"""Figure functions. Each takes the clean model table `m` (and, for missingness, the raw colour table)
and returns a matplotlib Figure, so the same figure can be shown in the notebook, the dashboard or the report.

    python -m src.make_figures      # writes every figure to reports/figures/
"""
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from . import analysis as A
from .config import SEGMENT, BRAND_ORDER, SHORT, FIB_ORDER, FIBRE_GROUPS, NAMED_FIBRES
from .style import (INK, INK2, MUTED, SURFACE, CAT, SEQ, DIV, SEG_COLOR, GROUP_COLOR, GROUP_LABEL, GROUP_SHORT,
                    PRICE_TICKS, apply_style, price_axis, annotate_heatmap, clean_heatmap_axes, colorbar)

apply_style()
GROUPS = list(FIBRE_GROUPS)


def _segment_legend(ax, marker="o", **kw):
    for seg, col in SEG_COLOR.items():
        ax.scatter([], [], marker=marker, s=35, color=col, label=seg)
    ax.legend(**({"loc": "lower right", "fontsize": 8} | kw))


# ================================================================== data description
def missingness_by_brand(variants_raw, brands=BRAND_ORDER):
    """Heatmap: % of colours missing each field, by brand (raw data)."""
    vr = variants_raw
    fields = {
        "composition (fibre %)": vr["cotton_pct"].isna(),
        "price_current": vr["price_current"].isna(),
        "price_original (on sale)": vr["price_original"].isna().where(vr["on_sale"]),
        "discount_pct (on sale)": vr["discount_pct"].isna().where(vr["on_sale"]),
        "origin_country": vr["origin_country"].isna(),
        "sustainability_raw": vr["sustainability_raw"].isna(),
        "care_raw": vr["care_raw"].isna(),
        "description_raw": vr["description_raw"].isna(),
        "colour": vr["color"].isna(),
        "weight_g": vr["weight_g"].isna(),
        "fit": vr["fit"].isna(),
        "supplier_factory": vr["supplier_factory"].isna(),
    }
    tab = pd.DataFrame({k: s.astype(float).groupby(vr["brand"]).mean() * 100 for k, s in fields.items()}).T[brands]
    data = tab.values.astype(float)

    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    im = ax.imshow(np.nan_to_num(data, nan=0), cmap=SEQ, vmin=0, vmax=100, aspect="auto")
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            val = data[i, j]
            ax.text(j, i, "n/a" if np.isnan(val) else f"{val:.0f}", ha="center", va="center", fontsize=7.5,
                    color="#ffffff" if (not np.isnan(val) and val > 55) else INK2)
    ax.set_xticks(range(len(brands)), [SHORT.get(b, b) for b in brands])
    ax.set_yticks(range(len(fields)), list(fields))
    clean_heatmap_axes(ax)
    ax.axvline(3.5, color=SURFACE, lw=3)
    ax.text(1.5, -0.95, "Fast fashion", ha="center", fontsize=8, color=INK2)
    ax.text(5.5, -0.95, "Mid/premium", ha="center", fontsize=8, color=INK2)
    colorbar(fig, im, ax, "% of variants missing")
    ax.set_title("Missing values are brand-specific, not random", pad=18)
    return fig


