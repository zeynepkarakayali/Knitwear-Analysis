"""UNIQLO US: scrolling category links + product parser (validated on saved Oct 2026 US product HTML).
Price and product group come from JSON-LD; fabric and care from the "Fabric details" section.
"""
import json
import re
from urllib.parse import urlparse, parse_qs, urlunparse
from bs4 import BeautifulSoup
import common

BRAND = 'UNIQLO'
HOST, STORE = 'www.uniqlo.com', '/us/en/'
CATEGORY = 'https://www.uniqlo.com/us/en/women/sweaters'
CARD_JS = r"a => /^\/us\/en\/products\/E\d+-\d{3}\/\d{2}$/.test(a.pathname) && !a.closest('header, nav, footer, dialog')"
GRID_READY = 'a[href*="/us/en/products/"]'
# /us/en/products/E465734-000/00
PRODUCT_PATH = re.compile(r'/us/en/products/(?P<model>E\d+-\d{3})/(?P<version>\d{2})')
NAME = 'h1'
MATERIALS = '[id="productMaterialDescription-content"]'
PART_SPLIT = re.compile(r'\s*/\s*(?=[A-Za-z][A-Za-z -]*:)')  # "Body: 100% Cotton/ Binder-processed Part: ..."


def in_store(url):
    return common.in_store(url, HOST, STORE)


def clean_link(url):
    """(dedupe key, canonical URL) for a product link, else None. One colour per model."""
    p = urlparse(url)
    m = PRODUCT_PATH.fullmatch(p.path)
    if not in_store(url) or not m:
        return None
    return m['model'], urlunparse(('https', HOST, p.path, '', '', ''))


def dismiss_consent(page):
    reject = page.locator('#onetrust-reject-all-handler')
    if reject.count() and reject.first.is_visible():
        reject.first.click()


def open_details(page):
    page.locator(NAME).first.wait_for(state='visible', timeout=20000)
    page.locator(MATERIALS).first.wait_for(state='attached', timeout=10000)


def sections(soup):
    """{'fabric details': ['100% Cashmere', 'Imported'], 'washing instructions': [...]}"""
    result = {}
    root = soup.select_one(MATERIALS)
    if not root:
        return result
    for block in root.select('[data-testid="ITOContentAlignment"]'):
        children = [c for c in block.children if getattr(c, 'name', None)]
        if not children:
            continue
        lines = [line.strip() for c in children[1:] for line in c.get_text('\n').split('\n') if line.strip()]
        result[common.norm(children[0].get_text(' ', strip=True))] = lines
    return result


def select_composition(lines, product_ids, colour_code):
    """The fibre text that applies to one colour of one product, from Uniqlo's fabric lines:
    - "482321, 490525: 70% Acrylic, 30% Cotton"  -> the line for this product id
    - "[19 WINE, 50 LIGHT GREEN] 58% ... [Other Colors] 57% ..."  -> the segment for this colour
    - plain "39% Cotton, 34% Polyester, 27% Rayon ( 34% Uses Recycled ... )"  -> as is"""
    lines = [l for l in lines if '%' in l]
    if not lines:
        return None
    by_id = [(re.findall(r'\d+', m[1]), m[2]) for m in (re.match(r'^([\d,\s]+):\s*(.+)$', l) for l in lines) if m]
    text = next((t for ids, t in by_id if set(ids) & product_ids), None) or (by_id[0][1] if by_id else lines[0])
    segments = re.findall(r'\[([^\]]+)\]\s*([^\[]+)', text)
    if segments:
        default = None
        for colours, fibres in segments:
            codes = {c.strip().split(' ')[0] for c in colours.split(',')}
            if colour_code and colour_code in codes:
                return fibres.strip(' ;')
            if 'other' in colours.lower():
                default = fibres.strip(' ;')
        return default or segments[0][1].strip(' ;')
    return text


