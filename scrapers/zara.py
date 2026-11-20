"""Zara US: category links + product page parser (selectors validated on FR HTML, US labels unverified)."""
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup
import common

BRAND = 'Zara'
HOST, STORE = 'www.zara.com', '/us/en/'
CATEGORY = 'https://www.zara.com/us/en/woman-knitwear-l1152.html?v1=2420306'
CARD_JS = "a => a.closest('.product-grid-product')"  # which <a> elements count as product cards
GRID_READY = '.product-grid-product'
PRODUCT_PATH = re.compile(r'/us/en/[^/]+-p\d+\.html')
NAME = '[data-qa-qualifier="product-detail-info-name"]'
BUTTON = 'button[data-qa-action="show-extra-detail"]'
MATERIALS = '[data-observer-key="materials"]'


def in_store(url):
    return common.in_store(url, HOST, STORE)


def clean_link(url):
    """(dedupe key, canonical URL) for a product link, else None. One colour per model path."""
    p = urlparse(url)
    if not in_store(url) or not PRODUCT_PATH.fullmatch(p.path):
        return None
    v1 = parse_qs(p.query).get('v1')
    return p.path, urlunparse(('https', HOST, p.path, '', urlencode({'v1': v1[0]}) if v1 else '', ''))


def dismiss_consent(page):
    reject = page.locator('#onetrust-reject-all-handler')
    if reject.is_visible():
        reject.click()


def open_details(page):
    page.locator(NAME).wait_for(state='visible', timeout=20000)
    button = page.locator(BUTTON)
    if button.count() == 1 and button.is_visible():
        button.click()
        page.locator('[role="dialog"] ' + MATERIALS).wait_for(state='visible', timeout=10000)


def parse(html, url, captured_at=None):
    s = BeautifulSoup(html, 'html.parser')
    warnings = []
    reference = common.txt(s, '[data-qa-action="product-detail-info-color-copy"]')
    ref = re.fullmatch(r'(\d{4})/(\d{3})/(\d{3})', reference or '')
    path_model = re.search(r'-p(\d+)\.html', urlparse(url).path)
    if ref and path_model and path_model[1] != '0' + ref[1] + ref[2]:
        warnings.append('url_model_mismatch')

    def price(selector):
        node = s.select_one(selector)
        try:
            return float(node['value']) if node else None
        except (ValueError, KeyError):
            warnings.append('invalid_price')
            return None

    current = s.select_one('.product-detail-info__price [data-qa-id="price-container-current"] data[value]')
    section = s.select_one(MATERIALS)
    outer = None
    if section:
        heads = [common.norm(h.get_text(' ', strip=True))
                 for h in section.select('.structured-component-text-block-subtitle')]
        parts = [h for h in heads if h != 'composition']
        if not parts or (len(parts) == 1 and parts[0] in common.OUTER_LABELS):
            outer = '; '.join(p.get_text(' ', strip=True)
                              for p in section.select('.structured-component-text-block-paragraph')) or None
        else:
            warnings.append('multiple_or_unknown_material_sections')
    else:
        nodes = s.select('.product-detail-composition__single-part-materials')
        if len(nodes) == 1:
            outer = nodes[0].get_text(' ', strip=True)

    fields = dict(
        brand=BRAND, product_ref=reference,
        model_id='/'.join(ref.groups()[:2]) if ref else None, color_id=ref[3] if ref else None,
        product_name=common.txt(s, NAME), product_url=url,
        country='US' if in_store(url) else None,
        currency=current.get('data-currency') if current else None,
        price_current=price('.product-detail-info__price [data-qa-id="price-container-current"] data[value]'),
        price_original=price('.product-detail-info__price .price-old data[value]'),  # untested fallback
        color=common.txt(s, '.product-color-extended-name__name'),
        description_raw=common.txt(s, '.product-detail-info__description .expandable-text__inner-content'),
        composition_raw=section.get_text(' ', strip=True) if section else common.txt(s, '.product-detail-composition'),
        composition_outer_raw=outer,
        care_raw=common.txt(s, '[data-observer-key="care"]'),
        origin_raw=common.txt(s, '[data-observer-key="traceability"]'),
        sustainability_raw=common.txt(s, '[data-observer-key="sustainableMaterials"]'))
    return common.finalize(fields, warnings, html, captured_at)
