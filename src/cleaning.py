"""Cleaning: from the three merged tables (models, variants, fibres) to the clean model table
(data/clean/models_clean.csv) and a clean colour table (data/clean/variants_clean.csv).

This is the cleaning of notebook 01 (section 5) as functions, so notebooks, figures, robustness checks
and the dashboard all read one and the same table. Steps:
1. Scope: knit tops / T-shirts / shirts are removed; capes and ponchos are kept and flagged (`is_cape`).
2. Price outliers: log-IQR rule inside each brand (flag only, nothing removed).
3. Composition: fibres.csv (scraper-parsed) with 'other' split into yak/camel (other_animal), acetate,
   polybutylene terephthalate (polyester) and metallised/unknown (other); unparsed variants are re-parsed
   from the main-fabric text. Model composition = mean over its colours.
4. Price: model price = median current price; regular price undoes the sale where the original is known.
5. Care, origin and sustainability claims (claims only where the brand shows them).
"""
import re

import numpy as np
import pandas as pd

from .config import CLAIM_SOURCE, FIBRE_GROUPS, FIBRES, NAMED_FIBRES, PCT, SEGMENT
from .paths import MERGED


# ------------------------------------------------------------------ loading
def load_merged(folder=MERGED):
    """Read models.csv, variants.csv and fibres.csv (written by merge_products.py)."""
    read = lambda name: pd.read_csv(folder / name, encoding="utf-8-sig", low_memory=False)
    return read("models.csv"), read("variants.csv"), read("fibres.csv")


# ------------------------------------------------------------------ 1-2. scope, outliers
def scope_flags(models_raw):
    """Boolean Series: out-of-scope knit tops, and capes / ponchos (kept but flagged)."""
    name = models_raw["product_name"].fillna("").str.lower()
    knit_top = name.str.contains(r"\b(?:top|t-shirt|shirt)\b") & ~name.str.contains(r"sweater|jumper|cardigan")
    cape = name.str.contains(r"\bcape|poncho")
    return knit_top, cape


def select_scope(models_raw, variants_raw, fibres_raw):
    knit_top, cape = scope_flags(models_raw)
    models = models_raw.loc[~knit_top].copy()
    models["is_cape"] = cape.loc[models.index]
    models["segment"] = models["brand"].map(SEGMENT)
    variants = variants_raw[variants_raw["model_key"].isin(models["model_key"])].copy()
    fibres = fibres_raw[fibres_raw["variant_key"].isin(variants["variant_key"])].copy()
    return models, variants, fibres


def flag_price_outliers(models):
    """Within-brand price outliers: IQR rule on log10 price (flag only)."""
    logp = np.log10(models["price_median"])
    q1 = logp.groupby(models["brand"]).transform(lambda s: s.quantile(.25))
    q3 = logp.groupby(models["brand"]).transform(lambda s: s.quantile(.75))
    return (logp < q1 - 1.5 * (q3 - q1)) | (logp > q3 + 1.5 * (q3 - q1))


# ------------------------------------------------------------------ 3. composition
FIBER_MAP = [  # (regex, column) - checked in this order
    (r"yak|camel|angora|vicu", "other_animal_pct"),
    (r"cashmere", "cashmere_pct"), (r"mohair", "mohair_pct"), (r"alpaca", "alpaca_pct"),
    (r"wool|merino|lambswool", "wool_pct"), (r"silk", "silk_pct"),
    (r"cotton", "cotton_pct"), (r"linen|flax", "linen_pct"),
    (r"lyocell|tencel", "lyocell_pct"), (r"modal", "modal_pct"), (r"viscose|rayon", "viscose_pct"), (r"acetate", "acetate_pct"),
    (r"polyamide|nylon", "polyamide_pct"), (r"acrylic", "acrylic_pct"), (r"elastane|spandex", "elastane_pct"),
    (r"polyester|polybutylene terephthalate", "polyester_pct"),
    (r"metallised|metallized|metallic|other fib", "other_pct"),
]
assert [c for _, c in FIBER_MAP] == PCT


