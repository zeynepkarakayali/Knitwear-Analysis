#!/usr/bin/env python3
"""Collect product URLs from a brand's US category page (product pages are not visited).
Install: python -m pip install beautifulsoup4 playwright && python -m playwright install chromium
Usage (from the project root):  python scrapers/collect_links.py --brand zara|mango|massimodutti|bershka [--category URL]
Zara and Mango load products by scrolling; H&M by numbered pages (?page=N).
Images, media and fonts are blocked; CSS, scripts and XHR are kept for lazy loading.
Stops on access challenges or store redirects; no retries, no access-control bypass.
"""
import argparse
import importlib
import json
import sys
import time
from pathlib import Path
import common

DATA_RAW = Path('data/raw')  # run from the project root: data/raw/<brand>/links, products, saved

# Observe inserted cards so virtualized items are captured before they leave the DOM.
# Only href strings cross the browser/Python boundary, never the full page HTML.
INSTALL = r'''() => {
  const accept = __ACCEPT__;
  if (window.__linkObserver) window.__linkObserver.disconnect();
  window.__found = new Set();
  window.__pending = new Set();
  const scan = root => {
    const add = a => {
      if (accept(a) && a.href && !window.__found.has(a.href)) {
        window.__found.add(a.href); window.__pending.add(a.href);
      }
    };
    if (root.nodeType !== 1) return;
    if (root.matches('a[href]')) add(root);
    root.querySelectorAll('a[href]').forEach(add);
  };
  scan(document.documentElement);
  window.__linkObserver = new MutationObserver(ms => {
    for (const m of ms) {
      if (m.type === 'attributes') scan(m.target);
      else for (const n of m.addedNodes) scan(n);
    }
  });
  window.__linkObserver.observe(document.documentElement,
    {subtree: true, childList: true, attributes: true, attributeFilter: ['href']});
}'''
DRAIN = '() => {const out=[...window.__pending]; window.__pending.clear(); return out;}'
METRICS = '() => ({y: scrollY, h: innerHeight, total: document.documentElement.scrollHeight})'
SCROLL_TO_END = 'window.scrollTo(0, document.documentElement.scrollHeight)'


def scroll_collect(page, args, add, checkpoint, progress, timeout_error):
    """Infinite-scroll categories: scroll until the bottom stays quiet. Returns the stop reason."""
    page.evaluate(INSTALL.replace('__ACCEPT__', args.brand_module.CARD_JS))
    bottom_since = stalled_since = None
    for progress['rounds'] in range(1, args.max_scrolls + 1):
        common.check_block(page)
        changed = add(page.evaluate(DRAIN))
        now = time.monotonic()
        if changed:
            checkpoint()
        m = page.evaluate(METRICS)
        bottom = m['y'] + m['h'] >= m['total'] - 10
        if bottom:
            if changed or bottom_since is None:
                bottom_since = now
            if now - bottom_since >= args.end_wait:
                return 'bottom_quiet_timeout'
        else:
            bottom_since = None
        page.evaluate('window.scrollBy(0, Math.max(400, innerHeight * 0.85))')
        try:
            page.wait_for_function('window.__pending && window.__pending.size > 0', timeout=args.wait_ms)
        except timeout_error:
            pass
        if not bottom and page.evaluate(METRICS)['y'] == m['y'] and not changed:
            stalled_since = stalled_since or now
            if now - stalled_since >= args.end_wait:
                return 'scroll_stalled_incomplete'
        else:
            stalled_since = None
    return 'max_scrolls_reached_incomplete'


