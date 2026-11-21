"""Chart style shared by the notebook, the dashboard and the report figures."""
import matplotlib as mpl
from matplotlib.colors import LinearSegmentedColormap

INK, INK2, MUTED, GRID, BASE, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
# validated categorical palette (fixed order)
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER_GREY = "#b5b3ad"

SEQ = LinearSegmentedColormap.from_list(
    "seq_blue", ["#f3f7fc", "#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"])
DIV = LinearSegmentedColormap.from_list(
    "div_blue_red", ["#184f95", "#3987e5", "#9ec5f4", "#f0efec", "#f2a7a6", "#e34948", "#a32f2e"])
SEQ.set_bad(SURFACE)
DIV.set_bad(SURFACE)

SEG_COLOR = {"Fast fashion": CAT[0], "Mid/premium": CAT[1]}
GROUP_COLOR = {"animal_pct": CAT[0], "plant_pct": CAT[2], "cellulosic_pct": CAT[6],
               "synthetic_pct": CAT[1], "other_group_pct": OTHER_GREY}
GROUP_LABEL = {"animal_pct": "Animal (wool, cashmere, mohair, alpaca, silk, yak/camel)", "plant_pct": "Plant (cotton, linen)",
               "cellulosic_pct": "Man-made cellulosic (viscose, lyocell, modal, acetate)",
               "synthetic_pct": "Synthetic (polyester, acrylic, polyamide, elastane)", "other_group_pct": "Other"}
GROUP_SHORT = {"animal_pct": "animal", "plant_pct": "plant", "cellulosic_pct": "cellulosic",
               "synthetic_pct": "synthetic", "other_group_pct": "other"}

PRICE_TICKS = [10, 20, 50, 100, 200, 500]


def apply_style():
    mpl.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": BASE, "axes.labelcolor": INK2, "axes.titlecolor": INK, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False,
        "font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "legend.frameon": False, "savefig.dpi": 200, "savefig.bbox": "tight",
    })


def price_axis(ax):
    ax.set_xscale("log")
    ax.minorticks_off()
    ax.set_xticks(PRICE_TICKS, [f"${t}" for t in PRICE_TICKS])


def annotate_heatmap(ax, values, fmt, vmax, light_above=0.55):
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            val = values[i, j]
            if val != val:   # NaN
                continue
            ax.text(j, i, fmt(val), ha="center", va="center", fontsize=7.5,
                    color="#ffffff" if val > light_above * vmax else INK2)


def clean_heatmap_axes(ax):
    ax.grid(False)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)


def colorbar(fig, im, ax, label, **kw):
    cb = fig.colorbar(im, ax=ax, **({"fraction": 0.03, "pad": 0.02} | kw))
    cb.set_label(label, color=INK2)
    cb.outline.set_visible(False)
    return cb
