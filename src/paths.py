"""All project folders in one place.

Paths are built from this file's location, so every script works no matter which folder it is run from.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA = ROOT / "data"
RAW = DATA / "raw"            # per-brand scraper output (JSON / saved pages)
MERGED = DATA / "merged"      # models.csv, variants.csv, fibres.csv written by merge_products.py
CLEAN = DATA / "clean"        # models_clean.csv, variants_clean.csv written by src.build_dataset

REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"


def ensure_dirs():
    for d in (CLEAN, FIGURES):
        d.mkdir(parents=True, exist_ok=True)
