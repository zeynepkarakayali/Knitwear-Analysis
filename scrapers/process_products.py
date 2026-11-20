#!/usr/bin/env python3
"""Scrape product pages collected by collect_links.py into data/raw/<brand>/products/products.csv.
Run from the project root.
Install: python -m pip install beautifulsoup4 playwright && python -m playwright install chromium
Live:    python scrapers/process_products.py --brand zara|mango|massimodutti|bershka
Offline: python scrapers/process_products.py --brand cos --html data/raw/cos/saved/
         (a folder of pages saved from your own browser; one .html file also works)
Stops on access challenges; no retries or bypass.
"""
import argparse
import importlib
import html as html_lib
import json
import re
import time
from urllib.parse import urlparse
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup
import common

DATA_RAW = Path('data/raw')  # run from the project root: data/raw/<brand>/links, products, saved


def collect(page, url, brand, debug_dir=None):
    common.open_page(page, url, brand)
    try:
        brand.open_details(page)
    except Exception:
        common.check_block(page)  # a deny page that loaded late shows up as a timeout
        raise
    html = page.content()
    rows = parse_all(brand, html, page.url, common.now())
    for row in rows:
        row['requested_url'] = url
        row['source_mode'] = 'browser'
    row = rows[0]
    row['_record_url'] = url  # the visited colour is filed under the URL that was requested
    if debug_dir and row['collection_status'] != 'complete':
        # Keep the page exactly as the scraper saw it: send it for debugging, or fix the parser
        # and re-process later with --html <out>/incomplete_pages/
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / (common.record_key(url) + '.html')).write_text(html, encoding='utf-8')
    return rows, colour_links(page, brand)


def parse_all(brand, html, url, captured_at):
    """Rows for every colour the page describes: [this colour, other colours on the same page...].
    Brands without per-colour data on the page return just this colour."""
    if hasattr(brand, 'parse_variants'):
        return brand.parse_variants(html, url, captured_at)
    return [brand.parse(html, url, captured_at)]


def colour_links(page, brand):
    """Links on the page to other colours of the same model (same dedupe key, different URL)."""
    here = brand.clean_link(page.url)
    if not here:
        return []
    hrefs = page.evaluate('() => [...document.querySelectorAll("a[href]")].map(a => a.href)')
    found = (brand.clean_link(h) for h in hrefs)
    # A link without a colour parameter opens the default colour, usually one already seen.
    colour_param = bool(urlparse(here[1]).query)
    return list(dict.fromkeys(u for k, u in filter(None, found)
                              if k == here[0] and u != here[1] and (urlparse(u).query or not colour_param)))


def saved_page_url(html):
    """The product URL a saved page declares about itself (canonical link, else og:url).
    Tags are found with a regex over the whole file: on large pages (e.g. SHEIN, ~5 MB)
    they can sit far below the top, and parsing the full page only for this would be slow."""
    for pattern, attr in ((r'<link\b[^>]*\brel=["\']canonical["\'][^>]*>', 'href'),
                          (r'<meta\b[^>]*\bproperty=["\']og:url["\'][^>]*>', 'content')):
        for tag in re.findall(pattern, html, re.I):
            value = re.search(rf'\b{attr}=["\']([^"\']+)["\']', tag)
            if value:
                return html_lib.unescape(value[1])  # decode &amp; etc.
    return None


# Exclusion reasons that still apply; rows excluded under an older rule (sweater-only scope,
# one colour per model) are collected again.
CURRENT_EXCLUSIONS = ('not_sweater_or_cardigan',)


def paths_for(url, records, excluded_dir):
    key = common.record_key(url)
    return records / (key + '.json'), excluded_dir / (key + '.json')


def store(row, records, excluded_dir, include_all):
    """Write one colour's row to records/ or excluded/; returns a short status for printing.
    Every colour is kept (one row per model *and* colour); merge_products.py builds the model table."""
    record, excluded = paths_for(row.pop('_record_url', None) or row['product_url'], records, excluded_dir)
    label = f"{row['product_name']} [{row.get('color')}]"
    if not include_all and row['product_name'] and row['category'] not in common.SCOPE:
        row['exclusion_reason'] = 'not_sweater_or_cardigan'
        common.write_json(excluded, row)
        return 'EXCLUDED ' + label
    common.write_json(record, row)
    excluded.unlink(missing_ok=True)  # e.g. a colour excluded under the old one-colour-per-model rule
    return f"{row['collection_status']} {label} {row['price_current']}"