def distributions(m):
    """(a) price by brand, (b) log-price histogram, (c) Q-Q plot, (d) natural-share histogram."""
    order = A.brands_by_price(m)
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.2))

    ax = axes[0, 0]
    data = [m.loc[m["brand"] == b, "price_regular"].dropna() for b in order]
    mpl_ver = tuple(int(x) for x in mpl.__version__.split(".")[:2])   # "orientation" exists from 3.10
    horiz = {"orientation": "horizontal"} if mpl_ver >= (3, 10) else {"vert": False}
    bp = ax.boxplot(data, **horiz, patch_artist=True, widths=0.55, showfliers=True,
                    medianprops=dict(color=INK, lw=1.4), whiskerprops=dict(color=MUTED, lw=1),
                    capprops=dict(color=MUTED, lw=1),
                    flierprops=dict(marker="o", ms=2.5, mfc=MUTED, mec="none", alpha=.6))
    for patch, b in zip(bp["boxes"], order):
        patch.set(facecolor=SEG_COLOR[SEGMENT[b]], edgecolor=SEG_COLOR[SEGMENT[b]], alpha=.85, lw=1)
    ax.set_yticks(range(1, len(order) + 1), [f"{b} (n={len(d)})" for b, d in zip(order, data)])
    price_axis(ax)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("regular price (USD, log scale)")
    ax.set_title("a. Regular price by brand")
    _segment_legend(ax, marker="s")

    x = m["log_price"].dropna()
    ax = axes[0, 1]
    ax.hist(x, bins=25, color=CAT[0], edgecolor=SURFACE, lw=0.6, density=True)
    grid = np.linspace(x.min(), x.max(), 200)
    ax.plot(grid, stats.norm.pdf(grid, x.mean(), x.std()), color=INK2, lw=1.4, ls="--", label="normal fit")
    ax.set_xlabel("log(regular price)")
    ax.set_ylabel("density")
    ax.set_title(f"b. Log price, all models (skew {x.skew():.2f})")
    ax.legend(fontsize=8)

    ax = axes[1, 0]
    (osm, osr), (slope, intercept, _) = stats.probplot(x, dist="norm")
    ax.plot(osm, osr, "o", ms=2.5, color=CAT[0], alpha=.7)
    ax.plot(osm, slope * osm + intercept, color=INK2, lw=1.2, ls="--")
    ax.set_xlabel("theoretical normal quantiles")
    ax.set_ylabel("observed log price")
    ax.set_title("c. Q-Q plot of log price")

    ax = axes[1, 1]
    ax.hist(m["natural_pct"].dropna(), bins=np.arange(0, 105, 5), color=CAT[1], edgecolor=SURFACE, lw=0.6)
    ax.set_xlabel("natural fibre share of the garment (%)")
    ax.set_ylabel("number of models")
    ax.set_title("d. Natural-fibre share: U-shaped, not normal")
    fig.tight_layout()
    return fig


def fibre_mix_by_brand(m, compact=False):
    """Stacked bars of the mean fibre-group shares per brand (brands ordered by median price)."""
    order = A.brands_by_price(m)
    fib = m.groupby("brand")[GROUPS].mean().loc[order]
    med = m.groupby("brand")["price_regular"].median()
    fig, ax = plt.subplots(figsize=(3.45, 2.35) if compact else (9, 4.2))
    left = np.zeros(len(fib))
    ypos = np.arange(len(fib))[::-1]
    for g in GROUPS:
        vals = fib[g].values
        lab = GROUP_SHORT[g] if compact else GROUP_LABEL[g]
        ax.barh(ypos, vals, left=left, color=GROUP_COLOR[g], edgecolor=SURFACE, lw=0.8 if compact else 1.2,
                height=0.72, label=lab)
        for y, l, w in zip(ypos, left, vals):
            if w >= (12 if compact else 9):
                ax.text(l + w / 2, y, f"{w:.0f}", ha="center", va="center", fontsize=6 if compact else 7.5,
                        color="#ffffff")
        left += vals
    ax.set_yticks(ypos, [f"{b} (${med[b]:.0f})" for b in fib.index], fontsize=6.5 if compact else None)
    ax.set_xlim(0, 100)
    ax.grid(axis="y", visible=False)
    if compact:
        ax.set_xlabel("mean share of the garment (%)", fontsize=6.5)
        ax.tick_params(labelsize=6.5, length=0)
        ax.legend(ncol=5, loc="lower left", bbox_to_anchor=(-0.02, 1.0), fontsize=6, handlelength=1,
                  columnspacing=0.8)
    else:
        ax.set_xlabel("brands ordered by median regular price (in brackets)", fontsize=8)
        ax.legend(ncol=2, fontsize=7.5, loc="upper left", bbox_to_anchor=(0, -0.13))
        ax.set_title("Fibre mix by brand (mean % of the garment)")
    return fig


