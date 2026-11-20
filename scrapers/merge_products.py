#!/usr/bin/env python3
"""Merge every data/raw/<brand>/products/products.csv into a normalised dataset (three linked tables):

  data/dataset/models.csv    one row per model     (key: model_key = brand:model_id)
  data/dataset/variants.csv  one row per colour    (key: variant_key = brand:model_id:color_id; has model_key)
  data/dataset/fibres.csv    one row per colour and fibre, long format (variant_key, model_key, fibre, pct)

Usage (from the project root):  python scrapers/merge_products.py [--root .] [--out-dir data/dataset] [--keep-all]
The brand key is the folder name under data/raw/, so it must be the --brand name (stories, not otherstories).
Needs common.py in the same folder; no extra packages.

What it reconciles between brands:
- Columns: the union of all columns, in a fixed order (shared fields, fibre %, status,
  brand-only extras such as weight_g / fit / on_sale / supplier_factory, then provenance).
  A column a brand does not have is left empty for that brand's rows.
- Older column names from earlier scraper versions are renamed (product_id -> product_ref, ...).
- Fibre % columns are recomputed from composition_outer_raw with the current fibre rules,
  so every brand is parsed the same way; unknown fibres go to other_pct / other_fibres.
- Numbers are written as plain numbers; empty means unknown, never 0.
- on_sale / discount_pct are unified (Uniqlo flags sales without showing the old price).
- origin_country is extracted from the brand-specific origin text ("Made in Turkey",
  "Manufacture: China", "Mainland China" -> China; "Imported" -> empty).
- The same colour collected twice (re-runs, live + saved page) is kept once: complete rows win
  over partial ones, then the most recent collection.
- By default only sweaters and cardigans are kept (rows from --include-all runs are dropped).

Weighting: a model with many colours has many rows in variants/fibres. For brand comparisons,
aggregate to models first (models.csv, or groupby model_key) so every model counts once.
"""
import argparse
import csv
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import common

LEGACY_NAMES = {'product_id': 'product_ref', 'requested_variant_id': 'variant_id',
                'traceability_raw': 'origin_raw'}
DROP = {'extracted_at', 'source_sha256'}  # always empty or not useful in the merged file
FIBRE_COLUMNS = [f + '_pct' for f in common.FIBERS] + ['other_pct', 'other_fibres']
NUMERIC = {'price_current', 'price_original', 'weight_g', 'discount_pct', *FIBRE_COLUMNS} - {'other_fibres'}
STATUS = ['composition_parse_status', 'collection_status', 'warnings']
DERIVED = ['on_sale', 'discount_pct', 'origin_country', 'collected_date']
PROVENANCE = ['brand_key', 'source_mode', 'source_file', 'collected_at_source', 'requested_url', 'source_csv']
STATUS_RANK = {'complete': 0, 'partial': 1, 'identity_mismatch': 2, 'not_extracted': 3}
COUNTRY_NAMES = {'mainland china': 'China', 'china': 'China', 'turkiye': 'Turkey', 'turkey': 'Turkey',
                 'viet nam': 'Vietnam', 'vietnam': 'Vietnam', 'bangladesh': 'Bangladesh',
                 'cambodia': 'Cambodia', 'india': 'India', 'pakistan': 'Pakistan', 'morocco': 'Morocco',
                 'portugal': 'Portugal', 'italy': 'Italy', 'spain': 'Spain', 'myanmar': 'Myanmar',
                 'indonesia': 'Indonesia', 'sri lanka': 'Sri Lanka', 'romania': 'Romania',
                 'bulgaria': 'Bulgaria', 'mongolia': 'Mongolia', 'egypt': 'Egypt', 'tunisia': 'Tunisia'}


def number(value):
    if value in (None, ''):
        return None
    try:
        return float(str(value).replace(',', '.'))
    except ValueError:
        return None


def truthy(value):
    return str(value).strip().lower() in ('true', '1', 'yes')


def origin_country(text):
    """Best-effort manufacturing country from the brand's origin text; None if not stated."""
    if not text:
        return None
    value = common.norm(text)
    match = re.search(r'manufactur\w*\s*:\s*([a-z .]+)', value) or re.search(r'made in\s+([a-z .]+)', value)
    candidate = (match[1] if match else value).strip(' .;')
    for name, canonical in COUNTRY_NAMES.items():
        if re.search(rf'\b{name}\b', candidate):
            return canonical
    return None  # e.g. "Imported" or a long traceability paragraph without a country


def read_brand_csv(path):
    """Rows of one brand CSV with legacy column names mapped to the current ones."""
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    brand_key = path.parent.parent.name  # data/raw/<brand>/products/products.csv
    for row in rows:
        for old, new in LEGACY_NAMES.items():
            if old in row:
                value = row.pop(old)
                if value and not row.get(new):
                    row[new] = value
        for column in DROP:
            row.pop(column, None)
        row['brand_key'] = brand_key
        row['source_csv'] = str(path)
    return rows


