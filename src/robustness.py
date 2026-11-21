"""Robustness check: do the headline results depend on the unequal number of models per brand?

    python3 -m src.robustness              # 200 balanced subsamples of 60 models per brand
    python3 -m src.robustness --n 60 --reps 500

Writes reports/tables/robustness_balanced.csv and prints the table.
"""
import argparse

import pandas as pd

from .analysis import robustness_balanced
from .cleaning import load_clean
from .paths import REPORTS


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=60, help="models per brand")
    ap.add_argument("--reps", type=int, default=200, help="number of balanced subsamples")
    args = ap.parse_args()

    _, m = load_clean()
    print("models per brand:", m["brand"].value_counts().to_dict())
    tab = robustness_balanced(m, n=args.n, reps=args.reps)
    out = REPORTS / "tables"
    out.mkdir(parents=True, exist_ok=True)
    tab.round(3).to_csv(out / "robustness_balanced.csv")
    with pd.option_context("display.width", 160, "display.max_colwidth", 60):
        print(tab.round(2))
    print("saved", out / "robustness_balanced.csv")


if __name__ == "__main__":
    main()