# ================================================================== Q1 price
def price_by_brand_and_category(m):
    """(a) every model's price by brand with median / IQR; (b) sweaters vs cardigans per brand."""
    order = A.brands_by_price(m)
    cat_gap = A.category_gap_by_brand(m, order)
    rng = np.random.default_rng(0)
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.9), gridspec_kw={"width_ratios": [1.2, 1]})

    ax = axes[0]
    for i, b in enumerate(order):
        y = m.loc[m["brand"] == b, "price_regular"].dropna()
        ax.scatter(y, i + rng.uniform(-0.25, 0.25, len(y)), s=7, color=SEG_COLOR[SEGMENT[b]], alpha=0.35, lw=0)
        q_lo, med, q_hi = y.quantile([.25, .5, .75])
        ax.plot([q_lo, q_hi], [i, i], color=INK, lw=2.4, solid_capstyle="round", zorder=3)
        ax.plot(med, i, "o", ms=7, mfc="white", mec=INK, mew=1.6, zorder=4)
        ax.text(1.01, i, f"${med:.0f}", transform=ax.get_yaxis_transform(), va="center", fontsize=8, color=INK2)
    ax.text(1.01, len(order) - 0.35, "median", transform=ax.get_yaxis_transform(), fontsize=7.5, color=MUTED)
    ax.set_yticks(range(len(order)), [f"{b} (n={int((m['brand'] == b).sum())})" for b in order])
    price_axis(ax)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("regular price (USD, log scale)")
    ax.set_title("a. Regular price by brand (dot = median, bar = IQR)")
    _segment_legend(ax)

    ax = axes[1]
    style = {"sweater": (CAT[2], "o", -0.16), "cardigan": (CAT[6], "D", 0.16)}
    for i, b in enumerate(order):
        for cat, (col, mk, off) in style.items():
            y = m.loc[(m["brand"] == b) & (m["category"] == cat), "price_regular"]
            q_lo, med, q_hi = y.quantile([.25, .5, .75])
            ax.plot([q_lo, q_hi], [i + off] * 2, color=col, lw=1.8)
            ax.plot(med, i + off, mk, color=col, ms=6.5, mec=SURFACE, mew=1, zorder=3)
    ax.set_yticks(range(len(order)), [b + ("  *" if cat_gap.loc[b, "p_BH"] < 0.05 else "") for b in order])
    price_axis(ax)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("regular price (USD, log scale)")
    ax.set_title("b. Sweaters vs. cardigans (* = BH p < 0.05)")
    for cat, (col, mk, _) in style.items():
        ax.plot([], [], mk, color=col, label=f"{cat}s: median and IQR", ms=6)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    return fig


def pairwise_price_differences(m):
    """Lower-triangle heatmap of Cliff's delta between brands (BH-corrected significance)."""
    B, D, PA = A.pairwise_price_deltas(m)
    k = len(B)
    fig, ax = plt.subplots(figsize=(6.6, 5.6))
    im = ax.imshow(np.ma.masked_invalid(D), cmap=DIV, vmin=-1, vmax=1)
    for i, j in zip(*np.tril_indices(k, -1)):
        ax.text(j, i, f"{D[i, j]:.2f}" + ("" if PA[i, j] < 0.05 else "\nn.s."), ha="center", va="center",
                fontsize=7.5, color="#ffffff" if abs(D[i, j]) > 0.6 else INK2)
    ax.set_xticks(range(k), [SHORT.get(b, b) for b in B], rotation=35, ha="right")
    ax.set_yticks(range(k), B)
    clean_heatmap_axes(ax)
    colorbar(fig, im, ax, "Cliff's δ: row brand dearer (+) or cheaper (−) than column brand", fraction=0.04)
    ax.set_title("Pairwise price differences between brands\n(brands ordered by median price; n.s. = BH p ≥ 0.05)")
    return fig


