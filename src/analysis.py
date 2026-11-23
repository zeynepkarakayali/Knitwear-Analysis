"""Statistics used for Q1-Q3 (rank-based tests, effect sizes, within-brand correlations, price model)."""
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.formula.api import ols
from statsmodels.stats.multitest import multipletests

from .config import NAMED_FIBRES


# ------------------------------------------------------------------ effect sizes and tests
def bh(pvalues):
    """Benjamini-Hochberg adjusted p-values; NaN p-values stay NaN."""
    p = pd.Series(pvalues, dtype=float)
    out = pd.Series(np.nan, index=p.index)
    ok = p.notna()
    if ok.any():
        out[ok] = multipletests(p[ok], method="fdr_bh")[1]
    return out.values


def kruskal_eps2(df, y, group):
    """Kruskal-Wallis H, p and epsilon^2 (share of rank variance explained by the groups)."""
    groups = [g[y].dropna() for _, g in df.groupby(group) if g[y].notna().sum() > 1]
    h, p = stats.kruskal(*groups)
    n = sum(len(g) for g in groups)
    return h, p, h / (n - 1)


def cliffs_delta(a, b):
    """Cliff's delta = P(a > b) - P(a < b), from the Mann-Whitney U of a; between -1 and 1."""
    a, b = pd.Series(a).dropna(), pd.Series(b).dropna()
    if len(a) == 0 or len(b) == 0:
        return np.nan
    u = stats.mannwhitneyu(a, b).statistic
    return 2 * u / (len(a) * len(b)) - 1


def boot_rho(x, y, n_boot=1000, seed=0):
    """95% bootstrap interval of Spearman's rho."""
    rng = np.random.default_rng(seed)
    x, y = np.asarray(x), np.asarray(y)
    out = [stats.spearmanr(x[s], y[s])[0] for s in (rng.integers(0, len(x), len(x)) for _ in range(n_boot))]
    return np.nanpercentile(out, [2.5, 97.5])


def brands_by_price(m):
    """Brands sorted by median regular price (cheapest first)."""
    return m.groupby("brand")["price_regular"].median().sort_values(kind="stable").index.tolist()


# ------------------------------------------------------------------ Q1
def category_gap_by_brand(m, brands=None):
    """Sweater vs cardigan price inside each brand: medians, Cliff's delta, BH-corrected Mann-Whitney p."""
    rows = []
    for b in brands or brands_by_price(m):
        g = m[m["brand"] == b]
        sw = g.loc[g["category"] == "sweater", "price_regular"]
        ca = g.loc[g["category"] == "cardigan", "price_regular"]
        rows.append({"brand": b, "n_sweater": len(sw), "n_cardigan": len(ca),
                     "median_sweater": sw.median(), "median_cardigan": ca.median(),
                     "delta_cardigan_vs_sweater": cliffs_delta(ca, sw),
                     "p": stats.mannwhitneyu(ca, sw).pvalue if len(ca) and len(sw) else np.nan})
    out = pd.DataFrame(rows).set_index("brand")
    out["p_BH"] = bh(out["p"])
    return out


def pairwise_price_deltas(m, brands=None):
    """Lower-triangle matrices of Cliff's delta (row vs column brand) and BH-adjusted Mann-Whitney p."""
    B = brands or brands_by_price(m)
    k = len(B)
    D, P = np.full((k, k), np.nan), np.full((k, k), np.nan)
    low = np.tril_indices(k, -1)
    for i, j in zip(*low):
        a = m.loc[m["brand"] == B[i], "price_regular"]
        c = m.loc[m["brand"] == B[j], "price_regular"]
        D[i, j] = cliffs_delta(a, c)
        P[i, j] = stats.mannwhitneyu(a, c).pvalue
    PA = np.full((k, k), np.nan)
    PA[low] = multipletests(P[low], method="fdr_bh")[1]
    return B, D, PA