def fiber_col(fname):
    fname = str(fname).lower()
    for pat, col in FIBER_MAP:
        if re.search(pat, fname):
            return col
    return None


SECTION_STOP = r"\b(?:SECONDARY FABRIC|LINING|EMBELLISHMENT|DETAILS|OTHERS|TRIM|Binder-processed Part|Back:|Rib:|Woven part:)"


def main_fabric_text(raw_text):
    """Keep only the main / outer fabric part of a composition string."""
    t = str(raw_text)
    t = re.sub(r"^COMPOSITION\s+", "", t)
    t = re.sub(r"^(?:OUTER SHELL|Outer layer:|Shell:|Composition:|Body:|Knitted part:)\s*", "", t, flags=re.I)
    t = re.sub(r"^(?:MAIN FABRIC|BODY|Face:)\s*", "", t, flags=re.I)
    t = re.split(SECTION_STOP, t)[0]
    t = re.split(r"\[Other Colors\]", t)[0]
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"\(\s*\d+%\s*Uses Recycled[^)]*\)", " ", t, flags=re.I)
    t = re.sub(r"\(mulberry\)|\(recycled nylon\)", " ", t, flags=re.I)
    t = re.split(r";\s*Imported|;\s*RN:|/\s*Exclusive of Decoration|Excluding trims", t)[0]
    t = re.split(r"/", t)[0]
    t = re.sub(r"<\s*0[.,]5\s*%\s*[a-z ]+", " ", t, flags=re.I)  # trace fibres
    return t.strip()


PAIR = re.compile(r"(\d+(?:[.,]\d+)?)\s*%\s*([A-Za-z][A-Za-z \-]*)|([A-Za-z][A-Za-z \-]*?)\s+(\d+(?:[.,]\d+)?)\s*%")


def parse_composition(raw_text):
    """{fibre column: pct} for the main fabric, or None (unknown fibre name, or sum outside 99-101)."""
    if pd.isna(raw_text):
        return None
    out = {}
    for m in PAIR.finditer(main_fabric_text(raw_text)):
        if m.group(1):
            pct, fname = float(m.group(1).replace(",", ".")), m.group(2)
        else:
            pct, fname = float(m.group(4).replace(",", ".")), m.group(3)
        col = fiber_col(fname)
        if col is None:          # unknown fibre name -> reject the whole string
            return None
        out[col] = out.get(col, 0) + pct
    if not out or not (99 <= sum(out.values()) <= 101):
        return None
    return out


# fibres.csv 'other' -> column, by its fibre names
OTHER_NAMES = [(r"yak|camel|angora|vicu", "other_animal_pct"), (r"acetate", "acetate_pct"),
               (r"polybutylene", "polyester_pct"), (r".", "other_pct")]


def fibre_column(fibre, names):
    if fibre != "other":
        return f"{fibre}_pct"
    return next(col for pat, col in OTHER_NAMES if re.search(pat, str(names).lower()))


def variant_compositions(variants, fibres):
    """One row per variant with a usable composition (columns PCT) + Series comp_status for every variant."""
    fibres = fibres.assign(column=[fibre_column(f, n) for f, n in zip(fibres["fibre"], fibres["fibre_names"])])
    scraper_fib = fibres.pivot_table(index="variant_key", columns="column", values="pct", aggfunc="sum") \
                        .reindex(columns=PCT).fillna(0)
    todo = variants.loc[~variants["variant_key"].isin(scraper_fib.index)]
    reparsed = todo["composition_outer_raw"].fillna(todo["composition_raw"]).map(parse_composition)
    rec = pd.DataFrame([r for r in reparsed.dropna()], index=todo.loc[reparsed.notna(), "variant_key"]) \
            .reindex(columns=PCT).fillna(0)
    var_fib = pd.concat([scraper_fib, rec])
    status = pd.Series("missing", index=variants["variant_key"].values)
    status[status.index.isin(scraper_fib.index)] = "scraper"
    status[status.index.isin(rec.index)] = "re-parsed"
    return var_fib, status