def process_saved(args, brand, records, excluded_dir, error):
    """Offline mode: parse saved HTML files (a file or every .html/.htm/.txt in a folder)."""
    files = sorted(f for ext in ('*.html', '*.htm', '*.txt') for f in args.html.glob(ext)) \
        if args.html.is_dir() else [args.html]
    if not files:
        error(f'No .html files in {args.html}')
    for path in files:
        html = path.read_text(encoding='utf-8', errors='replace')
        url = args.url if args.url and len(files) == 1 else saved_page_url(html)
        if not url or not brand.in_store(url):
            print('SKIP (not a', brand.BRAND, 'US product page):', path.name)
            continue
        # The file's save time is the best available capture time for a saved page.
        saved_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        for row in parse_all(brand, html, url, saved_at):
            row.update(source_mode='saved_html', source_file=path.name, collected_at_source='file_mtime')
            print(path.name, '->', store(row, records, excluded_dir, args.include_all))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--brand', required=True, choices=common.BRANDS)
    p.add_argument('--urls', type=Path, help='One product URL per line (default: data/raw/<brand>/links/urls.txt)')
    p.add_argument('--html', type=Path, help='Offline mode: a saved product page or a folder of them')
    p.add_argument('--url', help='Override the URL of a single saved page (normally read from the page)')
    p.add_argument('--include-all', action='store_true', help='Keep products other than sweaters/cardigans too')
    p.add_argument('--out', type=Path, help='Output folder (default: data/raw/<brand>/products)')
    p.add_argument('--limit', type=int, default=0, help='Maximum attempted products per run; 0 = all')
    p.add_argument('--delay', type=float, default=4, help='Seconds between pages (minimum 2)')
    p.add_argument('--max-errors', type=int, default=3, help='Stop after this many consecutive errors')
    p.add_argument('--headless', action='store_true')
    args = p.parse_args()
    brand = importlib.import_module(args.brand)
    out = args.out or DATA_RAW / args.brand / 'products'
    url_file = args.urls or DATA_RAW / args.brand / 'links' / 'urls.txt'
    if args.limit < 0 or args.delay < 2 or args.max_errors < 1:
        p.error('limit >= 0, delay >= 2 and max-errors >= 1 required')
    records, excluded_dir = out / 'records', out / 'excluded'
    records.mkdir(parents=True, exist_ok=True)

    # One colour per model: SHEIN lists every colour as its own product page.
    if args.html:
        if not args.html.exists():
            p.error(f'{args.html} not found')
        process_saved(args, brand, records, excluded_dir, p.error)
        common.write_csv(records)
        print('->', out / 'products.csv')
        return

    if not url_file.exists():
        p.error(f'{url_file} not found. Run collect_links.py --brand {args.brand} first.')
    lines = url_file.read_text(encoding='utf-8').splitlines()
    urls = list(dict.fromkeys(u.strip() for u in lines if u.strip() and not u.lstrip().startswith('#')))
    if not urls:
        p.error('URL list is empty. Run collect_links.py first.')
    bad = [u for u in urls if not brand.in_store(u)]
    if bad:
        p.error(f'{len(bad)} URL(s) are not {brand.BRAND} US pages, e.g. {bad[0]}')

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        page = browser.new_context(locale='en-US').new_page()
        attempted = consecutive_errors = 0
        queue, queued = deque(urls), set(urls)
        try:
            while queue:
                url = queue.popleft()
                record, excluded = paths_for(url, records, excluded_dir)
                if excluded.exists() and not args.include_all and \
                        common.read_json(excluded).get('exclusion_reason') in CURRENT_EXCLUSIONS:
                    print('SKIP excluded', url)
                    continue
                if record.exists() and common.read_json(record).get('collection_status') == 'complete':
                    print('SKIP', url)
                    continue
                if args.limit and attempted >= args.limit:
                    break
                if attempted:
                    time.sleep(args.delay)
                attempted += 1
                try:
                    rows, links = collect(page, url, brand, out / 'incomplete_pages')
                    consecutive_errors = 0
                    for row in rows:
                        print(store(row, records, excluded_dir, args.include_all))
                    if rows[0]['category'] in common.SCOPE or args.include_all:
                        # Other colours of an in-scope model: same-page rows are already complete
                        # and are skipped when reached; linked colours are visited.
                        new = [u for u in links if u not in queued]
                        queue.extend(new)
                        queued.update(new)
                        if new:
                            print(f'  + {len(new)} colour link(s) queued')
                except Exception as exc:
                    with (out / 'errors.jsonl').open('a', encoding='utf-8') as f:
                        f.write(json.dumps({'url': url, 'time': common.now(), 'error': str(exc)},
                                           ensure_ascii=False) + '\n')
                    print('ERROR', url, exc)
                    if isinstance(exc, common.Blocked):
                        print('Access restricted. Stopping without retries.')
                        break
                    consecutive_errors += 1
                    if consecutive_errors >= args.max_errors:
                        print(f'{consecutive_errors} errors in a row; stopping. Check errors.jsonl before rerunning.')
                        break
        finally:
            browser.close()
            common.write_csv(records)


if __name__ == '__main__':
    main()