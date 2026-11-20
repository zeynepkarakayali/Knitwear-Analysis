"""Massimo Dutti US: scrolling category links + product parser (validated on saved Oct 2026 US HTML).
Name, price and colour come from JSON-LD; composition, care and origin from the "FABRIC / CARE"
drawer, which open_details() opens (the saved test page was captured with it open).
"""
import json
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup
import common

BRAND = 'Massimo Dutti'
HOST, STORE = 'www.massimodutti.com', '/us/'
CATEGORY = 'https://www.massimodutti.com/us/women/jumpers-n1464'
CARD_JS = r"a => /^\/us\/[^/]+-l\d{8}$/.test(a.pathname) && !a.closest('header, nav, footer, dialog')"
GRID_READY = 'a[href*="-l0"], a[href*="-l1"]'
# /us/100-wool-knit-mock-neck-sweater-l05717596?pelement=63985019
PRODUCT_PATH = re.compile(r'/us/(?P<slug>[^/]+)-l(?P<model>\d{8})')
NAME = 'h1'
DRAWER_BUTTON = 'product-composition-drawer-wrapper button'
COMPOSITION = 'product-composition-list'


def in_store(url):
    return common.in_store(url, HOST, STORE)


def clean_link(url):
    """(dedupe key, canonical URL keeping the colour 'pelement') for a product link, else None."""
    p = urlparse(url)
    m = PRODUCT_PATH.fullmatch(p.path)
    if not in_store(url) or not m:
        return None
    colour = parse_qs(p.query).get('pelement')
    return m['model'], urlunparse(('https', HOST, p.path, '', urlencode({'pelement': colour[0]}) if colour else '', ''))


def dismiss_consent(page):
    reject = page.locator('#onetrust-reject-all-handler')
    if reject.count() and reject.first.is_visible():
        reject.first.click()


def open_details(page):
    """Open "FABRIC / CARE". The site is Angular: a click made before the app has started is
    silently lost (the drawer never fills), so wait for the page to load and retry the click."""
    page.locator(NAME).first.wait_for(state='visible', timeout=20000)
    if page.locator(COMPOSITION).count():
        return
    try:
        page.wait_for_load_state('load', timeout=15000)
    except Exception:
        pass
    button = page.locator(DRAWER_BUTTON)
    if not button.count():
        button = page.get_by_role('button', name=re.compile(r'fabric|composition', re.I))
    if not button.count():
        return  # parse() records what is missing
    dismiss_consent(page)
    for attempt in range(4):
        try:
            if attempt:
                page.keyboard.press('Escape')  # close a half-open drawer before trying again
                page.wait_for_timeout(1500)
            button.first.scroll_into_view_if_needed(timeout=5000)
            button.first.click(timeout=5000)
            page.locator(COMPOSITION).first.wait_for(state='attached', timeout=5000)
            break
        except Exception:
            continue
    try:
        page.locator('product-made-in').first.wait_for(state='attached', timeout=3000)
    except Exception:
        pass


