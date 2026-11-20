"""Bershka US: scrolling category links + product parser (validated on saved Oct 2026 US HTML).
Price comes from JSON-LD; composition, care and origin from the "Materials, care and source"
drawer, which open_details() opens (the saved test page was captured with it open).
"""
import json
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup
import common

BRAND = 'Bershka'
HOST, STORE = 'www.bershka.com', '/us/'
CATEGORY = 'https://www.bershka.com/us/women/clothes/sweaters-and-cardigans-n3870.html'
CARD_JS = (r"a => /^\/us\/[^/]+-c0p\d+\.html$/.test(a.pathname) && "
           r"!a.closest('header, nav, footer, dialog, .section-tree-menu, .bsk-drawer')")
GRID_READY = 'a[href*="-c0p"]'
# /us/v-neck-sweater-with-buttons-c0p232554433.html?colorId=814
PRODUCT_PATH = re.compile(r'/us/(?P<slug>[^/]+)-c0p(?P<product>\d+)\.html')
NAME = '.product-detail-info__title, h1'
DETAILS_BUTTON = 'button.extended-area-action'
COMPOSITION = '.product-compositions'
CONTENT_READY = '.product-compositions li, .product-cares__care'


def in_store(url):
    return common.in_store(url, HOST, STORE)


def clean_link(url):
    """(dedupe key, canonical URL keeping colorId) for a product link, else None. One colour per model."""
    p = urlparse(url)
    m = PRODUCT_PATH.fullmatch(p.path)
    if not in_store(url) or not m:
        return None
    colour = parse_qs(p.query).get('colorId')
    return m['product'], urlunparse(('https', HOST, p.path, '', urlencode({'colorId': colour[0]}) if colour else '', ''))


def dismiss_consent(page):
    reject = page.locator('#onetrust-reject-all-handler')
    if reject.count() and reject.first.is_visible():
        reject.first.click()


def open_details(page):
    """Open "Materials, care and source" and wait for its *content*, not just the empty drawer:
    the drawer element can exist before its lists are filled in."""
    page.locator('.product-detail-info__price').first.wait_for(state='attached', timeout=20000)
    if page.locator(CONTENT_READY).count():
        return
    button = page.locator(DETAILS_BUTTON).filter(has_text=re.compile(r'materials|composition|care', re.I))
    if not button.count():
        button = page.get_by_role('button', name=re.compile(r'materials|composition', re.I))
    if not button.count():
        return  # parse() records what is missing
    dismiss_consent(page)
    # A normal click first; if the drawer stays empty, a direct DOM click (no overlay checks).
    for attempt in ('click', 'dom_click'):
        try:
            button.first.scroll_into_view_if_needed(timeout=5000)
            if attempt == 'click':
                button.first.click(timeout=5000)
            else:
                button.first.evaluate('b => b.click()')
            page.locator(CONTENT_READY).first.wait_for(state='attached', timeout=10000)
            break
        except Exception:
            continue  # parse() records what is missing if both attempts fail
    try:
        page.locator('.product-origin__text').first.wait_for(state='attached', timeout=3000)
    except Exception:
        pass


def composition_parts(soup):
    """[('outer shell', 'main fabric', '69% polyester, 3% elastane, 28% viscose'), ...]
    Handles both layouts: sub-parts with a label (MAIN FABRIC / DETAILS, each with its own list)
    and a flat list of fibres directly under the layer heading (OUTER SHELL: 41% viscose, ...)."""
    root = soup.select_one(COMPOSITION)
    parts = []
    if not root:
        return parts
    for h3 in root.find_all('h3'):
        layer = common.norm(h3.get_text(' ', strip=True))
        box = h3.find_next_sibling('ul')
        if not box:
            continue
        flat = []
        for item in box.find_all('li', recursive=False):
            label = item.find('span')
            nested = [li.get_text(' ', strip=True) for li in item.find_all('li') if '%' in li.get_text()]
            if nested:
                parts.append((layer, common.norm(label.get_text(' ', strip=True)) if label else '', ', '.join(nested)))
            elif '%' in item.get_text():
                flat.append(item.get_text(' ', strip=True))
        if flat:
            parts.append((layer, '', ', '.join(flat)))
    return parts