def add_composition(models, variants, var_fib):
    """Model composition (mean over colours), fibre groups and composition flags."""
    vf = var_fib.join(variants.set_index("variant_key")["model_key"])
    mod_fib = vf.groupby("model_key")[PCT].mean()
    n_comp = vf.groupby("model_key").size()

    models = models.drop(columns=[c for c in PCT if c in models.columns])
    models = models.join(mod_fib, on="model_key")
    models["n_variants_with_composition"] = models["model_key"].map(n_comp).fillna(0).astype(int)
    models["has_composition"] = models["n_variants_with_composition"] > 0

    for g, fs in FIBRE_GROUPS.items():
        models[g] = models[[f + "_pct" for f in fs]].sum(axis=1, min_count=1)
    models["natural_pct"] = models["animal_pct"] + models["plant_pct"]
    models["wool_cashmere_pct"] = models["wool_pct"] + models["cashmere_pct"]

    has = models["has_composition"]
    models["all_natural"] = (models["natural_pct"] >= 99.5).where(has)
    models["any_synthetic"] = (models["synthetic_pct"] > 0).where(has)
    models["synthetic_majority"] = (models["synthetic_pct"] > 50).where(has)
    models["contains_wool_or_cashmere"] = (models["wool_cashmere_pct"] > 0).where(has)
    models[FLAG_COLS] = models[FLAG_COLS].astype("boolean")
    models["dominant_fiber"] = models.loc[has, PCT].idxmax(axis=1).str.replace("_pct", "").reindex(models.index)
    models["n_fibers"] = (models[PCT] > 0.5).sum(axis=1).where(has)
    return models


FLAG_COLS = ["all_natural", "any_synthetic", "synthetic_majority", "contains_wool_or_cashmere"]


# ------------------------------------------------------------------ 4. price
def add_prices(models, variants):
    models["price"] = models["price_median"]
    models["log10_price"] = np.log10(models["price"])
    variants["price_regular"] = variants["price_original"].where(variants["on_sale"] & variants["price_original"].notna(),
                                                                 variants["price_current"])
    models["price_regular"] = models["model_key"].map(variants.groupby("model_key")["price_regular"].median())
    models["share_colours_on_sale"] = models["model_key"].map(variants.groupby("model_key")["on_sale"].mean())
    return models, variants


# ------------------------------------------------------------------ 5. care, origin, claims
def care_category(t):
    """The most demanding washing method on the care label."""
    if pd.isna(t):
        return np.nan
    s = t.lower()
    if re.search(r"machine wash|gentle cycle|delicate cycle", s):
        return "Machine wash"
    if re.search(r"hand wash", s):
        return "Hand wash"
    if re.search(r"dry clean", s) and not re.search(r"do not dry clean", s):
        return "Dry clean only"
    if re.search(r"do not wash|not washable|unwashable|specialist cleaning", s):
        return "Do not wash"
    return "No washing instruction"


def add_care(models, variants):
    variants["care_category"] = variants["care_raw"].map(care_category)
    care_mode = variants.dropna(subset=["care_category"]).groupby("model_key")["care_category"] \
                        .agg(lambda s: s.value_counts().index[0])
    models["care_category"] = models["model_key"].map(care_mode)
    return models, variants


def add_origin(models, variants):
    """Standardised origin country, how origin is reported, and Mango's production stages."""
    origin_raw = variants.groupby("model_key")["origin_raw"].agg(lambda s: "; ".join(s.dropna().unique()) or np.nan)
    models["origin_raw"] = models["model_key"].map(origin_raw)
    made_in = models["origin_raw"].str.extract(r"(?i)made in\s+([a-z]+)")[0].str.title()
    models["origin_country_std"] = models["origin_country"].fillna(made_in).replace({"Türkiye": "Turkey", "Mainland China": "China"})
    models["origin_status"] = np.select(
        [models["origin_country_std"].notna(), models["origin_raw"].str.contains("imported", case=False, na=False)],
        ["country given", "'Imported' only"], default="not available")
    stages = models["origin_raw"].str.extract(
        r"Manufacture:\s*(?P<manufacture>[^;]+)(?:;\s*Dye/printing:\s*(?P<dye>[^;]+))?(?:;\s*Weave:\s*(?P<weave>[^;]+))?")
    for c in stages:
        models[f"origin_{c}"] = stages[c].str.strip().replace({"Türkiye": "Turkey"})
    return models


