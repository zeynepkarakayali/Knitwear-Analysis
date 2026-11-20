"""H&M US: paginated category links + product parser (validated on saved Oct 2026 US product HTML).
Product data comes from the page's __NEXT_DATA__ JSON, so no click is needed for composition or price.
"""
import json
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup
import common

BRAND = 'H&M'
HOST, STORE = 'www2.hm.com', '/en_us/'
CATEGORY = 'https://www2.hm.com/en_us/women/products/cardigans-sweaters.html'
CARD_JS = "a => a.pathname.includes('/productpage.') && !a.closest('header, nav, footer, dialog')"
GRID_READY = 'a[href*="/productpage."]'
PRODUCT_PATH = re.compile(r'/en_us/productpage\.(?P<article>(?P<model>\d{7})\d{3})\.html')
NAME = 'h1[data-testid="product-name"]'


def in_store(url):
    return common.in_store(url, HOST, STORE)


def page_url(category, n):
    """Category listing page n (H&M paginates with ?page=N instead of infinite scroll)."""
    p = urlparse(category)
    query = {k: v[0] for k, v in parse_qs(p.query).items()}
    query['page'] = str(n)
    return urlunparse(p._replace(query=urlencode(query)))


def clean_link(url):
    """(dedupe key, canonical URL) for a product link, else None. One colour per model."""
    p = urlparse(url)
    m = PRODUCT_PATH.fullmatch(p.path)
    if not in_store(url) or not m:
        return None
    return m['model'], urlunparse(('https', HOST, p.path, '', '', ''))


def dismiss_consent(page):
    """Choose 'Only required cookies' if the OneTrust settings are shown; never 'Accept all'."""
    for selector in ('#settings-only-required-btn', '#onetrust-reject-all-handler'):
        button = page.locator(selector)
        if button.count() and button.first.is_visible():
            button.first.click()
            return


def open_details(page):
    page.locator(NAME).wait_for(state='visible', timeout=20000)
    # Country of production loads only after opening "Supplier information" (unverified markup).
    try:
        dismiss_consent(page)
        page.get_by_role('button', name=re.compile(r'supplier information', re.I)).first.click(timeout=3000)
        page.get_by_text('Country of production', exact=False).first.wait_for(state='visible', timeout=8000)
    except Exception:
        pass


def number(value):
    try:
        return float(value) if value not in (None, '') else None
    except ValueError:
        return None


def production_country(soup):
    for label in soup.find_all(string=re.compile(r'^\s*Country of production\s*:?\s*$', re.I)):
        if label.find_parent('script'):
            continue
        value = label.find_next(string=lambda s: s.strip() and 'country of production' not in s.lower())
        if value:
            return value.strip()
    return None


def parse(html, url, captured_at=None):
    s = BeautifulSoup(html, 'html.parser')
    warnings = []
    m = PRODUCT_PATH.fullmatch(urlparse(url).path)
    data = s.select_one('#__NEXT_DATA__')
    try:
        props = json.loads(data.string)['props']['pageProps']['productPageProps']
        details = props['aemData']['productArticleDetails']
    except (AttributeError, KeyError, TypeError, ValueError):
        props, details = {}, {}
        warnings.append('missing_next_data')
    article = props.get('articleCode') or (m['article'] if m else None)
    if m and article and article != m['article']:
        warnings.append('url_model_mismatch')
    variant = details.get('variations', {}).get(article, {})

    red, white = number(variant.get('redPriceValue')), number(variant.get('whitePriceValue'))
    compositions = variant.get('compositions') or []
    attributes = {a.get('title'): a.get('values') for a in variant.get('productAttributes', {}).get('description', [])}
    weight = re.search(r'(\d+(?:\.\d+)?)\s*g\b', str(attributes.get('weight') or ''))
    crumbs = s.select_one('#breadcrumb-schema')
    try:
        names = [i['name'] for i in json.loads(crumbs.string)['itemListElement']]
        subcategory = common.norm(names[-2]) if len(names) >= 2 else None
    except (AttributeError, KeyError, TypeError, ValueError):
        subcategory = None

    fields = dict(
        brand=BRAND, product_ref=article, model_id=details.get('productId') or (m['model'] if m else None),
        color_id=article[-3:] if article else None,
        product_name=details.get('productName') or common.txt(s, NAME),
        subcategory=subcategory, product_url=url, country='US' if in_store(url) else None,
        currency=variant.get('priceCurrency'),
        price_current=red if red is not None else white, price_original=white if red is not None else None,
        color=variant.get('name'), description_raw=variant.get('description'),
        composition_raw='; '.join(compositions) or None,
        composition_outer_raw=common.outer_composition(compositions, warnings),
        care_raw='; '.join(variant.get('careInstructions') or []) or None,
        origin_raw=production_country(s),
        weight_g=float(weight[1]) if weight else None)
    return common.finalize(fields, warnings, html, captured_at)


def parse_variants(html, url, captured_at=None):
    """Every colour of the model from one page: __NEXT_DATA__ lists each colour (article) with its
    own price, composition and care. Supplier country is only shown for the open colour."""
    base = parse(html, url, captured_at)
    rows = [base]
    try:
        details = json.loads(BeautifulSoup(html, 'html.parser').select_one('#__NEXT_DATA__').string)
        details = details['props']['pageProps']['productPageProps']['aemData']['productArticleDetails']
    except (AttributeError, KeyError, TypeError, ValueError):
        return rows
    for article, v in details.get('variations', {}).items():
        if article == base['product_ref'] or not re.fullmatch(r'\d{10}', article):
            continue
        red, white = number(v.get('redPriceValue')), number(v.get('whitePriceValue'))
        compositions = v.get('compositions') or []
        warnings = []
        rows.append(common.variant_row(
            base, html, captured_at, product_ref=article, color_id=article[-3:],
            product_url=f'https://{HOST}/en_us/productpage.{article}.html',
            color=v.get('name'), currency=v.get('priceCurrency') or base['currency'],
            price_current=red if red is not None else white,
            price_original=white if red is not None else None,
            description_raw=v.get('description') or base['description_raw'],
            composition_raw='; '.join(compositions) or None,
            composition_outer_raw=common.outer_composition(compositions, warnings),
            care_raw='; '.join(v.get('careInstructions') or []) or None,
            origin_raw=None))  # not on the page for colours other than the open one
    return rows