def outer_fibres(text, warnings):
    """Main-fabric fibres from one colour's text: picks Body/Shell when there are several parts and
    drops a nested label (e.g. "Body: Face: 100% Polyester / Back: ..." -> "100% Polyester")."""
    if not text:
        return None
    parts = [p for p in PART_SPLIT.split(text) if p.strip()]
    outer = common.outer_composition(parts, warnings) if len(parts) > 1 else re.sub(r'^\s*(?:body|shell)\s*:\s*', '', text, flags=re.I)
    return re.sub(r'^\s*[A-Za-z][A-Za-z -]*:\s*', '', outer) if outer else None


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
        for item in data.get('@graph', [data]) if isinstance(data, dict) else data:
            if isinstance(item, dict) and item.get('@type') == 'ProductGroup':
                group = item
    model_id = group.get('productGroupID') or (m['model'] if m else None)
    if m and group.get('productGroupID') and group['productGroupID'] != m['model']:
        warnings.append('url_model_mismatch')

    title = s.select_one(NAME)
    info = title.find_parent(class_='fr-ec-layout') if title else None
    colour_text = info.find(string=re.compile(r'^\s*Color:')) if info else None
    colour = re.match(r'\s*Color:\s*(\d+)?\s*(.*)', colour_text) if colour_text else None
    colour_code = colour[1] if colour else parse_qs(urlparse(url).query).get('colorDisplayCode', [None])[0]

    offers = [v.get('offers', {}) for v in group.get('hasVariant', [])]
    chosen = [o for o in offers if colour_code and f'colorDisplayCode={colour_code}' in o.get('url', '')] or offers
    try:
        current = float(chosen[0]['price']) if chosen else None
    except (KeyError, ValueError):
        current = None
        warnings.append('invalid_price')
    # A sale shows the main price in the promotional colour; the original price is often not shown.
    prices = info.select('p[class*="fr-ec-price-text"]') if info else []
    on_sale = any('color-promotional' in ' '.join(p.get('class', [])) for p in prices)
    shown = [float(x) for p in prices for x in re.findall(r'\$([\d,]+\.\d{2})', p.get_text().replace(',', ''))]
    currency = chosen[0].get('priceCurrency') if chosen else None
    if current is None and shown:  # JSON-LD without offers: the first price in the product block
        current, currency = shown[0], 'USD'
        warnings[:] = [w for w in warnings if w != 'invalid_price']
    higher = [v for v in shown if current and v > current + 0.001]

    info_sections = sections(s)
    fabric = info_sections.get('fabric details', [])
    product_id = s.find(lambda t: t.name == 'p' and t.get_text(strip=True).startswith('Product ID:'))
    product_ids = set(re.findall(r'\d+', product_id.get_text())) if product_id else set()
    product_id = re.search(r'\d+', product_id.get_text()) if product_id else None
    selected = select_composition(fabric, product_ids, colour_code)
    breadcrumb = (group.get('category') or '').split(' / ')

    fields = dict(
        brand=BRAND, product_ref=product_id[0] if product_id else None,
        model_id=model_id, color_id=colour_code,
        product_name=title.get_text(' ', strip=True) if title else group.get('name'),
        subcategory=common.norm(breadcrumb[2]) if len(breadcrumb) > 2 else None,
        product_url=url, country='US' if in_store(url) else None,
        currency=currency,
        price_current=current, price_original=max(higher) if higher else None,
        color=colour[2].strip().title() if colour else None,
        description_raw=group.get('description'),
        composition_raw='; '.join(fabric) or group.get('material'),
        composition_outer_raw=outer_fibres(selected, warnings),
        care_raw='; '.join(info_sections.get('washing instructions', [])) or None,
        origin_raw='; '.join(l for l in fabric if '%' not in l and not l.startswith('RN')
                             and (l.lower() == 'imported' or l.lower().startswith('made in'))) or None,
        sustainability_raw='; '.join(dict.fromkeys(re.findall(r'\(\s*([^)]*recycled[^)]*?)\s*\)', selected or '', re.I))) or None,
        on_sale=on_sale)
    return common.finalize(fields, warnings, html, captured_at)


def parse_variants(html, url, captured_at=None):
    """Every colour from one page: JSON-LD lists each colour (colorDisplayCode) with its price.
    Fabric details are per product, so they are shared by all colours."""
    base = parse(html, url, captured_at)
    rows, s = [base], BeautifulSoup(html, 'html.parser')
    colours = {}
    for script in s.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or '')
        except ValueError:
            continue
        for item in data.get('@graph', [data]) if isinstance(data, dict) else data:
            if isinstance(item, dict) and item.get('@type') == 'ProductGroup':
                for v in item.get('hasVariant', []):
                    offer = v.get('offers') or {}
                    code = parse_qs(urlparse(offer.get('url', '')).query).get('colorDisplayCode', [None])[0]
                    if code and code != base['color_id'] and code not in colours:
                        colours[code] = (v.get('color'), offer)
    path = urlparse(base['product_url']).path
    fabric = sections(s).get('fabric details', [])
    product_ids = {base['product_ref']} if base.get('product_ref') else set()
    node = s.find(lambda t: t.name == 'p' and t.get_text(strip=True).startswith('Product ID:'))
    if node:
        product_ids |= set(re.findall(r'\d+', node.get_text()))
    price_source = 'json_ld'
    if not colours:
        # Some pages ship JSON-LD without the colour list; the colour chips name every colour
        # (goods_<colour>_<product>_chip.jpg). Their price is not on the page, so the open
        # colour's price is used and flagged in price_source.
        price_source = 'open_colour'
        for img in s.select('img[src*="/chip/"]'):
            m = re.search(r'goods_(\d+)_(\d+)_chip', img.get('src', ''))
            if m and m[2] in product_ids and m[1] != base['color_id'] and m[1] not in colours:
                colours[m[1]] = (img.get('alt'), {'price': base['price_current'], 'priceCurrency': base['currency']})
    for code, (colour, offer) in colours.items():
        selected = select_composition(fabric, product_ids, code)  # some products differ by colour
        try:
            price = float(offer.get('price'))
        except (TypeError, ValueError):
            price = None
        rows.append(common.variant_row(
            base, html, captured_at, color_id=code, color=(colour or '').title() or None,
            product_url=f'https://{HOST}{path}?colorDisplayCode={code}',
            currency=offer.get('priceCurrency') or base['currency'], price_current=price,
            price_original=None, on_sale=None,  # the sale flag is only shown for the open colour
            composition_outer_raw=outer_fibres(selected, []) if selected else base['composition_outer_raw'],
            price_source=price_source))
    return rows
