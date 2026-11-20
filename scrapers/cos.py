"""COS US: paginated category links + product parser.
Name, price, colour and category come from JSON-LD (validated on saved Oct 2026 US HTML).
Composition, care and supplier country are NOT in the initial HTML: they load in the
"Details & Description" drawer (tabs: Details, Care Guide, Materials and Suppliers).
open_details() opens it; drawer markup validated on a page saved with the drawer open.
"""
import json
import re
from urllib.parse import urlparse, urlencode, urlunparse
from bs4 import BeautifulSoup
import common

BRAND = 'COS'
HOST, STORE = 'www.cos.com', '/en-us/'
CATEGORY = 'https://www.cos.com/en-us/women/knitwear'
CARD_JS = r"a => /\/product\/[^/]+-\d{10}\/?$/.test(a.pathname) && !a.closest('header, nav, footer, dialog')"
GRID_READY = 'a[href*="/product/"]'
# /en-us/women/womenswear/knitwear/jumpers/cashmere/product/chunky-...-charcoal-1323214008
PRODUCT_PATH = re.compile(r'/en-us/(?:[^/]+/)*product/(?P<slug>[^/]+)-(?P<article>(?P<model>\d{7})(?P<color>\d{3}))/?')
NAME = 'h1'
DETAILS_BUTTON = '[data-testid="product-info-navigation-details-and-description-button"]'
DRAWER = '[data-testid^="product-details-drawer"]'
MATERIALS = '[data-testid="product-details-drawer-materials"]'
SUPPLIER = '[data-testid="product-details-drawer-supplier"] li'
CARE = '[data-testid="product-details-drawer-care-instructions"] li'
FIBRE_LINE = re.compile(r'\d+(?:[.,]\d+)?\s*%\s*[A-Za-z]|[A-Za-z]+\s+\d+(?:[.,]\d+)?\s*%')


def in_store(url):
    return common.in_store(url, HOST, STORE)


def page_url(category, n):
    """Category listing page n (the site links '?page=2' from its 'Loading (48/259)' control)."""
    p = urlparse(category)
    return urlunparse(p._replace(query=urlencode({'page': n}), fragment=''))


def clean_link(url):
    """(dedupe key, canonical URL) for a product link, else None. One colour per model."""
    p = urlparse(url)
    m = PRODUCT_PATH.fullmatch(p.path)
    if not in_store(url) or not m:
        return None
    return m['model'], urlunparse(('https', HOST, p.path.rstrip('/'), '', '', ''))


def dismiss_consent(page):
    reject = page.locator('#onetrust-reject-all-handler')
    if reject.count() and reject.first.is_visible():
        reject.first.click()


def open_details(page):
    """Open 'Details & Description', then the 'Materials and Suppliers' and 'Care Guide' tabs."""
    page.locator(NAME).first.wait_for(state='visible', timeout=20000)
    button = page.locator(DETAILS_BUTTON)
    if not button.count():
        return
    dismiss_consent(page)
    button.first.click()
    for name, ready in ((r'care guide', CARE), (r'materials', MATERIALS)):
        try:
            page.get_by_role('tab', name=re.compile(name, re.I)).first.click(timeout=3000)
            page.locator(ready).first.wait_for(state='attached', timeout=8000)
        except Exception:
            pass  # parse() records what is missing


def fibre_lines(soup):
    """Lines like 'Shell: 100% Wool' from the Materials section (other drawer parts as fallback)."""
    roots = soup.select(MATERIALS) or soup.select(DRAWER) or [soup]
    lines = []
    for root in roots:
        for text in root.find_all(string=FIBRE_LINE):
            if text.find_parent(['script', 'style', 'footer', 'nav', 'header']):
                continue
            line = ' '.join(text.parent.get_text(' ', strip=True).split())
            if line not in lines and 'off' not in line.lower():
                lines.append(line)
    return lines


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
    sku = product.get('sku')
    if m and sku and sku != m['article']:
        warnings.append('url_model_mismatch')
    offers = product.get('offers') or []
    offers = offers if isinstance(offers, list) else [offers]
    try:
        current = float(offers[0]['price']) if offers else None
    except (KeyError, TypeError, ValueError):
        current = None
        warnings.append('invalid_price')

    # Main product price block: a higher second price next to it is taken as the original (untested).
    title = s.select_one(NAME)
    block = title.parent.parent if title else None
    shown = [float(x.replace(',', '')) for p in (block.select('[data-testid="product-price"]') if block else [])
             for x in re.findall(r'\$([\d,]+(?:\.\d{2})?)', p.get_text())]
    higher = [v for v in shown if current and v > current + 0.001]

    path = [common.norm(x.strip()) for x in (product.get('category') or {}).get('name', '').split('>')]
    subcategory = path[3] if len(path) > 3 else None
    name = product.get('name') or (title.get_text(' ', strip=True) if title else None)
    category = common.classify(name, subcategory)

    lines = fibre_lines(s)
    care = [li.get_text(' ', strip=True) for li in s.select(CARE)] or [
        li.get_text(' ', strip=True) for li in s.select('[data-testid="product-details-drawer-description-tab"] li')
        if re.search(r'wash|clean|iron|dry|bleach', li.get_text(), re.I)]
    supplier = {}
    for li in s.select(SUPPLIER):
        label = li.find('span')
        if label:
            supplier[label.get_text(strip=True).lower()] = ' '.join(
                li.get_text(' ', strip=True)[len(label.get_text(strip=True)):].split())
    fields = dict(
        brand=BRAND, product_ref=sku, model_id=sku[:7] if sku else (m['model'] if m else None),
        color_id=sku[7:] if sku else (m['color'] if m else None),
        product_name=name.title() if name else None, category=category, subcategory=subcategory,
        product_url=url, country='US' if in_store(url) else None,
        currency=offers[0].get('priceCurrency') if offers else None,
        price_current=current, price_original=max(higher) if higher else None,
        color=(product.get('color') or '').title() or None,
        description_raw=product.get('description'),
        composition_raw='; '.join(lines) or None,
        composition_outer_raw=common.outer_composition(lines, warnings) if lines else None,
        care_raw='; '.join(c for c in care if c) or None,
        origin_raw=supplier.get('country'),
        supplier_factory=supplier.get('factory'))
    return common.finalize(fields, warnings, html, captured_at)