def composition_parts(soup):
    """['Outer layer: Wool 100%', 'Lining: ...'] from the drawer's composition list."""
    root = soup.select_one(COMPOSITION)
    if not root:
        return []
    # One part per heading (OUTER LAYER, LINING, ...): its fibres are separate <span>s.
    groups, label = {}, None
    for node in root.find_all(['h4', 'span']):
        text = ' '.join(node.get_text(' ', strip=True).split()).strip(' ,')
        if node.name == 'h4':
            label = text.capitalize()
        elif '%' in text:
            groups.setdefault(label, []).append(text)
    return [f'{label}: {", ".join(fibres)}' if label else ', '.join(fibres) for label, fibres in groups.items()]


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
    pelement = parse_qs(urlparse(url).query).get('pelement', [None])[0]
    variants = group.get('hasVariant', [])
    variant = next((v for v in variants if v.get('sku') == pelement), variants[0] if variants else {})
    offer = variant.get('offers') or {}
    try:
        current = float(offer['price']) if offer.get('price') is not None else None
    except (TypeError, ValueError):
        current = None
        warnings.append('invalid_price')
    # A crossed-out price would be a second, higher amount in the heading price block (untested).
    block = s.select_one('.md-product-heading-prices')
    shown = [float(x.replace(',', '')) for x in re.findall(r'\$([\d,]+(?:\.\d{2})?)', block.get_text())] if block else []
    higher = [v for v in shown if current and v > current + 0.001]

    ref = re.search(r'Ref\.\s*(\d{4})/(\d{3})', s.select_one('.md-pdp5-box--info-sku').get_text()
                    if s.select_one('.md-pdp5-box--info-sku') else '')
    if m and ref and m['model'] != '0' + ref[1] + ref[2]:
        warnings.append('url_model_mismatch')

    title = s.title.get_text() if s.title else ''
    title_parts = [x.strip() for x in title.split('|')[0].split('·')]  # name · colour · Sweaters
    subcategory = common.norm(title_parts[-1]) if len(title_parts) >= 3 else None
    heading = s.select_one(NAME)
    name = group.get('name') or (heading.get_text(' ', strip=True) if heading else None)

    parts = composition_parts(s)
    care = [l.get_text(' ', strip=True) for l in s.select('care-instructions label')]
    made_in = s.find(lambda t: t.name == 'p' and t.get_text(strip=True).startswith('Made in'))
    certified = [p.get_text(' ', strip=True) for p in s.select('certified-materials > div > div > p')]

    fields = dict(
        brand=BRAND, product_ref='/'.join(ref.groups()) if ref else None,
        model_id='/'.join(ref.groups()) if ref else (m['model'] if m else None),
        color_id=variant.get('sku') or pelement,
        product_name=name[:1].upper() + name[1:] if name else None, subcategory=subcategory,
        product_url=url, country='US' if in_store(url) else None,
        currency=offer.get('priceCurrency'), price_current=current,
        price_original=max(higher) if higher else None,
        color=variant.get('color'), description_raw=common.txt(s, 'pdp-product-info'),
        composition_raw='; '.join(parts) or None,
        composition_outer_raw=common.outer_composition(parts, warnings) if parts else None,
        care_raw='; '.join(c.capitalize() for c in care) or None,
        origin_raw=made_in.get_text(strip=True).replace('Made in', '').strip() if made_in else None,
        sustainability_raw='; '.join(c for c in certified if c) or None)
    return common.finalize(fields, warnings, html, captured_at)


def parse_variants(html, url, captured_at=None):
    """Every colour from one page. All colours share the reference (model/quality), so the
    composition, care and origin of the open colour apply to them; price comes from JSON-LD.
    Colour ids (pelement) come from the colour buttons, because JSON-LD repeats one sku."""
    base = parse(html, url, captured_at)
    rows, s = [base], BeautifulSoup(html, 'html.parser')
    ids = {}
    for button in s.select('.md-color-selector-btn[id^="color-btn-pdp-"]'):
        name = (button.get('title') or '').split(', Ref.')[0].strip().lower()
        ids[name] = button['id'].removeprefix('color-btn-pdp-')
    seen = {(base['color'] or '').lower()}
    for script in s.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or '')
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not (isinstance(item, dict) and item.get('@type') == 'ProductGroup'):
                continue
            for v in item.get('hasVariant', []):
                colour = (v.get('color') or '').strip()
                pelement = ids.get(colour.lower())
                if not pelement or colour.lower() in seen or pelement == base['color_id']:
                    continue
                seen.add(colour.lower())
                offer = v.get('offers') or {}
                try:
                    price = float(offer.get('price'))
                except (TypeError, ValueError):
                    price = None
                path = urlparse(base['product_url']).path
                rows.append(common.variant_row(
                    base, html, captured_at, color_id=pelement, color=colour.capitalize(),
                    product_url=f'https://{HOST}{path}?pelement={pelement}',
                    currency=offer.get('priceCurrency') or base['currency'],
                    price_current=price, price_original=None))
    return rows