CERT_RE = r"(?i)\b(?:RWS|RCS|OCS|RMS|RAS|GCS|GOTS|GRS|responsible (?:wool|mohair) standard|certified)\b"
REC_BEFORE = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*%\s*(?:uses\s+)?(?:RCS[- ]certified\s+)?recycled\s+([a-z]+)")  # "29% RCS-certified recycled polyamide"
REC_AFTER = re.compile(r"(?i)(?:^|[:,]\s*)recycled\s+([a-z]+)\s+(\d+(?:\.\d+)?)\s*%")                   # "Shell: Recycled polyamide 38%"
TEXT_SOURCES = ["sustainability_raw", "composition_raw", "description_raw"]
CLAIM_COLS = ["recycled_claim", "certified_claim", "organic_claim"]


def recycled_share(text):
    """Recycled % of the main fabric: first statement per fibre (later ones describe other parts), summed."""
    if pd.isna(text):
        return 0.0
    main = re.split(SECTION_STOP, text)[0]
    found = [(m.start(), m.group(2).lower(), float(m.group(1))) for m in REC_BEFORE.finditer(main)]
    found += [(m.start(), m.group(1).lower(), float(m.group(2))) for m in REC_AFTER.finditer(main)]
    first = {}
    for _, fibre, pct in sorted(found):
        first.setdefault(fibre, pct)
    return sum(first.values())


def add_claims(models, variants):
    """Claims at colour level (NaN where the brand shows none), then 'any colour' per model."""
    rec_by_source = pd.concat({c: variants[c].map(recycled_share) for c in TEXT_SOURCES}, axis=1)
    text_all = variants[TEXT_SOURCES].fillna("").agg(" ".join, axis=1)
    variants["claim_source"] = variants["brand"].map(CLAIM_SOURCE)
    details_seen = variants[["composition_raw", "care_raw", "origin_raw", "sustainability_raw"]].notna().any(axis=1)
    variants["claim_observable"] = details_seen & variants["claim_source"].ne("none captured")
    obs = variants["claim_observable"]
    variants["recycled_pct"] = rec_by_source.max(axis=1).clip(upper=100).where(obs)
    variants["recycled_claim"] = (variants["recycled_pct"].gt(0) | text_all.str.contains("recycl", case=False)).where(obs)
    variants["certified_claim"] = text_all.str.contains(CERT_RE).where(obs)
    variants["organic_claim"] = text_all.str.contains("organic", case=False).where(obs)
    variants[CLAIM_COLS] = variants[CLAIM_COLS].astype("boolean")
    variants["any_claim"] = variants["recycled_claim"] | variants["certified_claim"] | variants["organic_claim"]

    obs_v = variants[obs]
    claims = obs_v.groupby("model_key").agg(recycled_claim=("recycled_claim", "any"), certified_claim=("certified_claim", "any"),
                                            organic_claim=("organic_claim", "any"), any_claim=("any_claim", "any"),
                                            recycled_pct=("recycled_pct", "mean"))
    models = models.drop(columns=[c for c in claims.columns if c in models.columns]).join(claims, on="model_key")
    models[CLAIM_COLS + ["any_claim"]] = models[CLAIM_COLS + ["any_claim"]].astype("boolean")
    models["claim_source"] = models["brand"].map(CLAIM_SOURCE)
    models["claim_observable"] = models["model_key"].isin(obs_v["model_key"])
    return models, variants