# ================================================================== Q2 fibre vs price
def fibre_heatmaps(m, brands=BRAND_ORDER):
    """Brand x fibre heatmaps: (a) mean share of each fibre, (b) % of models containing it."""
    cols = [f + "_pct" for f in FIB_ORDER]
    mean_pct = m.groupby("brand")[cols].mean().loc[brands]
    prev_pct = (m[cols] > 0).groupby(m["brand"]).mean().mul(100).loc[brands]
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.6))
    for ax, data, title, vmax, unit in [
            (axes[0], mean_pct, "a. Mean share of each fibre in the garment (%)", 60, "mean % of garment"),
            (axes[1], prev_pct, "b. Models containing the fibre (% of the brand's models)", 100, "% of models")]:
        vals = data.values
        im = ax.imshow(vals, cmap=SEQ, vmin=0, vmax=vmax, aspect="auto")
        annotate_heatmap(ax, vals, lambda x: f"{x:.0f}", vmax)
        ax.set_xticks(range(len(FIB_ORDER)), FIB_ORDER, rotation=45, ha="right")
        ax.set_yticks(range(len(brands)), brands)
        clean_heatmap_axes(ax)
        start = 0
        for g, fs in FIBRE_GROUPS.items():                 # group dividers and labels follow FIB_ORDER
            end = start + len(fs)
            if end < len(FIB_ORDER):
                ax.axvline(end - 0.5, color=SURFACE, lw=3)
            if g != "other_group_pct":
                ax.text((start + end - 1) / 2, -0.85, GROUP_SHORT[g], ha="center", fontsize=8, color=INK2)
            start = end
        ax.axhline(3.5, color=SURFACE, lw=3)
        ax.set_title(title, pad=20)
        colorbar(fig, im, ax, unit)
    fig.text(0.005, 0.70, "fast\nfashion", fontsize=8, color=INK2, ha="left")
    fig.text(0.005, 0.30, "mid /\npremium", fontsize=8, color=INK2, ha="left")
    fig.tight_layout(rect=(0.04, 0, 1, 1))
    return fig


SYN_BINS = [(-0.1, 0.5, "0% (none)"), (0.5, 49.5, "1–49%"), (49.5, 99.5, "50–99%"), (99.5, 100.1, "100%")]
ANI_BINS = [(-0.1, 0.5, "0% (none)"), (0.5, 9.99, "1–9% (token)"), (9.99, 49.5, "10–49%"), (49.5, 99.5, "50–99%"),
            (99.5, 100.1, "100%")]
SYN_COLORS = ["#d9d8d2", "#86b6ef", "#3987e5", "#184f95"]
ANI_COLORS = ["#d9d8d2", "#f6c1a6", "#f08a5d", "#d95926", "#9c3d15"]
_DARK = ("#3987e5", "#184f95", "#d95926", "#9c3d15")


def synthetic_and_animal_bins(m, brands=BRAND_ORDER):
    """Share of each brand's models by synthetic-share bin (a) and animal-share bin (b)."""
    syn = A.bin_shares(m, "synthetic_pct", SYN_BINS, brands)
    ani = A.bin_shares(m, "animal_pct", ANI_BINS, brands)
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8), sharey=True)
    ypos = np.arange(len(brands))[::-1]
    for ax, tab, colors, title in [(axes[0], syn, SYN_COLORS, "a. Synthetic share of the garment"),
                                   (axes[1], ani, ANI_COLORS, "b. Animal-fibre share of the garment")]:
        left = np.zeros(len(tab))
        for lab, col in zip(tab.columns, colors):
            vals = tab[lab].values
            ax.barh(ypos, vals, left=left, color=col, edgecolor=SURFACE, lw=1.2, height=0.72, label=lab)
            for y_, l_, w_ in zip(ypos, left, vals):
                if w_ >= 8:
                    ax.text(l_ + w_ / 2, y_, f"{w_:.0f}", ha="center", va="center", fontsize=7.5,
                            color="#ffffff" if col in _DARK else INK)
            left += vals
        ax.axhline(3.5, color=INK2, lw=0.8, ls=":")
        ax.set_xlim(0, 100)
        ax.set_xlabel("% of the brand's models")
        ax.grid(axis="y", visible=False)
        ax.set_title(title)
        ax.legend(ncol=len(tab.columns), fontsize=7.5, loc="upper left", bbox_to_anchor=(0, -0.12))
    axes[0].set_yticks(ypos, brands)
    for y, lab in [(5.5, "fast fashion"), (1.5, "mid / premium")]:
        axes[0].text(-0.30, y, lab, transform=axes[0].get_yaxis_transform(), rotation=90, va="center",
                     fontsize=8, color=INK2)
    fig.tight_layout()
    return fig


_LABEL_OFFSETS = {("& Other Stories", "animal"): (-8, 6), ("Massimo Dutti", "animal"): (7, -14),
                  ("COS", "animal"): (7, 4), ("& Other Stories", "synthetic"): (-8, 6),
                  ("Massimo Dutti", "synthetic"): (-8, -12), ("COS", "synthetic"): (6, 8)}


