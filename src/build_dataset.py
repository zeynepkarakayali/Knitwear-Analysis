"""Build the clean tables from the merged scraper output.

    python -m src.build_dataset                  # data/merged -> data/clean
    python -m src.build_dataset --in DIR --out DIR
"""
import argparse
from pathlib import Path

from .cleaning import load_merged, build
from .paths import MERGED, CLEAN


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", type=Path, default=MERGED, help="folder with models/variants/fibres.csv")
    ap.add_argument("--out", dest="dst", type=Path, default=CLEAN, help="folder for the clean CSV files")
    args = ap.parse_args()

    models_raw, variants_raw, fibres_raw = load_merged(args.src)
    print(f"raw:   {len(models_raw):,} models, {len(variants_raw):,} colours, {len(fibres_raw):,} fibre rows")

    v, m = build(models_raw, variants_raw, fibres_raw)
    print(f"clean: {len(m):,} models, {len(v):,} colours "
          f"({len(models_raw) - len(m)} out-of-scope models removed)")
    print("composition status (colours):", v["comp_status"].value_counts().to_dict())
    print("models without composition:", int((~m["has_composition"]).sum()))

    args.dst.mkdir(parents=True, exist_ok=True)
    v.to_csv(args.dst / "variants_clean.csv", index=False)
    m.to_csv(args.dst / "models_clean.csv", index=False)
    print(f"saved to {args.dst}")


if __name__ == "__main__":
    main()
