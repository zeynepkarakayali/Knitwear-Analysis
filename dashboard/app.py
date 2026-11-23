"""Knitwear dashboard (Deliverable 2).

    streamlit run dashboard/app.py      # from the project root

Reads data/clean/ (written by `python3 -m src.build_dataset`) and data/merged/variants.csv (missing-value view).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import analysis as A                                      # noqa: E402
from src.cleaning import load_clean, load_merged                   # noqa: E402
from src.config import BRAND_ORDER, FIB_ORDER, FIBRE_GROUPS, NAMED_FIBRES, SEGMENT, SUST_BRANDS  # noqa: E402
from src.style import CAT, OTHER_GREY, GROUP_COLOR, INK2              # noqa: E402

st.set_page_config(page_title="Knitwear across fashion segments", page_icon="🧶", layout="wide")

SEQ_SCALE = ["#f3f7fc", "#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"]
BRAND_COLOR = dict(zip(BRAND_ORDER, CAT))                         # fixed colour per brand
SEG_COLOR = {"Fast fashion": CAT[0], "Mid/premium": CAT[1], "UNIQLO": CAT[2]}
GROUP_NAME = {"animal_pct": "animal", "plant_pct": "plant", "cellulosic_pct": "man-made cellulosic",
              "synthetic_pct": "synthetic", "other_group_pct": "other"}
PRICE_TICKS = [10, 20, 50, 100, 200, 500]
LAYOUT = dict(template="simple_white", margin=dict(l=10, r=10, t=30, b=10), font=dict(size=13),
              legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, title_text=""))


def log_price_axis(fig, axis="x"):
    upd = dict(type="log", tickvals=PRICE_TICKS, ticktext=[f"${t}" for t in PRICE_TICKS], showgrid=True,
               gridcolor="#e1e0d9", title="regular price (USD, log scale)")
    if axis == "x":
        fig.update_xaxes(**upd)
    else:
        fig.update_yaxes(**upd)
    return fig


# ================================================================== data
@st.cache_data
def load_data():
    variants, models = load_clean()
    first = variants.groupby("model_key").agg(product_url=("product_url", "first"),
                                              composition=("composition_raw", "first"),
                                              origin_raw=("origin_raw", "first"))
    models = models.join(first)
    _, variants_raw, _ = load_merged()
    return models.reset_index(), variants, variants_raw


models, variants, variants_raw = load_data()

# ================================================================== sidebar filters
st.sidebar.title("Filters")
sel_brands = st.sidebar.multiselect("Brands", BRAND_ORDER, default=BRAND_ORDER)
sel_cats = st.sidebar.multiselect("Category", ["sweater", "cardigan"], default=["sweater", "cardigan"])
pmin, pmax = float(models["price_regular"].min()), float(models["price_regular"].max())
sel_price = st.sidebar.slider("Regular price (USD)", 0.0, float(np.ceil(pmax / 10) * 10), (0.0, float(np.ceil(pmax / 10) * 10)),
                              step=5.0)
uniqlo_sep = st.sidebar.toggle("Show UNIQLO as its own segment", value=False,
                               help="UNIQLO is grouped with mid / premium brands but is priced like fast fashion.")
balanced = st.sidebar.toggle("Balanced sample (60 models per brand)", value=False,
                             help="Draw 60 random models from every brand so that large brands (H&M, Mango, Zara) "
                                  "do not dominate pooled numbers.")
seed = st.sidebar.number_input("Random seed", 0, 999, 0, disabled=not balanced)
exclude_capes = st.sidebar.checkbox("Exclude capes (7 models)", value=False)

df = models[models["brand"].isin(sel_brands) & models["category"].isin(sel_cats)
            & models["price_regular"].between(*sel_price)].copy()
if exclude_capes:
    df = df[~df["is_cape"].astype(bool)]
if balanced:
    df = A.balanced_subsample(df, n=60, seed=int(seed))
df["segment"] = np.where(uniqlo_sep & (df["brand"] == "UNIQLO"), "UNIQLO", df["segment"])
brands_in = [b for b in BRAND_ORDER if b in df["brand"].unique()]
brands_by_price = df.groupby("brand")["price_regular"].median().sort_values(kind="stable").index.tolist()

st.sidebar.markdown("---")
st.sidebar.caption(f"**{len(df):,} models** shown (of {len(models):,}).  \n"
                   "Data: US online stores, 22–27 October 2026. Unit = one product model (all its colours).")

if df.empty:
    st.warning("No model matches the filters.")
    st.stop()

# ================================================================== header
st.title("Knitwear across fashion segments")
st.markdown("**How are price segment and price related to the fibre composition of women's sweaters and "
            "cardigans, and how much does fast fashion rely on synthetic fibres?**")

tabs = st.tabs(["Overview", "Q1 · Price", "Q2 · Fibre mix", "Q2 · Price and fibre", "Q3 · Names vs. composition",
                "Products"])

# ================================================================== 1. overview
with tabs[0]:
    c = st.columns(5)
    c[0].metric("Models", f"{len(df):,}")
    c[1].metric("Colour variants", f"{variants[variants['model_key'].isin(df['model_key'])].shape[0]:,}")
    c[2].metric("Brands", len(brands_in))
    c[3].metric("Median price", f"${df['price_regular'].median():.0f}")
    c[4].metric("Majority-synthetic models", f"{df['synthetic_majority'].mean() * 100:.0f}%")

    st.subheader("Brands at a glance")
    g = df.groupby("brand")
    shown = g.size().index                       # brands left after the filters
    tab = pd.DataFrame({
        "segment": g["segment"].first(),
        "collection": variants.groupby("brand")["source_mode"].first().reindex(shown)
                              .map({"browser": "automated", "saved_html": "saved pages"}),
        "models": g.size(),
        "median price ($)": g["price_regular"].median(),
        "synthetic (mean %)": g["synthetic_pct"].mean(),
        "animal fibre (mean %)": g["animal_pct"].mean(),
        "100% natural (% of models)": g["all_natural"].mean() * 100,
        "origin stated": g["origin_country_std"].apply(lambda s: f"{s.notna().mean() * 100:.0f}%"),
        "claims field": pd.Series(["yes" if b in SUST_BRANDS else "no" for b in shown], index=shown),
    }).loc[brands_in]
    st.dataframe(tab, width="stretch", column_config={
        "median price ($)": st.column_config.NumberColumn(format="$%.2f"),
        "synthetic (mean %)": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
        "animal fibre (mean %)": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
        "100% natural (% of models)": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
    })

    st.subheader("Where values are missing")
    vr = variants_raw[variants_raw["brand"].isin(brands_in)]
    fields = {
        "composition": vr["cotton_pct"].isna(), "price": vr["price_current"].isna(),
        "original price (sale items)": vr["price_original"].isna().where(vr["on_sale"]),
        "origin country": vr["origin_country"].isna(), "sustainability text": vr["sustainability_raw"].isna(),
        "care text": vr["care_raw"].isna(), "weight (g)": vr["weight_g"].isna(),
    }
    miss = pd.DataFrame({k: s.astype(float).groupby(vr["brand"]).mean() * 100 for k, s in fields.items()}).T[brands_in]
    fig = px.imshow(miss.round(0), text_auto=".0f", color_continuous_scale=SEQ_SCALE, zmin=0, zmax=100,
                    aspect="auto", labels=dict(color="% missing"))
    fig.update_layout(**LAYOUT, height=330, coloraxis_colorbar=dict(title="% of colours<br>missing"))
    st.plotly_chart(fig, width="stretch", key="chart1")
    st.caption("Gaps follow the brand: origin is not shown by H&M, Zara and & Other Stories (UNIQLO only says "
               "\"Imported\"); the sustainability field was not captured for H&M, Mango and COS. Empty cells = no "
               "item of that brand was on sale. These fields are not needed for Q1–Q3.")

# ================================================================== 2. price
with tabs[1]:
    st.markdown("**Q1. How do regular prices differ between brands and segments, and between sweaters and "
                "cardigans?**  Prices are shown on a log scale because a few cashmere items cost 10× the median.")
    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Every model's regular price (black bar = median)**")
        fig = px.strip(df, x="price_regular", y="brand", color="segment", color_discrete_map=SEG_COLOR,
                       category_orders={"brand": brands_by_price[::-1]}, stripmode="overlay",
                       hover_data={"product_name": True, "category": True, "price_regular": ":$.2f",
                                   "segment": False, "brand": False})
        fig.update_traces(marker=dict(size=5, opacity=0.45), jitter=1)
        med = df.groupby("brand")["price_regular"].median()
        fig.add_trace(go.Scatter(x=med[brands_by_price], y=brands_by_price, mode="markers+text",
                                 marker=dict(symbol="line-ns", size=18, line=dict(width=3, color="#0b0b0b")),
                                 text=[f"  ${v:.0f}" for v in med[brands_by_price]], textposition="middle right",
                                 name="median", hoverinfo="skip"))
        fig.update_layout(**LAYOUT, height=480)
        st.plotly_chart(log_price_axis(fig), width="stretch", key="chart2")
    with right:
        h, p, e2 = A.kruskal_eps2(df, "price_regular", "brand") if len(brands_in) > 1 else (np.nan,) * 3
        st.metric("Share of price ranking explained by brand (ε²)", f"{e2:.2f}" if e2 == e2 else "–")
        seg = df.groupby("segment")["price_regular"].describe()[["count", "25%", "50%", "75%"]]
        seg.columns = ["models", "Q1 ($)", "median ($)", "Q3 ($)"]
        st.dataframe(seg.style.format({"models": "{:.0f}", "Q1 ($)": "${:.2f}", "median ($)": "${:.2f}",
                                       "Q3 ($)": "${:.2f}"}), width="stretch")
        st.caption("ε² = Kruskal–Wallis effect size (0 = brand says nothing about price, 1 = everything). "
                   "Toggle *UNIQLO as its own segment* to see how much it pulls the mid / premium median down.")

    st.markdown("**Sweaters vs. cardigans within each brand**")
    fig = px.box(df, x="price_regular", y="brand", color="category",
                 color_discrete_map={"sweater": CAT[2], "cardigan": CAT[6]},
                 category_orders={"brand": brands_by_price[::-1], "category": ["sweater", "cardigan"]},
                 points=False, hover_data=["product_name"])
    fig.update_layout(**LAYOUT, height=460, boxmode="group")
    st.plotly_chart(log_price_axis(fig), width="stretch", key="chart3")
    if len(brands_in) > 1:
        gap = A.category_gap_by_brand(df, brands_by_price)
        gap = gap.assign(**{"cardigan vs sweater": np.where(gap["p_BH"] < 0.05,
                                                            np.where(gap["delta_cardigan_vs_sweater"] > 0, "dearer", "cheaper"),
                                                            "no clear difference")})
        st.dataframe(gap[["n_sweater", "n_cardigan", "median_sweater", "median_cardigan", "cardigan vs sweater"]]
                     .style.format({"median_sweater": "${:.2f}", "median_cardigan": "${:.2f}"}),
                     width="stretch")

# ================================================================== 3. fibre mix
with tabs[2]:
    st.markdown("**Q2a. What are the garments made of, brand by brand?**")
    mode = st.radio("Heatmap shows", ["mean share of the garment (%)", "models containing the fibre (%)"],
                    horizontal=True)
    cols = [f + "_pct" for f in FIB_ORDER]
    if mode.startswith("mean"):
        heat = df.groupby("brand")[cols].mean()
    else:
        heat = (df[cols] > 0).groupby(df["brand"]).mean() * 100
    heat = heat.loc[brands_in].rename(columns=lambda c: c[:-4])
    fig = px.imshow(heat.round(0), text_auto=".0f", color_continuous_scale=SEQ_SCALE, zmin=0,
                    zmax=60 if mode.startswith("mean") else 100, aspect="auto",
                    labels=dict(x="fibre", y="", color="%"))
    for x in np.cumsum([len(fs) for fs in FIBRE_GROUPS.values()])[:-1] - 0.5:   # group dividers
        fig.add_vline(x=x, line_width=3, line_color="white")
    fig.update_layout(**LAYOUT, height=380)
    fig.update_xaxes(side="top")
    st.plotly_chart(fig, width="stretch", key="chart4")
    st.caption("Fibres are grouped: animal | plant | man-made cellulosic | synthetic. Wool appears in most "
               "fast-fashion brands, but in small amounts next to polyester, acrylic and polyamide.")

    c1, c2 = st.columns(2)
    with c1:
        grp = df.groupby("brand")[list(FIBRE_GROUPS)].mean().loc[brands_by_price[::-1]]
        long = grp.reset_index().melt(id_vars="brand", var_name="group", value_name="share")
        long["group"] = long["group"].map(GROUP_NAME)
        st.markdown("**Fibre groups (mean % of garment)**")
        fig = px.bar(long, x="share", y="brand", color="group", orientation="h",
                     color_discrete_map={GROUP_NAME[k]: v for k, v in GROUP_COLOR.items()},
                     category_orders={"group": list(GROUP_NAME.values())})
        fig.update_traces(marker_line_color="white", marker_line_width=1,
                          hovertemplate="%{y}: %{x:.0f}%<extra>%{fullData.name}</extra>")
        fig.update_layout(**LAYOUT, height=400,
                          xaxis=dict(range=[0, 100], title="%"))
        st.plotly_chart(fig, width="stretch", key="chart5")
    with c2:
        bins = [(-0.1, 0.5, "0%"), (0.5, 49.5, "1–49%"), (49.5, 99.5, "50–99%"), (99.5, 100.1, "100%")]
        sb = A.bin_shares(df, "synthetic_pct", bins, brands_by_price[::-1])
        long = sb.reset_index().melt(id_vars="brand", var_name="synthetic share", value_name="models")
        st.markdown("**How synthetic are the models? (% of models)**")
        fig = px.bar(long, x="models", y="brand", color="synthetic share", orientation="h",
                     color_discrete_sequence=["#d9d8d2", "#86b6ef", "#3987e5", "#184f95"])
        fig.update_traces(marker_line_color="white", marker_line_width=1,
                          hovertemplate="%{y}: %{x:.0f}% of models<extra>synthetic %{fullData.name}</extra>")
        fig.update_layout(**LAYOUT, height=400,
                          xaxis=dict(range=[0, 100], title="% of the brand's models"))
        st.plotly_chart(fig, width="stretch", key="chart6")

    # ---- within-brand (intraclass) variation
    st.markdown("**Variation inside brands: how different are the models of one brand?**  Box = middle 50% "
                "of models, line = median, dots = models.")
    box_cols = list(A.VARIATION_COLS)
    if len(brands_in) > 1:
        part = A.variance_partition(df, box_cols)
        st.caption("Share of the variation that lies **within** brands (1 − η²); the rest is between brands.")
        mc = st.columns(len(box_cols))
        for col_, c in zip(mc, box_cols):
            col_.metric(GROUP_NAME[c],
                        f"{part.loc[c, 'within_share'] * 100:.0f}%",
                        help="1 − η²: the part of the variance that lies between models of the same brand. "
                             f"ICC = {part.loc[c, 'icc1']:.2f}.")
    view = st.radio("Show", ["all brands in one chart", "one brand"], horizontal=True, key="box_view")
    long = df.melt(id_vars=["brand", "product_name"], value_vars=box_cols, var_name="group", value_name="share") \
             .dropna(subset=["share"])
    long["group"] = long["group"].map(GROUP_NAME)
    box_colors = {GROUP_NAME[k]: GROUP_COLOR[k] for k in box_cols}
    if view == "one brand":
        b_sel = st.selectbox("Brand", brands_by_price, key="box_brand")
        long = long[long["brand"] == b_sel]
        fig = px.box(long, x="group", y="share", color="group", points="all", color_discrete_map=box_colors,
                     category_orders={"group": list(box_colors)}, hover_data=["product_name"])
    else:
        fig = px.box(long, x="brand", y="share", color="group", points="all", color_discrete_map=box_colors,
                     category_orders={"brand": brands_by_price, "group": list(box_colors)},
                     hover_data=["product_name"])
        fig.update_layout(boxmode="group")
    fig.update_traces(marker=dict(size=3, opacity=0.35), jitter=0.6, line_width=1)
    fig.update_layout(**LAYOUT, height=460, yaxis=dict(range=[-3, 103], title="% of the garment"),
                      xaxis_title="")
    st.plotly_chart(fig, width="stretch", key="chart_box")
    with st.expander("Table: spread of each fibre group inside each brand"):
        wv = A.within_brand_variation(df, box_cols, brands_by_price)
        wv["fibre_group"] = wv["fibre_group"].map(GROUP_NAME)
        st.dataframe(wv.round(1), width="stretch", hide_index=True)
    st.caption("Fibre shares pile up at 0% and 100%, so many boxes collapse to a line; the dots show where the "
               "models really are. Brand (and segment) explains about 30% of the variation in animal and "
               "synthetic share; the rest is between models of the same brand.")

# ================================================================== 4. price and fibre
with tabs[3]:
    st.markdown("**Q2b. Do dearer brands, and dearer items within a brand, contain more natural (especially "
                "animal) fibre?**")
    measures = {"animal fibre (%)": "animal_pct", "synthetic fibre (%)": "synthetic_pct",
                "natural fibre (%)": "natural_pct", "wool (%)": "wool_pct", "cashmere (%)": "cashmere_pct"}
    c1, c2 = st.columns(2)
    measure_lab = c1.selectbox("Fibre measure", list(measures))
    focus = c2.selectbox("Highlight a brand", ["all brands"] + brands_in)
    y = measures[measure_lab]

    d = df.dropna(subset=[y])
    st.markdown(f"**Price vs {measure_lab}**")
    fig = go.Figure()
    for b in brands_in:
        g = d[d["brand"] == b]
        dim = focus != "all brands" and b != focus
        fig.add_trace(go.Scatter(
            x=g["price_regular"], y=g[y], mode="markers", name=b,
            marker=dict(size=7, color=OTHER_GREY if dim else BRAND_COLOR[b], opacity=0.25 if dim else 0.7,
                        line=dict(width=0.5, color="white")),
            customdata=np.stack([g["product_name"], g["composition"].fillna("")], axis=-1),
            hovertemplate="<b>%{customdata[0]}</b><br>$%{x:.2f} · %{y:.0f}%<br>%{customdata[1]}<extra>" + b + "</extra>"))
    fig.update_layout(**LAYOUT, height=500, yaxis_title=measure_lab)
    st.plotly_chart(log_price_axis(fig), width="stretch", key="chart7")

    c1, c2 = st.columns([3, 2])
    with c1:
        q = df.groupby("brand")["price_regular"].transform(
            lambda x: pd.qcut(x.rank(method="first"), 4, labels=False) + 1 if len(x) >= 4 else np.nan)
        heat = df.assign(q=q).pivot_table(index="brand", columns="q", values=y, aggfunc="mean").reindex(brands_in)
        heat.columns = ["cheapest 25%", "Q2", "Q3", "dearest 25%"][:len(heat.columns)]
        st.markdown(f"**Mean {measure_lab} by price quartile inside each brand**")
        fig = px.imshow(heat.round(0), text_auto=".0f", color_continuous_scale=SEQ_SCALE, zmin=0, zmax=100,
                        aspect="auto", labels=dict(color="%"))
        fig.update_layout(**LAYOUT, height=380)
        st.plotly_chart(fig, width="stretch", key="chart8")
    with c2:
        if len(brands_in) > 0:
            rho = A.within_brand_spearman(df, variables=(y,), brands=brands_in, boot=False)
            rho["direction"] = np.where(rho["p_BH"] < 0.05, np.where(rho["rho"] > 0, "↑ with price", "↓ with price"),
                                        "no clear link")
            st.markdown(f"**Within-brand Spearman ρ** (log price vs {measure_lab})")
            st.dataframe(rho.set_index("brand")[["n", "rho", "direction"]].style.format({"rho": "{:+.2f}"}),
                         width="stretch")
            st.caption("ρ is computed inside each brand, so brand price levels do not drive it. "
                       "Benjamini–Hochberg corrected.")

# ================================================================== 5. names vs composition
with tabs[4]:
    st.markdown("**Q3. Do product names that mention wool, cashmere, mohair, alpaca or merino reflect the actual "
                "composition?**  Each dot is one product whose name mentions the fibre; its position is how much "
                "of that fibre the garment really contains.")
    c1, c2, c3 = st.columns(3)
    fibre_sel = c1.multiselect("Fibre named in the product name", list(NAMED_FIBRES), default=list(NAMED_FIBRES))
    threshold = c2.slider("Flag when the named fibre is below (%)", 10, 90, 50, step=5)
    no_blend = c3.checkbox("Only names without 'blend' / 'mix'", value=False)

    men = A.named_fibre_mentions(df)
    men = men[men["named_fibre"].isin(fibre_sel)]
    if no_blend:
        men = men[~men["blend_in_name"]]
    if men.empty:
        st.info("No product name matches.")
    else:
        men = men.merge(df[["model_key", "price_regular", "synthetic_pct", "composition", "product_url"]],
                        on="model_key", how="left")
        low = men["named_pct"] < threshold
        k = st.columns(4)
        k[0].metric("Fibre mentions", f"{len(men):,}")
        k[1].metric(f"Named fibre < {threshold}%", f"{low.mean() * 100:.0f}%")
        k[2].metric("…of which say 'blend' / 'mix'", f"{men.loc[low, 'blend_in_name'].mean() * 100:.0f}%" if low.any() else "–")
        k[3].metric("Named models with < 30% animal fibre",
                    f"{(df.loc[df['name_premium_fibre'], 'animal_pct'] < 30).sum()}")

        men["wording"] = np.where(men["blend_in_name"], "'blend' / 'mix' in name", "no blend wording")
        st.markdown("**How much of the named fibre is really in the garment?**")
        fig = px.strip(men, x="named_pct", y="named_fibre", color="wording",
                       color_discrete_map={"no blend wording": CAT[6], "'blend' / 'mix' in name": CAT[1]},
                       category_orders={"named_fibre": list(NAMED_FIBRES)}, stripmode="overlay",
                       hover_data={"product_name": True, "brand": True, "named_pct": ":.0f",
                                   "synthetic_pct": ":.0f", "wording": False, "named_fibre": False})
        fig.update_traces(marker=dict(size=7, opacity=0.6), jitter=1)
        fig.add_vline(x=threshold, line_dash="dash", line_color=INK2,
                      annotation_text=f"{threshold}%", annotation_position="top")
        fig.update_layout(**LAYOUT, height=420, xaxis=dict(range=[-3, 103], title="share of the named fibre (%)"),
                          yaxis_title="name says")
        st.plotly_chart(fig, width="stretch", key="chart9")

        st.markdown(f"**Products whose named fibre is below {threshold}%**")
        flagged = men[low].sort_values("named_pct")[["brand", "product_name", "named_fibre", "named_pct",
                                                    "synthetic_pct", "price_regular", "composition", "product_url"]]
        st.dataframe(flagged, width="stretch", hide_index=True, column_config={
            "named_pct": st.column_config.NumberColumn("named fibre %", format="%.0f"),
            "synthetic_pct": st.column_config.NumberColumn("synthetic %", format="%.0f"),
            "price_regular": st.column_config.NumberColumn("price", format="$%.2f"),
            "product_url": st.column_config.LinkColumn("page", display_text="open")})

    st.markdown("**The other direction: animal fibre that the name does not mention**")
    tmp = df.dropna(subset=["animal_pct"]).copy()
    tmp["name"] = np.where(tmp["name_premium_fibre"], "name mentions an animal fibre", "name does not")
    tmp["animal bin"] = pd.cut(tmp["animal_pct"], [-0.1, 0.5, 9.99, 49.5, 99.5, 100.1],
                               labels=["0%", "1–9% (token)", "10–49%", "50–99%", "100%"])
    ct = pd.crosstab([tmp["segment"], tmp["name"]], tmp["animal bin"], normalize="index") * 100
    ct.index = [f"{a} · {b}" for a, b in ct.index]
    fig = px.imshow(ct.round(0), text_auto=".0f", color_continuous_scale=SEQ_SCALE, zmin=0, zmax=100, aspect="auto",
                    labels=dict(x="animal-fibre share of the garment", y="", color="% of row"))
    fig.update_layout(**LAYOUT, height=320)
    st.plotly_chart(fig, width="stretch", key="chart10")

# ================================================================== 6. product table
with tabs[5]:
    q = st.text_input("Search product names", placeholder="e.g. wool, cashmere, cable-knit")
    show = df if not q else df[df["product_name"].str.contains(q, case=False, na=False)]
    cols = ["brand", "segment", "category", "product_name", "price_regular", "any_on_sale", "animal_pct",
            "synthetic_pct", "dominant_fiber", "composition", "origin_country_std", "n_colours", "product_url"]
    st.caption(f"{len(show):,} models")
    st.dataframe(show[cols].sort_values(["brand", "price_regular"]), width="stretch", hide_index=True,
                 height=560, column_config={
                     "price_regular": st.column_config.NumberColumn("price", format="$%.2f"),
                     "animal_pct": st.column_config.ProgressColumn("animal %", format="%.0f", min_value=0, max_value=100),
                     "synthetic_pct": st.column_config.ProgressColumn("synthetic %", format="%.0f", min_value=0, max_value=100),
                     "product_url": st.column_config.LinkColumn("page", display_text="open")})
    st.download_button("Download these rows (CSV)", show[cols].to_csv(index=False).encode("utf-8"),
                       file_name="knitwear_filtered.csv", mime="text/csv")