def normalise(row):
    """Clean one row in place and add the derived columns."""
    for key, value in list(row.items()):
        if isinstance(value, str):
            row[key] = ' '.join(value.split()) or None
    # Same fibre rules for every brand, whatever version of the scraper wrote the CSV.
    values, status = common.fiber_values(row.get('composition_outer_raw'))
    row.update(values)
    row['composition_parse_status'] = status
    if not row.get('category'):
        row['category'] = common.classify(row.get('product_name'), row.get('subcategory'))
    for column in NUMERIC:
        if column in row:
            row[column] = number(row[column])
    current, original = row.get('price_current'), row.get('price_original')
    marked = truthy(row.get('on_sale'))
    reduced = bool(current and original and original > current)
    row['on_sale'] = reduced or marked
    row['discount_pct'] = round(100 * (original - current) / original, 1) if reduced else None
    row['origin_country'] = origin_country(row.get('origin_raw'))
    try:
        row['collected_date'] = datetime.fromisoformat(row['collected_at']).date().isoformat()
    except (KeyError, TypeError, ValueError):
        row['collected_date'] = None
    return row


def best_per_variant(rows):
    """One row per (brand, model, colour): complete beats partial, then the most recent collection.
    Duplicates come from re-runs, live + saved pages, or the same colour reached by two URLs."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row['brand_key'], row.get('model_id') or row.get('product_url'),
                row.get('color_id') or row.get('color') or row.get('product_url'))].append(row)
    keep, dropped = [], Counter()
    for (brand_key, _, _), group in groups.items():
        group.sort(key=lambda r: r.get('collected_at') or '', reverse=True)      # newest first ...
        group.sort(key=lambda r: STATUS_RANK.get(r.get('collection_status'), 9))  # ... within best status
        keep.append(group[0])
        dropped[brand_key] += len(group) - 1
    for row in keep:  # keys that are unique across brands, for joining the tables
        row['model_key'] = f"{row['brand_key']}:{row.get('model_id') or row.get('product_url')}"
        row['variant_key'] = f"{row['model_key']}:{row.get('color_id') or row.get('color') or row.get('product_url')}"
    return keep, dropped


def column_order(rows):
    present = list(dict.fromkeys(k for r in rows for k in r))
    fixed = ['variant_key', 'model_key'] + list(common.FIELDS) + FIBRE_COLUMNS + STATUS + DERIVED
    extras = sorted(k for k in present if k not in fixed and k not in PROVENANCE)
    return [c for c in fixed if c in present] + extras + [c for c in PROVENANCE if c in present]


def most_common(values):
    values = [v for v in values if v not in (None, '')]
    return Counter(values).most_common(1)[0][0] if values else None


def build_models(variants):
    """One row per model, summarising its colours. Fibre % are averaged over the colours whose
    composition was parsed (colours of one model rarely differ, see composition_varies)."""
    groups = defaultdict(list)
    for row in variants:
        groups[row['model_key']].append(row)
    models = []
    for model_key, group in groups.items():
        prices = sorted(r['price_current'] for r in group if r.get('price_current') is not None)
        parsed = [r for r in group if r.get('composition_parse_status') == 'parsed_complete']
        compositions = {r.get('composition_outer_raw') for r in group if r.get('composition_outer_raw')}
        discounts = [r['discount_pct'] for r in group if r.get('discount_pct') is not None]
        dates = sorted(r['collected_date'] for r in group if r.get('collected_date'))
        model = dict(
            model_key=model_key, brand=group[0].get('brand'), brand_key=group[0]['brand_key'],
            model_id=group[0].get('model_id'), product_name=most_common(r.get('product_name') for r in group),
            category=most_common(r.get('category') for r in group),
            subcategory=most_common(r.get('subcategory') for r in group),
            n_colours=len(group), n_colours_parsed=len(parsed),
            price_min=prices[0] if prices else None, price_max=prices[-1] if prices else None,
            price_median=prices[len(prices) // 2] if prices else None,
            any_on_sale=any(r.get('on_sale') for r in group),
            max_discount_pct=max(discounts) if discounts else None,
            composition_outer_raw=compositions.pop() if len(compositions) == 1 else None,
            composition_varies=len(compositions) > 1,
            origin_country=most_common(r.get('origin_country') for r in group),
            first_collected=dates[0] if dates else None, last_collected=dates[-1] if dates else None)
        for column in FIBRE_COLUMNS:
            if column == 'other_fibres':
                model[column] = ', '.join(dict.fromkeys(f for r in parsed for f in (r.get(column) or '').split(', ') if f)) or None
            else:
                model[column] = round(sum(r[column] or 0 for r in parsed) / len(parsed), 2) if parsed else None
        models.append(model)
    return models


def build_fibres(variants):
    """Long format: one row per colour and fibre present (pct > 0), parsed compositions only."""
    rows = []
    for row in variants:
        if row.get('composition_parse_status') != 'parsed_complete':
            continue
        for fibre in common.FIBERS + ('other',):
            pct = row.get(fibre + '_pct')
            if pct:
                rows.append(dict(variant_key=row['variant_key'], model_key=row['model_key'],
                                 brand=row.get('brand'), brand_key=row['brand_key'], fibre=fibre, pct=pct,
                                 fibre_names=row.get('other_fibres') if fibre == 'other' else None))
    return rows


def write_csv(path, rows, columns):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ('' if row.get(k) is None else row.get(k)) for k in columns})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, default=Path('.'), help='Project root (contains data/raw/<brand>/products)')
    ap.add_argument('--out-dir', type=Path, default=Path('data/dataset'))
    ap.add_argument('--keep-all', action='store_true', help='Keep rows outside sweaters/cardigans too')
    args = ap.parse_args()

    sources = sorted(args.root.glob('data/raw/*/products/products.csv'))
    if not sources:
        ap.error(f'No */products.csv under {args.root.resolve()}')

    rows, columns_by_brand = [], {}
    for path in sources:
        brand_rows = read_brand_csv(path)
        columns_by_brand[path.parent.parent.name] = set().union(*brand_rows) if brand_rows else set()
        rows += [normalise(r) for r in brand_rows]

    out_of_scope = Counter(r['brand_key'] for r in rows if r.get('category') not in common.SCOPE)
    if not args.keep_all:
        rows = [r for r in rows if r.get('category') in common.SCOPE]
    variants, duplicates = best_per_variant(rows)
    variants.sort(key=lambda r: (r['brand_key'], r.get('category') or '', r.get('product_name') or '',
                                 r.get('color') or ''))
    models = build_models(variants)
    models.sort(key=lambda m: (m['brand_key'], m.get('category') or '', m.get('product_name') or ''))
    fibres = build_fibres(variants)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    columns = column_order(variants)
    write_csv(args.out_dir / 'variants.csv', variants, columns)
    write_csv(args.out_dir / 'models.csv', models, list(models[0]) if models else ['model_key'])
    write_csv(args.out_dir / 'fibres.csv', fibres,
              ['variant_key', 'model_key', 'brand', 'brand_key', 'fibre', 'pct', 'fibre_names'])

    # Summary
    print(f'{len(models)} models, {len(variants)} colours, {len(fibres)} fibre rows -> {args.out_dir}/'
          '{models,variants,fibres}.csv\n')
    print(f'{"brand":<14}{"models":>7}{"colours":>9}{"sweater":>9}{"cardigan":>10}{"complete":>10}'
          f'{"no comp.":>10}{"dupes":>7}{"dropped":>9}')
    by_brand, models_by_brand = defaultdict(list), Counter(m['brand_key'] for m in models)
    for row in variants:
        by_brand[row['brand_key']].append(row)
    for brand_key in sorted(columns_by_brand):
        group = by_brand.get(brand_key, [])
        count = Counter(m.get('category') for m in models if m['brand_key'] == brand_key)
        print(f'{brand_key:<14}{models_by_brand[brand_key]:>7}{len(group):>9}{count["sweater"]:>9}'
              f'{count["cardigan"]:>10}{sum(r.get("collection_status") == "complete" for r in group):>10}'
              f'{sum(r["composition_parse_status"] != "parsed_complete" for r in group):>10}'
              f'{duplicates[brand_key]:>7}{0 if args.keep_all else out_of_scope[brand_key]:>9}')
    currencies = Counter(r.get('currency') for r in variants)
    if len(currencies) > 1:
        print('\nWARNING: more than one currency:', dict(currencies))
    varies = [m for m in models if m['composition_varies']]
    if varies:
        print(f'\n{len(varies)} model(s) have colours with different compositions (see variants.csv).')
    brands = sorted(columns_by_brand)
    partial = {}
    for column in columns:
        if column in PROVENANCE or column in FIBRE_COLUMNS or column in STATUS or column in DERIVED \
                or column in ('variant_key', 'model_key'):
            continue
        having = [b for b in brands if column in columns_by_brand[b]]
        if len(having) != len(brands):
            partial[column] = having
    if partial:
        print('\nColumns not every brand CSV has (left empty for the others):')
        for column, having in partial.items():
            missing = [b for b in brands if b not in having]
            text = 'only ' + ', '.join(having) if len(having) <= len(missing) else 'missing in ' + ', '.join(missing)
            print(f'  {column:<20} {text}')
    print('\nmodels = colours = rows per table; "no comp." = colours whose composition is missing/unparsed;'
          '\n"dupes" = repeated colour rows removed; "dropped" = rows outside sweaters/cardigans.')


if __name__ == '__main__':
    main()