# ------------------------------------------------------------------ Q2
def within_brand_spearman(m, variables=("animal_pct", "synthetic_pct"), brands=None, boot=True):
    """Spearman rho of log price with each variable inside each brand (+ bootstrap CI, BH p)."""
    rows = []
    for b in brands or sorted(m["brand"].unique()):
        g = m[m["brand"] == b]
        for y in variables:
            d = g[["log_price", y]].dropna()
            r, p = stats.spearmanr(d["log_price"], d[y])
            lo, hi = boot_rho(d["log_price"], d[y]) if boot else (np.nan, np.nan)
            rows.append({"brand": b, "variable": y, "n": len(d), "rho": r, "ci_low": lo, "ci_high": hi, "p": p})
    out = pd.DataFrame(rows)
    out["p_BH"] = bh(out["p"])
    return out


PRICE_MODEL_TERMS = {"I(wool_pct / 10)": "wool", "I(cashmere_pct / 10)": "cashmere",
                     "I((mohair_pct + alpaca_pct + silk_pct + other_animal_pct) / 10)": "mohair, alpaca, silk, yak",
                     "I(plant_pct / 10)": "cotton, linen", "I(cellulosic_pct / 10)": "viscose, lyocell, modal, acetate"}


def price_premium_model(m):
    """log price ~ fibre shares (per 10 points; synthetic + other = reference) + category, with and without
    brand fixed effects (HC3 errors). Returns a tidy table of % price changes with 95% CI."""
    formula = "log_price ~ " + " + ".join(PRICE_MODEL_TERMS) + " + C(category)"
    fits = {"across brands": ols(formula, data=m).fit(cov_type="HC3"),
            "within brand (brand fixed effects)": ols(formula + " + C(brand)", data=m).fit(cov_type="HC3")}
    rows = []
    for name, f in fits.items():
        ci = f.conf_int()
        for t, lab in PRICE_MODEL_TERMS.items():
            rows.append({"model": name, "fibre": lab, "price_change_pct": 100 * (np.exp(f.params[t]) - 1),
                         "ci_low_pct": 100 * (np.exp(ci.loc[t, 0]) - 1),
                         "ci_high_pct": 100 * (np.exp(ci.loc[t, 1]) - 1), "p": f.pvalues[t],
                         "n": int(f.nobs), "r2": f.rsquared})
    return pd.DataFrame(rows)


def bin_shares(m, col, bins, brands):
    """% of each brand's models falling in each (low, high, label] bin of `col`."""
    x = m[[col, "brand"]].dropna()
    out = pd.DataFrame({lab: x.groupby("brand")[col].apply(lambda s: ((s > lo) & (s <= hi)).mean() * 100)
                        for lo, hi, lab in bins})
    return out.loc[brands]


# ------------------------------------------------------------------ within-brand (intraclass) variation
VARIATION_COLS = ("animal_pct", "plant_pct", "cellulosic_pct", "synthetic_pct")


def within_brand_variation(m, cols=VARIATION_COLS, brands=None):
    """Spread of each fibre group inside each brand: n, mean, SD, quartiles and IQR (percentage points)."""
    rows = []
    for b in brands or brands_by_price(m):
        g = m[m["brand"] == b]
        for c in cols:
            x = g[c].dropna()
            q1, med, q3 = x.quantile([.25, .5, .75])
            rows.append({"brand": b, "fibre_group": c, "n": len(x), "mean": x.mean(), "sd": x.std(),
                         "q1": q1, "median": med, "q3": q3, "iqr": q3 - q1})
    return pd.DataFrame(rows)