def main_fabric(parts, warnings):
    """Outer shell main fabric if labelled, else the only outer-shell part, else the only part."""
    outer = [p for p in parts if p[0] in common.OUTER_LABELS or p[0] == 'outer shell']
    main = [p for p in outer if p[1] in ('main fabric', '')]
    for group in (main, outer, parts):
        if len(group) == 1:
            return group[0][2]
    if parts:
        warnings.append('multiple_or_unknown_material_sections')
    return None


def parse(html, url, captured_at=None):
    s = BeautifulSoup(html, 'html.parser')
    warnings = []
    m = PRODUCT_PATH.fullmatch(urlparse(url).path)

    product = {}
    for script in s.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or '')
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get('@type') == 'Product':
                product = item
    offers = product.get('offers') or []
    offers = offers if isinstance(offers, list) else [offers]
    try:
        current = float(offers[0]['price']) if offers else None
    except (KeyError, TypeError, ValueError):
        current = None
        warnings.append('invalid_price')
    block = s.select_one('.product-detail-info__price')
    shown = [float(x.replace(',', '')) for x in re.findall(r'\$\s*([\d,]+\.\d{2})', block.get_text())] if block else []
    currency = offers[0].get('priceCurrency') if offers else None
    if current is None:  # no JSON-LD: the first price shown in the product price block is the current one
        item = s.select_one('.product-detail-info__price [data-qa-anchor="productItemPrice"]')
        found = re.search(r'\$\s*([\d,]+\.\d{2})', item.get_text()) if item else None
        current, currency = (float(found[1].replace(',', '')), 'USD') if found else (None, currency)
    higher = [v for v in shown if current and v > current + 0.001]  # crossed-out price (untested)

    ref_text = common.txt(s, '.color-selector__reference') or ''
    ref = re.search(r'(\d{4})/(\d{3})/(\d{3})', ref_text)
    colour_node = s.select_one('.color-selector__name')
    if colour_node:
        for hidden in colour_node.select('.color-selector__sr-only'):
            hidden.extract()
    parts = composition_parts(s)
    care = [p.get_text(' ', strip=True) for p in s.select('.product-cares article p')]
    made_in = s.find(lambda t: t.name == 'p' and t.get_text(strip=True).startswith('Made in'))
    certified = [' '.join(d.get_text(' ', strip=True).split()) for d in s.select('.product-compositions li div')
                 if '%' in d.get_text() and not d.find('div')]  # "Containing at least: 69% RCS ..."
    name = product.get('name')
    if not name and s.title:  # "Fitted ribbed high neck sweater - BERSHKA LOVERS - Women"
        name = s.title.get_text().split(' - ')[0].strip() or None

    fields = dict(
        brand=BRAND, product_ref='/'.join(ref.groups()) if ref else None,
        model_id='/'.join(ref.groups()[:2]) if ref else (m['product'] if m else None),
        color_id=ref[3] if ref else parse_qs(urlparse(url).query).get('colorId', [None])[0],
        product_name=name[:1].upper() + name[1:] if name else None,
        product_url=url, country='US' if in_store(url) else None,
        currency=currency, price_current=current,
        price_original=max(higher) if higher else None,
        color=colour_node.get_text(' ', strip=True).title() if colour_node else None,
        description_raw=product.get('description'),
        composition_raw='; '.join(f'{a.capitalize()} / {b.capitalize()}: {c}' if b else f'{a.capitalize()}: {c}'
                                  for a, b, c in parts) or None,
        composition_outer_raw=main_fabric(parts, warnings),
        care_raw='; '.join(c.capitalize() for c in care) or None,
        origin_raw=' '.join(made_in.get_text(' ', strip=True).split()).replace('Made in', '').strip() if made_in else None,
        sustainability_raw='; '.join(dict.fromkeys(certified)) or None)
    return common.finalize(fields, warnings, html, captured_at)