def brand_level_price_vs_fibre(m):
    """8 brands: median price vs mean animal share (a) and mean synthetic share (b)."""
    bl = m.groupby("brand").agg(median_price=("price_regular", "median"), animal=("animal_pct", "mean"),
                                synthetic=("synthetic_pct", "mean"))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for ax, y, lab in [(axes[0], "animal", "mean animal-fibre share (%)"),
                       (axes[1], "synthetic", "mean synthetic share (%)")]:
        r, _ = stats.spearmanr(bl["median_price"], bl[y])
        for b, row in bl.iterrows():
            ax.scatter(row["median_price"], row[y], s=70, color=SEG_COLOR[SEGMENT[b]], edgecolor=SURFACE, lw=2,
                       zorder=3)
            dx, dy = _LABEL_OFFSETS.get((b, y), (7, 4))
            ax.annotate(b, (row["median_price"], row[y]), xytext=(dx, dy), textcoords="offset points",
                        fontsize=8, color=INK2, ha="right" if dx < 0 else "left")
        price_axis(ax)
        ax.set_xlim(30, 300)
        ax.set_ylim(-5, 100)
        ax.set_xlabel("median regular price of the brand (log scale)")
        ax.set_ylabel(lab)
        ax.set_title(f"{'a' if y == 'animal' else 'b'}. Brands: price vs {y} share (rho = {r:+.2f})")
    _segment_legend(axes[0], loc="upper left")
    fig.tight_layout()
    return fig


def within_brand(m, brands=BRAND_ORDER):
    """(a, b) mean animal / synthetic share by price quartile inside each brand; (c) within-brand Spearman rho."""
    q = m.groupby("brand")["price_regular"].transform(lambda x: pd.qcut(x.rank(method="first"), 4, labels=False) + 1)
    mm = m.assign(price_q=q)
    heat_animal = mm.pivot_table(index="brand", columns="price_q", values="animal_pct", aggfunc="mean").loc[brands]
    heat_syn = mm.pivot_table(index="brand", columns="price_q", values="synthetic_pct", aggfunc="mean").loc[brands]
    forest = A.within_brand_spearman(m, brands=brands)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.4), gridspec_kw={"width_ratios": [1, 1, 1.1]},
                             layout="constrained")
    qlabels = ["Q1\ncheapest", "Q2", "Q3", "Q4\ndearest"]
    for ax, tab, title in [(axes[0], heat_animal, "a. Mean animal share (%)"),
                           (axes[1], heat_syn, "b. Mean synthetic share (%)")]:
        vals = tab.values
        im = ax.imshow(vals, cmap=SEQ, vmin=0, vmax=100, aspect="auto")
        annotate_heatmap(ax, vals, lambda x: f"{x:.0f}", 100)
        ax.set_xticks(range(4), qlabels)
        ax.set_yticks(range(len(brands)), brands if ax is axes[0] else [])
        clean_heatmap_axes(ax)
        ax.axhline(3.5, color=SURFACE, lw=3)
        ax.set_xlabel("price quartile inside the brand")
        ax.set_title(title)
    colorbar(fig, im, axes[:2], "% of garment", orientation="horizontal", fraction=0.05, aspect=40)

    ax = axes[2]
    style = {"animal_pct": (CAT[0], "o", -0.15, "animal share"),
             "synthetic_pct": (CAT[1], "s", 0.15, "synthetic share")}
    for var, (col, mk, off, lab) in style.items():
        f = forest[forest["variable"] == var].set_index("brand").loc[brands]
        ys = np.arange(len(brands)) + off
        ax.hlines(ys, f["ci_low"], f["ci_high"], color=col, lw=1.8)
        ax.plot(f["rho"], ys, mk, color=col, ms=6.5, mec=SURFACE, mew=1, label=lab)
    ax.axvline(0, color=INK2, lw=0.9)
    ax.set_yticks(range(len(brands)), [SHORT.get(b, b) for b in brands])
    ax.set_ylim(len(brands) - 0.5, -0.5)
    ax.axhline(3.5, color=INK2, lw=0.8, ls=":")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(-0.75, 0.85)
    ax.set_xlabel("Spearman rho with log price (95% bootstrap CI)")
    ax.set_title("c. Within-brand correlation with price")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2, fontsize=8)
    return fig


