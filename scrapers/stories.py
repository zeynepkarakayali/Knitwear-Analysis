"""& Other Stories US: paginated category links + product parser (validated on saved Oct 2026 US HTML).
Price, colour and composition come from the page itself (JSON-LD "Main material" and the
Material section), so no click is needed for them. Supplier country, if shown, loads in the
"Material" drawer, which open_details() opens (that part is unverified).
"""
import json
import re
from urllib.parse import urlparse, urlencode, urlunparse
from bs4 import BeautifulSoup
import common

BRAND = '& Other Stories'
HOST, STORE = 'www.stories.com', '/en-us/'
CATEGORY = 'https://www.stories.com/en-us/clothing/knitwear/'
CARD_JS = r"a => /^\/en-us\/product\/[^/]+-\d{10}\/?$/.test(a.pathname) && !a.closest('header, nav, footer, dialog')"
GRID_READY = 'a[href*="/en-us/product/"]'
# /en-us/product/mohair-blend-jumper-pink-1355590002/
PRODUCT_PATH = re.compile(r'/en-us/product/(?P<slug>[^/]+)-(?P<article>(?P<model>\d{7})(?P<color>\d{3}))/?')
NAME = 'h1'
MATERIAL_BUTTON = '[data-testid="product-info-material-and-supplier"]'


def in_store(url):
    return common.in_store(url, HOST, STORE)


def page_url(category, n):
    """Category listing page n (same platform as COS, which pages with ?page=N)."""
    p = urlparse(category)
    return urlunparse(p._replace(query=urlencode({'page': n}), fragment=''))


def clean_link(url):
    """(dedupe key, canonical URL) for a product link, else None. One colour per model."""
    p = urlparse(url)
    m = PRODUCT_PATH.fullmatch(p.path)
    if not in_store(url) or not m:
        return None
    return m['model'], urlunparse(('https', HOST, p.path if p.path.endswith('/') else p.path + '/', '', '', ''))


def dismiss_consent(page):
    reject = page.locator('#onetrust-reject-all-handler')
    if reject.count() and reject.first.is_visible():
        reject.first.click()


def open_details(page):
    """Composition is already in the page; open the Material drawer only for supplier info."""
    page.locator(NAME).first.wait_for(state='visible', timeout=20000)
    button = page.locator(MATERIAL_BUTTON)
    if button.count():
        try:
            dismiss_consent(page)
            button.first.click(timeout=3000)
            page.get_by_text(re.compile(r'^\s*Country\s*$')).first.wait_for(state='attached', timeout=5000)
        except Exception:
            pass  # origin_raw stays empty


def section(soup, heading):
    """Paragraph texts under an <h3> such as 'Composition'."""
    h3 = soup.find('h3', string=re.compile(rf'^\s*{heading}\s*$', re.I))
    box = h3.find_next_sibling() if h3 else None
    return [p.get_text(' ', strip=True) for p in box.find_all('p')] if box else []


def labelled_value(soup, label):
    """Text right after a short label element (e.g. 'Country' -> 'Mainland China')."""
    for node in soup.find_all(string=re.compile(rf'^\s*{label}\s*:?\s*$', re.I)):
        if node.find_parent(['script', 'style']):
            continue
        value = node.find_next(string=lambda t: t.strip() and not re.match(rf'^\s*{label}', t, re.I))
        if value:
            return value.strip()
    return None


def parse(html, url, captured_at=None):
    s = BeautifulSoup(html, 'html.parser')
    warnings = []
    m = PRODUCT_PATH.fullmatch(urlparse(url).path)

    group = {}
    for script in s.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or '')
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get('@type') == 'ProductGroup':
                group = item
    article = m['article'] if m else None
    variants = group.get('hasVariant', [])
    variant = next((v for v in variants if v.get('sku') == article), variants[0] if variants else {})
    if m and group.get('productGroupID') and group['productGroupID'] != m['model']:
        warnings.append('url_model_mismatch')
    offer = variant.get('offers') or {}
    try:
        current = float(offer['price']) if offer.get('price') is not None else None
    except (TypeError, ValueError):
        current = None
        warnings.append('invalid_price')
    block = s.select_one('[data-testid="product-price"]')
    shown = [float(x.replace(',', '')) for x in re.findall(r'\$\s*([\d,]+(?:\.\d{2})?)', block.get_text())] if block else []
    higher = [v for v in shown if current and v > current + 0.001]  # crossed-out price (untested)

    properties = {p.get('name'): p.get('value') for p in group.get('additionalProperty', [])}
    parts = section(s, 'Composition') or ([properties['Main material']] if properties.get('Main material') else [])
    heading = s.select_one(NAME)
    description = BeautifulSoup(group.get('description') or '', 'html.parser').get_text(' ', strip=True)

    fields = dict(
        brand=BRAND, product_ref=variant.get('sku') or article,
        model_id=group.get('productGroupID') or (m['model'] if m else None),
        color_id=(variant.get('sku') or article or '')[7:] or None,
        product_name=group.get('name') or (heading.get_text(' ', strip=True) if heading else None),
        product_url=url, country='US' if in_store(url) else None,
        currency=offer.get('priceCurrency'), price_current=current,
        price_original=max(higher) if higher else None,
        color=variant.get('color'), description_raw=description or None,
        composition_raw='; '.join(parts) or None,
        composition_outer_raw=common.outer_composition(parts, warnings) if parts else None,
        care_raw='; '.join(section(s, 'Care instructions') or section(s, 'Care')) or None,
        origin_raw=labelled_value(s, 'Country'),
        sustainability_raw='; '.join(section(s, 'Additional material information')) or None,
        fit=properties.get('fit'))
    return common.finalize(fields, warnings, html, captured_at)


def parse_variants(html, url, captured_at=None):
    """Every colour from one page: JSON-LD lists each colour (own article number and price).
    The material section is per product, so composition is shared by all colours."""
    base = parse(html, url, captured_at)
    rows = [base]
    for script in BeautifulSoup(html, 'html.parser').select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or '')
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not (isinstance(item, dict) and item.get('@type') == 'ProductGroup'):
                continue
            for v in item.get('hasVariant', []):
                sku, offer = v.get('sku') or '', v.get('offers') or {}
                link = clean_link(offer.get('url', ''))
                if not re.fullmatch(r'\d{10}', sku) or sku == base['product_ref'] or not link:
                    continue
                try:
                    price = float(offer.get('price'))
                except (TypeError, ValueError):
                    price = None
                rows.append(common.variant_row(
                    base, html, captured_at, product_ref=sku, color_id=sku[7:], color=v.get('color'),
                    product_url=link[1], currency=offer.get('priceCurrency') or base['currency'],
                    price_current=price, price_original=None,
                    origin_raw=None))  # supplier info is only loaded for the open colour
    return rows
