"""SHEIN US: paginated category links + product parser (validated on saved Oct 2026 US product HTML).
Titles are keyword-stuffed ("...Sweater ... Cardigan Knit Top"), so the scope filter uses the
site's own "Type" attribute (e.g. Pullovers, Cardigans) instead of the title. Each colour is its own product
page; model_id (productGroupID) groups colours so process_products.py keeps one colour per model.
"""
import json
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup
import common

BRAND = 'SHEIN'
HOST, STORE = 'us.shein.com', '/'
CATEGORY = 'https://us.shein.com/Women-Sweaters-c-1734.html'
CARD_JS = "a => /-p-\\d+\\.html$/.test(a.pathname) && !a.closest('header, nav, footer, dialog')"
GRID_READY = 'a[href*="-p-"]'
PRODUCT_PATH = re.compile(r'/[^/]+-p-(?P<goods>\d+)\.html')
NAME = '.product-intro__head-name'


def in_store(url):
    return common.in_store(url, HOST, STORE)


def page_url(category, n):
    """Category listing page n; tracking parameters from a copied URL are dropped."""
    p = urlparse(category)
    return urlunparse(p._replace(query=urlencode({'page': n}), fragment=''))


def clean_link(url):
    """(dedupe key, canonical URL) for a product link, else None. Colours are separate goods ids."""
    p = urlparse(url)
    m = PRODUCT_PATH.fullmatch(p.path)
    if not in_store(url) or not m:
        return None
    return m['goods'], urlunparse(('https', HOST, p.path, '', '', ''))


def dismiss_consent(page):
    reject = page.locator('#onetrust-reject-all-handler')
    if reject.count() and reject.first.is_visible():
        reject.first.click()


def open_details(page):
    page.locator(NAME).first.wait_for(state='visible', timeout=20000)


def number(value):
    try:
        return float(value) if value not in (None, '') else None
    except ValueError:
        return None


def attributes(soup, html):
    """{'Composition': '100% Acrylic', 'Type': 'Pullovers', ...} from the Description list,
    falling back to the embedded productDetails JSON when the list is not rendered."""
    attrs = {}
    for li in soup.select('.product-intro__attr-list-textli'):
        name = li.select_one('.product-intro__attr-list-textname')
        value = li.select_one('.product-intro__attr-list-textval')
        if name and value:
            attrs.setdefault(name.get_text(' ', strip=True).rstrip(': '), value.get_text(' ', strip=True))
    if not attrs:
        for name, value in re.findall(r'"attr_name_en":"([^"]+)"[^{}]*?"attr_value_en":"([^"]*)"', html):
            attrs.setdefault(name, value)
    return attrs


def parse(html, url, captured_at=None):
    s = BeautifulSoup(html, 'html.parser')
    warnings = []
    m = PRODUCT_PATH.fullmatch(urlparse(url).path)
    goods_id = m['goods'] if m else None
    canonical = s.select_one('link[rel="canonical"]')
    canonical_id = PRODUCT_PATH.search(urlparse(canonical['href']).path) if canonical else None
    if goods_id and canonical_id and canonical_id['goods'] != goods_id:
        warnings.append('url_model_mismatch')

    group = {}
    for script in s.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or '')
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if item.get('@type') == 'ProductGroup':
                group = item
    offers = [v.get('offers', {}) for v in group.get('hasVariant', [])]
    current = number(offers[0].get('price')) if offers else None
    # List price sits in the main product's sku_list (the page also holds other colours' prices).
    block = re.search(r'"goods_id":"%s","sku_list":\[(.{0,6000})' % goods_id, html) if goods_id else None
    retail = re.search(r'"retailPrice":\{"amount":"([\d.]+)"', block[1]) if block else None
    if current is None and block:
        sale = re.search(r'"salePrice":\{"amount":"([\d.]+)"', block[1])
        current = number(sale[1]) if sale else None
    retail = number(retail[1]) if retail else None

    attrs = attributes(s, html)
    product_type = common.norm(attrs.get('Type', '')) or None
    name_node = s.select_one(NAME)
    name = name_node.get_text(' ', strip=True) if name_node else group.get('name')
    if product_type:
        category = common.classify(None, product_type)  # the stuffed title would mislead
    else:
        category = common.classify(name)
        warnings.append('type_attribute_missing')

    composition = attrs.get('Composition')
    fields = dict(
        brand=BRAND, product_ref=attrs.get('SKU'), model_id=group.get('productGroupID') or goods_id,
        color_id=goods_id, product_name=name, category=category, subcategory=product_type,
        product_url=url, country='US' if in_store(url) else None,
        currency=offers[0].get('priceCurrency') if offers else None,
        price_current=current,
        price_original=retail if retail and current and retail > current + 0.001 else None,
        color=attrs.get('Color') or group.get('color'),
        description_raw='; '.join(f'{k}: {v}' for k, v in attrs.items()
                                  if k not in ('Composition', 'Care Instructions', 'SKU')) or None,
        composition_raw=composition,
        composition_outer_raw=common.outer_composition([composition], warnings) if composition else None,
        care_raw=attrs.get('Care Instructions'))
    return common.finalize(fields, warnings, html, captured_at)