def price_vs_animal_small_multiples(m):
    """One scatter per brand: regular price (log) vs animal-fibre share."""
    order = A.brands_by_price(m)
    rho = A.within_brand_spearman(m, variables=("animal_pct",), boot=False).set_index("brand")["rho"]
    fig, axes = plt.subplots(2, 4, figsize=(11, 5.2), sharey=True)
    for ax, b in zip(axes.ravel(), order):
        g = m[m["brand"] == b]
        ax.scatter(g["price_regular"], g["animal_pct"], s=9, color=SEG_COLOR[SEGMENT[b]], alpha=.55, lw=0)
        ax.set_title(f"{b}  (rho = {rho[b]:.2f})", fontsize=9)
        ax.set_xscale("log")
        ax.minorticks_off()
        ax.set_xticks([t for t in PRICE_TICKS if g["price_regular"].min() * 0.8 <= t <= g["price_regular"].max() * 1.2])
        ax.xaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda val, _: f"${val:.0f}"))
        ax.set_ylim(-5, 105)
    for ax in axes[:, 0]:
        ax.set_ylabel("animal fibre share (%)")
    for ax in axes[1, :]:
        ax.set_xlabel("regular price (log scale)")
    fig.suptitle("Within each brand, dearer models contain more animal fibre", x=0.01, ha="left",
                 fontsize=10, fontweight="bold")
    fig.tight_layout()
    return fig


def fibre_price_premium(m):
    """Coefficient plot of the price model (% price change per +10 points of a fibre replacing synthetic)."""
    coef = A.price_premium_model(m)
    labels = list(A.PRICE_MODEL_TERMS.values())
    fig, ax = plt.subplots(figsize=(8.5, 4))
    for name, col, mk, off in [("across brands", CAT[0], "o", -0.14),
                               ("within brand (brand fixed effects)", CAT[1], "s", 0.14)]:
        c = coef[coef["model"] == name].set_index("fibre").loc[labels]
        ys = np.arange(len(labels)) + off
        ax.hlines(ys, c["ci_low_pct"], c["ci_high_pct"], color=col, lw=1.8)
        ax.plot(c["price_change_pct"], ys, mk, color=col, ms=7, mec=SURFACE, mew=1, label=name)
    ax.axvline(0, color=INK2, lw=0.9)
    ax.set_yticks(range(len(labels)), labels)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("price change (%) when 10 points of synthetic fibre are replaced (95% CI)")
    ax.set_title("Price premium of fibres over synthetics (same category)")
    ax.legend(loc="lower right", fontsize=8)
    return fig


# ================================================================== Q3 names vs composition
def named_fibre_share(m, brands=BRAND_ORDER):
    """(a) median share of the named fibre by brand; (b) every mention, coloured by 'blend' wording."""
    men = A.named_fibre_mentions(m)
    named = list(NAMED_FIBRES)
    rng = np.random.default_rng(0)
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.4), gridspec_kw={"width_ratios": [1.05, 1]})

    ax = axes[0]
    med = men.pivot_table(index="named_fibre", columns="brand", values="named_pct", aggfunc="median") \
        .reindex(index=named, columns=brands)
    n = men.pivot_table(index="named_fibre", columns="brand", values="named_pct", aggfunc="size") \
        .reindex(index=named, columns=brands)
    vals = med.values.astype(float)
    im = ax.imshow(np.ma.masked_invalid(vals), cmap=SEQ, vmin=0, vmax=100, aspect="auto")
    for i in range(vals.shape[0]):
        for j in range(vals.shape[1]):
            if not np.isnan(vals[i, j]):
                ax.text(j, i, f"{vals[i, j]:.0f}%\nn={int(n.values[i, j])}", ha="center", va="center",
                        fontsize=7, color="#ffffff" if vals[i, j] > 55 else INK2)
    ax.set_xticks(range(len(brands)), [SHORT.get(b, b) for b in brands], rotation=30, ha="right")
    ax.set_yticks(range(len(named)), [f"name says {f}" for f in named])
    clean_heatmap_axes(ax)
    ax.axvline(3.5, color=SURFACE, lw=3)
    colorbar(fig, im, ax, "median % of the named fibre")
    ax.set_title("a. How much of the named fibre is in the garment?")

    ax = axes[1]
    for i, f in enumerate(named):
        d = men[men["named_fibre"] == f]
        for blend, col in [(False, CAT[6]), (True, CAT[1])]:
            x = d.loc[d["blend_in_name"] == blend, "named_pct"]
            ax.scatter(x, i + rng.uniform(-0.25, 0.25, len(x)), s=14, color=col, alpha=0.6, lw=0)
    ax.axvline(50, color=INK2, lw=0.9, ls="--")
    ax.text(50, -0.65, " 50%: named fibre is a minority", fontsize=7.5, color=INK2)
    ax.set_yticks(range(len(named)), [f"name says {f}" for f in named])
    ax.set_ylim(len(named) - 0.5, -0.8)
    ax.set_xlim(-3, 103)
    ax.set_xlabel("share of the named fibre in the garment (%)")
    ax.grid(axis="y", visible=False)
    ax.scatter([], [], s=25, color=CAT[6], label="no 'blend' / 'mix' in name")
    ax.scatter([], [], s=25, color=CAT[1], label="'blend' / 'mix' in name")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, fontsize=8)
    ax.set_title("b. Every named-fibre mention (one dot per model)")
    fig.tight_layout()
    return fig