# ------------------------------------------------------------------ pipeline
KEEP = ["model_key", "brand", "segment", "model_id", "product_name", "category", "subcategory", "is_cape", "n_colours",
        "first_collected", "last_collected",
        "price", "price_min", "price_max", "price_regular", "log10_price", "price_outlier", "any_on_sale", "max_discount_pct",
        "share_colours_on_sale",
        "has_composition", "n_variants_with_composition", "composition_varies", "composition_outer_raw", *PCT,
        "animal_pct", "plant_pct", "natural_pct", "cellulosic_pct", "synthetic_pct", "other_group_pct", "wool_cashmere_pct",
        "all_natural", "any_synthetic", "synthetic_majority", "contains_wool_or_cashmere", "dominant_fiber", "n_fibers",
        "origin_status", "origin_country_std", "origin_manufacture", "origin_dye", "origin_weave",
        "claim_source", "claim_observable", "recycled_pct", "recycled_claim", "certified_claim", "organic_claim", "any_claim",
        "care_category"]

VARIANT_KEEP = ["variant_key", "model_key", "brand", "product_name", "category", "subcategory", "color", "product_url",
                "price_current", "price_original", "on_sale", "discount_pct", "price_regular", "comp_status", *PCT,
                "composition_raw", "composition_outer_raw", "origin_raw", "origin_country", "care_raw", "care_category",
                "sustainability_raw", "claim_source", "claim_observable", "recycled_pct", *CLAIM_COLS, "any_claim",
                "weight_g", "source_mode", "collected_date"]


def build(models_raw, variants_raw, fibres_raw):
    """Full pipeline: returns (variants_clean, models_clean). models_clean has the 67 columns of KEEP."""
    models, variants, fibres = select_scope(models_raw, variants_raw, fibres_raw)
    models["price_outlier"] = flag_price_outliers(models)
    var_fib, status = variant_compositions(variants, fibres)
    models = add_composition(models, variants, var_fib)
    models, variants = add_prices(models, variants)
    models, variants = add_care(models, variants)
    models = add_origin(models, variants)
    models, variants = add_claims(models, variants)

    variants["comp_status"] = variants["variant_key"].map(status)
    variants = variants.drop(columns=[c for c in PCT if c in variants.columns]).join(var_fib, on="variant_key")
    return variants[[c for c in VARIANT_KEEP if c in variants.columns]], models[KEEP].copy()


# ------------------------------------------------------------------ reading the clean tables
BOOL_COLS = ["is_cape", "price_outlier", "any_on_sale", "has_composition", "composition_varies", *FLAG_COLS,
             "claim_observable", *CLAIM_COLS, "any_claim"]


def _to_boolean(s):
    return s.map({True: True, False: False, "True": True, "False": False}).astype("boolean")


def add_analysis_columns(m):
    """Helper columns used by analysis, figures and dashboard (computed on reading, not stored):
    natural-log regular price, token animal fibre (0 < animal < 10%), name mentions an animal fibre,
    H&M premium line and plus sizes (from the subcategory)."""
    m = m.copy()
    has = m["has_composition"].fillna(False).astype(bool)
    m["log_price"] = np.log(m["price_regular"])
    m["token_animal"] = ((m["animal_pct"] > 0) & (m["animal_pct"] < 10)).astype(float).where(has)
    m["name_premium_fibre"] = m["product_name"].str.lower().str.contains("|".join(NAMED_FIBRES.values()), na=False)
    sub = m["subcategory"].fillna("").str.lower()
    m["premium_line"] = sub.isin(["premium selection", "100-cashmere"])
    m["plus_size"] = sub.eq("plus-sizes")
    return m


def load_clean(folder=None, helpers=True):
    """Read the clean tables written by `python -m src.build_dataset`.
    Returns (variants, models); models is indexed by model_key. `helpers=False` gives the stored columns only."""
    from .paths import CLEAN
    folder = folder or CLEAN
    v = pd.read_csv(folder / "variants_clean.csv", low_memory=False)
    m = pd.read_csv(folder / "models_clean.csv").set_index("model_key")
    for c in BOOL_COLS:
        if c in m.columns:
            m[c] = _to_boolean(m[c])
    for c in ["on_sale", "claim_observable", *CLAIM_COLS, "any_claim"]:
        if c in v.columns:
            v[c] = _to_boolean(v[c])
    return v, (add_analysis_columns(m) if helpers else m)