def paged_collect(page, args, add, checkpoint, progress, category):
    """Numbered-page categories: open ?page=1,2,... until a page adds no new models."""
    brand = args.brand_module
    links = f'() => [...document.querySelectorAll("a[href]")].filter({brand.CARD_JS}).map(a => a.href)'
    for progress['rounds'] in range(1, args.max_pages + 1):
        if progress['rounds'] > 1:
            time.sleep(args.delay)
            common.open_page(page, brand.page_url(category, progress['rounds']), brand)
        try:
            page.locator(brand.GRID_READY).first.wait_for(state='attached', timeout=25000)
        except Exception:
            common.check_block(page)  # raises if this is a deny page, not just an empty page
            return 'no_products_on_page'
        page.evaluate(SCROLL_TO_END)  # let lazy tiles render
        page.wait_for_timeout(1000)
        if not add(page.evaluate(links)):
            return 'page_without_new_models'
        checkpoint()
    return 'max_pages_reached_incomplete'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--brand', required=True, choices=common.BRANDS)
    ap.add_argument('--category', help='Category URL (default: the brand module CATEGORY)')
    ap.add_argument('--out', type=Path, help='Output folder (default: data/raw/<brand>/links)')
    ap.add_argument('--headless', action='store_true')
    ap.add_argument('--allow-media', action='store_true', help='Load images/fonts if blocking breaks lazy loading')
    ap.add_argument('--max-scrolls', type=int, default=400, help='Scroll mode limit')
    ap.add_argument('--wait-ms', type=int, default=1000, help='Scroll mode: maximum wait per scroll')
    ap.add_argument('--end-wait', type=float, default=8, help='Scroll mode: quiet seconds at bottom before stopping')
    ap.add_argument('--max-pages', type=int, default=60, help='Page mode limit')
    ap.add_argument('--delay', type=float, default=3, help='Page mode: seconds between pages (minimum 2)')
    args = ap.parse_args()
    brand = args.brand_module = importlib.import_module(args.brand)
    category = args.category or brand.CATEGORY
    out = args.out or DATA_RAW / args.brand / 'links'
    if not brand.in_store(category):
        ap.error(f'Use a {brand.BRAND} US HTTPS category URL (https://{brand.HOST}{brand.STORE}...).')
    if args.max_scrolls < 1 or args.wait_ms < 200 or args.end_wait < 3 or args.max_pages < 1 or args.delay < 2:
        ap.error('max-scrolls >= 1, wait-ms >= 200, end-wait >= 3, max-pages >= 1, delay >= 2 required')
    out.mkdir(parents=True, exist_ok=True)

    seen = {}
    progress = dict(rounds=0, blocked=0)
    reason, error = 'running', None
    started = common.now()

    def add(hrefs):
        before = len(seen)
        for href in hrefs:
            result = brand.clean_link(href)
            if result:  # every colour link is kept; colours not linked here are found on product pages
                seen.setdefault(result[1], result[1])
        if len(seen) != before:
            print(f'{len(seen)} product/colour links | round {progress["rounds"]}', flush=True)
        return len(seen) != before

    def checkpoint():
        common.atomic_write(out / 'urls.txt', ''.join(u + '\n' for u in seen.values()))
        common.atomic_write(out / 'manifest.json', json.dumps(dict(
            brand=brand.BRAND, category_url=category, started_at=started, updated_at=common.now(),
            stop_reason=reason, link_count=len(seen), rounds=progress['rounds'],
            blocked_resources=progress['blocked'], coverage_verified=False, error=error,
            sampling='all product/colour links in the category; process_products adds colours found on product pages'),
            ensure_ascii=False, indent=2))

    def route_request(route):
        if route.request.resource_type in {'image', 'media', 'font'}:
            progress['blocked'] += 1
            route.abort()
        else:
            route.continue_()

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    exit_code = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        try:
            context = browser.new_context(locale='en-US')
            if not args.allow_media:
                context.route('**/*', route_request)
            page = context.new_page()
            common.open_page(page, category, brand)
            if hasattr(brand, 'page_url'):
                reason = paged_collect(page, args, add, checkpoint, progress, category)
            else:
                page.locator(brand.GRID_READY).first.wait_for(state='attached', timeout=25000)
                reason = scroll_collect(page, args, add, checkpoint, progress, PWTimeout)
                add(page.evaluate(DRAIN))  # nodes inserted during the last wait
            if not seen:
                reason, exit_code = 'no_product_urls_found', 1
        except KeyboardInterrupt:
            reason, exit_code = 'interrupted_partial', 130
            print('\nInterrupted: collected links are saved.', flush=True)
        except Exception as exc:
            reason, error, exit_code = 'error_partial', str(exc), 1
            print('ERROR:', error, file=sys.stderr)
        finally:
            checkpoint()
            browser.close()
    print(f'{len(seen)} links -> {out / "urls.txt"}; {reason}')
    return exit_code


if __name__ == '__main__':
    sys.exit(main())