def name_vs_composition(m):
    """Heatmap: animal-fibre bins for models whose name does / does not mention an animal fibre, by segment."""
    bins = [-0.1, 0.5, 9.99, 29.5, 49.5, 99.5, 100.1]
    labels = ["0%", "1–9%", "10–29%", "30–49%", "50–99%", "100%"]
    tmp = m[m["animal_pct"].notna()].assign(
        animal_bin=lambda d: pd.cut(d["animal_pct"], bins=bins, labels=labels),
        group=lambda d: d["segment"] + np.where(d["name_premium_fibre"], " · named", " · not named"))
    order = ["Fast fashion · named", "Fast fashion · not named", "Mid/premium · named", "Mid/premium · not named"]
    tab = pd.crosstab(tmp["group"], tmp["animal_bin"], normalize="index").mul(100).reindex(order)
    counts = tmp["group"].value_counts().reindex(order)

    fig, ax = plt.subplots(figsize=(8.6, 3.6))
    vals = tab.values
    im = ax.imshow(vals, cmap=SEQ, vmin=0, vmax=100, aspect="auto")
    annotate_heatmap(ax, vals, lambda x: f"{x:.0f}", 100)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yticks(range(len(order)), [f"{g} (n={counts[g]})" for g in order])
    clean_heatmap_axes(ax)
    ax.axhline(1.5, color=SURFACE, lw=3)
    ax.set_xlabel("animal-fibre share of the garment")
    colorbar(fig, im, ax, "% of models in the row")
    ax.set_title("Name vs. composition: 'named' = name mentions wool, merino, cashmere, mohair or alpaca")
    return fig


# ================================================================== registry
# file name -> (function, needs the raw colour table?)
ALL_FIGURES = {
    "fig0_main_fibre_mix": (lambda m, vr: fibre_mix_by_brand(m, compact=True), False),
    "fig1_missingness_by_brand": (lambda m, vr: missingness_by_brand(vr), True),
    "fig2_distributions": (lambda m, vr: distributions(m), False),
    "fig3_fibre_mix_by_brand": (lambda m, vr: fibre_mix_by_brand(m), False),
    "fig4_price_vs_animal_pct_within_brand": (lambda m, vr: price_vs_animal_small_multiples(m), False),
    "fig5_q1_price_by_brand_and_category": (lambda m, vr: price_by_brand_and_category(m), False),
    "fig6_q1_pairwise_price_differences": (lambda m, vr: pairwise_price_differences(m), False),
    "fig7_q2_fibre_heatmaps": (lambda m, vr: fibre_heatmaps(m), False),
    "fig8_q2_synthetic_and_animal_bins": (lambda m, vr: synthetic_and_animal_bins(m), False),
    "fig9_q2_brand_level_price_vs_fibre": (lambda m, vr: brand_level_price_vs_fibre(m), False),
    "fig10_q2_within_brand": (lambda m, vr: within_brand(m), False),
    "fig11_q2_fibre_price_premium": (lambda m, vr: fibre_price_premium(m), False),
    "fig12_q3_named_fibre_share": (lambda m, vr: named_fibre_share(m), False),
    "fig13_q3_name_vs_composition": (lambda m, vr: name_vs_composition(m), False),
}
