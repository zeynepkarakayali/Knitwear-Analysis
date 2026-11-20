"""Shared helpers for the brand scrapers (zara.py, mango.py).
Every brand produces rows with the same columns, so the CSVs can be concatenated.
"""
import csv
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]     # proje kökü
RAW = ROOT / "data" / "raw"                    # data/raw/<marka>/
MERGED = ROOT / "data" / "merged"              # models.csv, variants.csv, fibres.csv

BRANDS = ('zara', 'mango', 'hm', 'shein', 'uniqlo', 'cos', 'massimodutti', 'stories', 'bershka')  # module names, selected with --brand
CHALLENGE = ('access denied', 'captcha', 'just a moment', 'robot', 'are you a human')
BLOCK_TEXT = ("you don't have permission to access", 'errors.edgesuite.net', 'verify you are human',
              'unusual traffic', 'request blocked')
BLOCK_URL = ('captcha', '/risk/', 'challenge')

FIELDS = ('brand', 'product_ref', 'model_id', 'color_id', 'product_name', 'category', 'subcategory',
          'product_url', 'country', 'collected_at', 'currency', 'price_current', 'price_original',
          'color', 'description_raw', 'composition_raw', 'composition_outer_raw', 'care_raw',
          'origin_raw', 'sustainability_raw')
REQUIRED = ('model_id', 'product_name', 'price_current', 'currency', 'color', 'composition_outer_raw')

FIBERS = ('cotton', 'wool', 'cashmere', 'mohair', 'alpaca', 'polyester', 'acrylic', 'polyamide',
          'viscose', 'elastane', 'silk', 'linen', 'lyocell', 'modal')
ALIASES = {'nylon': 'polyamide', 'spandex': 'elastane', 'elastan': 'elastane', 'rayon': 'viscose',
           'merino': 'wool', 'lambswool': 'wool', 'tencel': 'lyocell', 'elasthane': 'elastane'}
QUALIFIERS = re.compile(r'\b(?:recycled|organic|merino|virgin|mulberry|extra ?fine)\b')
OUTER_LABELS = {'composition', 'outer shell', 'outer', 'exterior', 'shell', 'main fabric', 'fabric', 'body', 'outer layer'}

# Analysis scope: sweaters and cardigans (kept apart in the `category` column).
SCOPE = ('sweater', 'cardigan')
SWEATER = re.compile(r'\b(?:sweater|pullover|jumper)s?\b')
CARDIGAN = re.compile(r'\bcardigans?\b')
OUT_OF_SCOPE = re.compile(r'\b(?:sleeveless|vests?|dress|poncho|jacket|skirt|coat|gilet)\b')
SWEATER_SUBCATEGORIES = {'sweater', 'sweaters', 'jumper', 'jumpers', 'pullover', 'pullovers'}
CARDIGAN_SUBCATEGORIES = {'cardigan', 'cardigans'}


def brand_dir(brand: str) -> Path:
    d = RAW / brand
    d.mkdir(parents=True, exist_ok=True)
    return d


class Blocked(Exception):
    pass


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn')


def txt(root, selector):
    node = root.select_one(selector)
    return node.get_text(' ', strip=True) if node else None


def now():
    return datetime.now(timezone.utc).isoformat()


def in_store(url, host, store):
    p = urlparse(url)
    return p.scheme == 'https' and p.hostname == host and p.path.startswith(store)


def classify(name, subcategory=None):
    """'sweater', 'cardigan' or None. Vests, jackets, dresses etc. are out of scope; otherwise the
    site's own subcategory decides, then the product name (cardigan wins over sweater)."""
    value, sub = norm(name or ''), norm(subcategory or '')
    if OUT_OF_SCOPE.search(value):
        return None
    if sub in CARDIGAN_SUBCATEGORIES:
        return 'cardigan'
    if sub in SWEATER_SUBCATEGORIES:
        return 'sweater'
    if CARDIGAN.search(value):
        return 'cardigan'
    if SWEATER.search(value):
        return 'sweater'
    return None