def variance_partition(m, cols=VARIATION_COLS, group="brand"):
    """How much of each variable's variation lies between brands and how much within them.
    eta2 = between-brand sum of squares / total; ICC(1) from one-way ANOVA (unequal group sizes);
    epsilon2 = Kruskal-Wallis rank version. 1 - eta2 is the within-brand share."""
    rows = []
    for c in cols:
        d = m[[group, c]].dropna()
        groups = [x[c].to_numpy() for _, x in d.groupby(group)]
        n_i = np.array([len(x) for x in groups])
        N, k = n_i.sum(), len(groups)
        grand = d[c].mean()
        ssb = sum(len(x) * (x.mean() - grand) ** 2 for x in groups)
        ssw = sum(((x - x.mean()) ** 2).sum() for x in groups)
        msb, msw = ssb / (k - 1), ssw / (N - k)
        n0 = (N - (n_i ** 2).sum() / N) / (k - 1)
        rows.append({"variable": c, "n": int(N), "eta2_between": ssb / (ssb + ssw),
                     "within_share": ssw / (ssb + ssw), "icc1": (msb - msw) / (msb + (n0 - 1) * msw),
                     "epsilon2_rank": kruskal_eps2(d, c, group)[2]})
    return pd.DataFrame(rows).set_index("variable")


# ------------------------------------------------------------------ Q3
def named_fibre_mentions(m):
    """One row per (model, fibre named in the product name) with the share of that fibre in the garment."""
    src = m if "model_key" in m.columns else m.reset_index()      # works with or without model_key as index
    name = src["product_name"].str.lower()
    cols = ["model_key", "brand", "segment", "product_name", "animal_pct"]
    men = pd.concat([src.loc[name.str.contains(rx), cols + [f + "_pct"]]
                     .rename(columns={f + "_pct": "named_pct"}).assign(named_fibre=f)
                     for f, rx in NAMED_FIBRES.items()])
    men = men.dropna(subset=["named_pct"]).reset_index(drop=True)
    men["blend_in_name"] = men["product_name"].str.contains(r"blend|mix", case=False)
    men["minority"] = men["named_pct"] < 50
    return men


# ------------------------------------------------------------------ robustness: balanced subsample
def balanced_subsample(m, n=60, seed=0):
    """`n` models drawn at random from every brand (without replacement), so each brand weighs the same."""
    parts = [g.sample(n=min(n, len(g)), random_state=seed) for _, g in m.groupby("brand")]
    return pd.concat(parts)


def headline_stats(m):
    """Pooled statistics that depend on how many models each brand contributes."""
    ff, mp = m[m["segment"] == "Fast fashion"], m[m["segment"] == "Mid/premium"]
    men = named_fibre_mentions(m)
    d = m[["log_price", "animal_pct"]].dropna()
    return {
        "Q1 price ~ brand, epsilon²": kruskal_eps2(m, "price_regular", "brand")[2],
        "Q1 median price, fast fashion ($)": ff["price_regular"].median(),
        "Q1 median price, mid / premium ($)": mp["price_regular"].median(),
        "Q2 mean synthetic share, fast fashion (%)": ff["synthetic_pct"].mean(),
        "Q2 mean synthetic share, mid / premium (%)": mp["synthetic_pct"].mean(),
        "Q2 majority-synthetic models, fast fashion (%)": ff["synthetic_majority"].mean() * 100,
        "Q2 majority-synthetic models, mid / premium (%)": mp["synthetic_majority"].mean() * 100,
        "Q2 pooled rho(log price, animal share)": stats.spearmanr(d["log_price"], d["animal_pct"])[0],
        "Q3 named fibre < 50% of the garment (% of mentions)": men["minority"].mean() * 100,
        "Q3 token animal fibre, fast fashion (% of models)": ff["token_animal"].mean() * 100,
    }


def robustness_balanced(m, n=60, reps=200, seed=0):
    """Headline statistics on the full data vs. `reps` balanced subsamples of `n` models per brand
    (mean and 2.5-97.5% range over the subsamples)."""
    full = headline_stats(m)
    runs = pd.DataFrame([headline_stats(balanced_subsample(m, n, seed + r)) for r in range(reps)])
    out = pd.DataFrame({"full data": pd.Series(full), "balanced mean": runs.mean(),
                        "balanced 2.5%": runs.quantile(0.025), "balanced 97.5%": runs.quantile(0.975)})
    out.index.name = "statistic"
    return out
