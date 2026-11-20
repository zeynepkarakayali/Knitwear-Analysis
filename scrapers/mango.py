"""Mango US: category links + product page parser (validated on saved Oct 2026 US product HTML)."""
import re
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup
import common

BRAND = 'Mango'
HOST, STORE = 'shop.mango.com', '/us/en/'
CATEGORY = 'https://shop.mango.com/us/en/c/women/sweaters-and-cardigans/f9a8c868'
CARD_JS = "a => a.pathname.includes('/p/') && !a.closest('header, nav, footer, dialog')"
GRID_READY = 'a[href*="/us/en/p/"]'
# /us/en/p/women/sweaters-and-cardigans/sweaters/argyle-knit-sweater/37017779/56/00
PRODUCT_PATH = re.compile(r'/us/en/p/(?P<cats>(?:[^/]+/)+)(?P<slug>[^/]+)/(?P<model>\d{6,10})/(?P<color>\d{1,3})(?:/\d+)?/?')
NAME = 'h1[class*="ProductDetail-module__"]'
DETAILS_BUTTON = 'button[class*="ProductDetailsLink-module__"]'
COMPOSITION_ITEMS = '[id="composition.panel"] [class*="Composition-module__"] li'

_consent_done = False


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
    """Refuse non-essential cookies (via 'Set cookies'); never clicks 'Accept all'."""
    global _consent_done
    banner = page.locator('#cookies-banner')
    if not _consent_done:
        try:
            banner.wait_for(state='visible', timeout=4000)
        except Exception:
            pass
    if banner.is_visible():
        try:
            banner.get_by_role('button', name=re.compile(r'set cookies', re.I)).click(timeout=3000)
            for label in (r'reject all', r'reject', r'decline', r'save|confirm'):
                button = page.locator('dialog[open]').get_by_role('button', name=re.compile(label, re.I))
                if button.count() and button.first.is_visible():
                    button.first.click()
                    break
        except Exception:
            pass
        if banner.is_visible():
            page.keyboard.press('Escape')
        if banner.is_visible():
            print('Cookie banner still open: refuse cookies manually in the browser (waiting 60 s).', flush=True)
            banner.wait_for(state='hidden', timeout=60000)
    _consent_done = any(c['name'] == 'consentCookie' for c in page.context.cookies())


def open_details(page):
    page.locator(NAME).wait_for(state='visible', timeout=20000)
    items = page.locator(COMPOSITION_ITEMS)
    if items.count() == 0:
        dismiss_consent(page)  # a late banner would block the click
        page.locator(DETAILS_BUTTON).first.click()
        items.first.wait_for(state='attached', timeout=10000)


def parse(html, url, captured_at=None):
    s = BeautifulSoup(html, 'html.parser')
    warnings = []
    m = PRODUCT_PATH.fullmatch(urlparse(url).path)

    title = s.select_one(NAME)
    block = title.parent if title else s  # name, price and tags share this container

    def number(value):
        try:
            return float(re.sub(r'[^\d.]', '', value)) if value else None
        except ValueError:
            warnings.append('invalid_price')
            return None

    price_meta = block.select_one('meta[itemprop="price"]')
    currency_meta = block.select_one('meta[itemprop="priceCurrency"]')
    current = number(price_meta.get('content') if price_meta else None)
    # Screen-reader labels look like "Current price [US$ 69.99 ]"; a higher bracketed
    # value in the same block is taken as the crossed-out price (untested: no sale example).
    shown = [number(v) for t in block.select('[class*="srOnly-module"]')
             for v in re.findall(r'\[([^\]]+)\]', t.get_text())]
    higher = [v for v in shown if v and current and v > current + 0.001]

    mpn = s.select_one('meta[itemprop="mpn"]')
    ref_text = common.txt(s, '[class*="Header-module__"][class*="__subtitle"]')  # "REF. 37017779"
    ref = re.search(r'\d{6,10}', ref_text or '')
    model_id = (mpn.get('content') if mpn else None) or (ref[0] if ref else None)
    if m and model_id and model_id != m['model']:
        warnings.append('url_model_mismatch')

    panel = s.select_one('[id="composition.panel"]')
    sections = {}
    if panel:
        for heading in panel.select('h2'):
            sections[common.norm(heading.get_text(strip=True))] = list(heading.parent.stripped_strings)[1:]
    items = [li.get_text(' ', strip=True) for li in s.select(COMPOSITION_ITEMS)]
    colour = s.select('[class*="ColorsSelector-module__"][class*="__title"] span')
    description = s.select_one('meta[name="description"]')

    fields = dict(
        brand=BRAND, product_ref=ref[0] if ref else None, model_id=model_id,
        color_id=m['color'] if m else None,
        product_name=title.get_text(' ', strip=True) if title else None,
        subcategory=m['cats'].rstrip('/').split('/')[-1] if m else None,
        product_url=url, country='US' if in_store(url) else None,
        currency=currency_meta.get('content') if currency_meta else None,
        price_current=current, price_original=max(higher) if higher else None,
        color=colour[-1].get_text(strip=True) if colour else None,
        description_raw=description.get('content') if description else None,
        composition_raw='; '.join(items) or None,
        composition_outer_raw=common.outer_composition(items, warnings),
        care_raw='; '.join(sections.get('care', [])) or None,
        origin_raw='; '.join(sections.get('origin', [])) or None)
    return common.finalize(fields, warnings, html, captured_at)
