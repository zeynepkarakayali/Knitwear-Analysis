"""Write every figure to reports/figures/.

    python -m src.make_figures                 # all figures
    python -m src.make_figures fig7 fig12      # only figures whose name starts with these prefixes
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .cleaning import load_clean, load_merged
from .figures import ALL_FIGURES
from .paths import FIGURES, ensure_dirs


def main(prefixes):
    ensure_dirs()
    _, m = load_clean()
    variants_raw = None
    for name, (func, needs_raw) in ALL_FIGURES.items():
        if prefixes and not any(name.startswith(p) for p in prefixes):
            continue
        if needs_raw and variants_raw is None:
            _, variants_raw, _ = load_merged()
        fig = func(m, variants_raw)
        fig.savefig(FIGURES / f"{name}.png", dpi=300 if name.startswith("fig0") else 200)
        plt.close(fig)
        print("saved", name)


if __name__ == "__main__":
    main(sys.argv[1:])