def fiber_values(raw):
    """'63% acrylic, 4% merino wool' or 'Acrylic 63%, Wool 4%' -> {'acrylic_pct': 63.0, ...}, status.
    Fibres outside FIBERS (yak, acetate, ...) go to other_pct and are named in other_fibres."""
    columns = [f + '_pct' for f in FIBERS] + ['other_pct']
    empty = dict.fromkeys(columns + ['other_fibres'])
    if not raw:
        return empty, 'missing'
    text = re.sub(r'\([^)]*\)', ' ', norm(raw))  # "Silk (mulberry) 8%" -> "Silk 8%"
    if re.match(r'\s*\d', text):  # Zara/Mango: number before fibre
        pairs = re.findall(r'(\d+(?:[.,]\d+)?)\s*%\s*([^\d%]+)', text)
    else:                          # H&M: fibre before number
        pairs = [(a, l) for l, a in re.findall(r'([^\d%,;:]+?)\s*(\d+(?:[.,]\d+)?)\s*%', text)]
    if not pairs or len(pairs) != text.count('%'):
        return empty, 'manual_review'
    result, others = dict.fromkeys(columns, 0.0), []
    for amount, label in pairs:
        label = label.strip(' ,;:.\n')
        label = ALIASES.get(label, label)
        label = ' '.join(QUALIFIERS.sub(' ', label).split()) or label
        label = ALIASES.get(label, label)
        if label not in FIBERS:  # "rcs certified recycled wool", "tencel lyocell" -> the fibre word
            known = [w for w in re.findall(r'[a-z]+', label) if ALIASES.get(w, w) in FIBERS]
            label = ALIASES.get(known[-1], known[-1]) if known else label
        if not re.fullmatch(r'[a-z][a-z \-]{1,30}', label):  # not a fibre name: leave for review
            return empty, 'manual_review'
        if label in FIBERS:
            result[label + '_pct'] += float(amount.replace(',', '.'))
        else:
            result['other_pct'] += float(amount.replace(',', '.'))
            others.append(label)
    if abs(sum(result.values()) - 100) > 0.1:
        return empty, 'invalid_total'
    result['other_fibres'] = ', '.join(dict.fromkeys(others)) or None
    return result, 'parsed_complete'


def outer_composition(items, warnings):
    """Pick the main-fabric line from ['Outer shell: 100% wool', 'Lining: ...'] style items."""
    parts = []
    for item in items:
        label, sep, value = item.partition(':')
        parts.append((norm(label).strip(), value.strip()) if sep else ('', item.strip()))
    if len(parts) == 1:
        return parts[0][1] or None
    main = [value for label, value in parts if label in OUTER_LABELS]
    if len(main) == 1:
        return main[0]
    if parts:
        warnings.append('multiple_or_unknown_material_sections')
    return None


def finalize(fields, warnings, html, captured_at):
    """Fill the standard columns, parse fibres and set collection_status."""
    row = dict.fromkeys(FIELDS)
    row.update(fields)
    row['collected_at'] = captured_at
    if 'category' not in fields:  # brands with a reliable product-type field set it themselves
        row['category'] = classify(row['product_name'], row['subcategory'])
    values, status = fiber_values(row['composition_outer_raw'])
    row.update(values)
    row['composition_parse_status'] = status
    warnings += ['missing:' + k for k in REQUIRED if row[k] is None]
    if status != 'parsed_complete':
        warnings.append('composition:' + status)
    if not captured_at:
        warnings.append('capture_time_unknown_saved_html')
    row['warnings'] = warnings
    if 'url_model_mismatch' in warnings:
        row['collection_status'] = 'identity_mismatch'
    elif not row['product_name']:
        row['collection_status'] = 'not_extracted'
    elif any(w != 'capture_time_unknown_saved_html' for w in warnings):
        row['collection_status'] = 'partial'
    else:
        row['collection_status'] = 'complete'
    row['source_sha256'] = hashlib.sha256(html.encode()).hexdigest()
    return row


COMPUTED = {'other_fibres', 'composition_parse_status', 'warnings', 'collection_status', 'source_sha256',
            'collected_at', *(f + '_pct' for f in FIBERS), 'other_pct'}


def variant_row(base, html, captured_at, **overrides):
    """Another colour of the same model, built from data on the same page: copy the parsed row,
    replace the colour-specific fields, and recompute fibres and status for it."""
    fields = {k: v for k, v in base.items() if k not in COMPUTED}
    fields.update(overrides, variant_source='same_page')
    warnings = [w for w in base.get('warnings', [])
                if not w.startswith(('missing:', 'composition:', 'capture_time'))]
    return finalize(fields, warnings, html, captured_at)


def check_block(page, response=None):
    """Raise Blocked if the server refused access (status code, page title or deny-page text)."""
    if response and response.status in (401, 403, 429):
        raise Blocked('HTTP ' + str(response.status))
    if any(x in page.url.lower() for x in BLOCK_URL):
        raise Blocked('Redirected to a challenge page: ' + page.url)
    title = page.title().lower()
    if any(x in title for x in CHALLENGE):
        raise Blocked('Access challenge: ' + title)
    try:
        body = page.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 3000)").lower()
    except Exception:
        return
    if any(x in body for x in BLOCK_TEXT):
        raise Blocked('Access denied page: ' + ' '.join(body.split())[:120])


def open_page(page, url, brand):
    """Navigate, stop on blocks or store redirects, handle the consent banner."""
    response = page.goto(url, wait_until='domcontentloaded', timeout=45000)
    check_block(page, response)
    if response and response.status >= 400:
        raise RuntimeError('HTTP ' + str(response.status))
    if not brand.in_store(page.url):
        raise RuntimeError('Redirected out of the US store: ' + page.url)
    brand.dismiss_consent(page)


def record_key(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def atomic_write(path, text):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(text, encoding='utf-8')
    temp.replace(path)


def write_json(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_csv(records):
    rows = [read_json(p) for p in sorted(records.glob('*.json'))]
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (records.parent / 'products.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in r.items()})
