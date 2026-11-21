# Knitwear Across Fashion Segments — Code and Folder Guide

This project collects women's sweaters and cardigans from the US online stores of 8 brands
(Zara, Mango, H&M, Bershka, UNIQLO, COS, Massimo Dutti, & Other Stories) — price, fibre
composition, country of production and sustainability claims — and merges them into three
linked tables. The data were collected on 22–27 October 2026 (prices in USD).
Course project, DALAS (Sorbonne Université).

**Main question.** How are price segment and price related to the fibre composition of women's knitwear, and how
much does fast fashion rely on synthetic fibres compared with mid / premium brands?

- **Q1** How do regular prices differ between brands and segments, and between sweaters and cardigans?
- **Q2** Do more expensive brands, and more expensive items within a brand, contain more natural (especially
  animal) fibre? How dependent is fast fashion on synthetics?
- **Q3** Do product names that mention wool, cashmere, mohair, alpaca or merino reflect the actual composition?

Segments: fast fashion = Zara, Mango, H&M, Bershka; mid / premium = UNIQLO, COS, & Other Stories, Massimo Dutti.

---

## 1. Files

### Data collection (`scrapers/`)

| File | Purpose |
|---|---|
| `common.py` | Shared helpers for all brands: fibre parsing, sweater/cardigan classification, block detection, saving, project paths (`ROOT`, `RAW`, `MERGED`) |
| `collect_links.py` | Collects product (and colour) links from a category page → `urls.txt` |
| `process_products.py` | Opens and parses product pages (live mode) or processes saved HTML files (`--html`) |
| `merge_products.py` | Merges every brand's `products.csv` → `models.csv`, `variants.csv`, `fibres.csv` |
| `zara.py`, `mango.py`, `hm.py`, `shein.py`, `uniqlo.py`, `cos.py`, `massimodutti.py`, `stories.py`, `bershka.py` | Brand-specific URLs and parsers |

**Brand names (`--brand`):** `zara`, `mango`, `hm`, `shein`, `uniqlo`, `cos`, `massimodutti`, `stories`, `bershka`.
& Other Stories is `stories` (not `otherstories`).

### Analysis (`src/`)

| File | Purpose |
|---|---|
| `paths.py` | All analysis folder paths, built from the file location |
| `config.py` | Fibre lists, fibre groups, brand segments and orders |
| `cleaning.py` | Scope filter, composition re-parsing, prices, origin, claims, model-level aggregation |
| `build_dataset.py` | Command line: `data/merged/` → `data/clean/` |
| `analysis.py` | Tests and effect sizes (Cliff's δ, Kruskal–Wallis ε², within-brand Spearman, price model, balanced subsamples) |
| `style.py` | Shared chart style and colours |
| `figures.py` | One function per figure; each returns a matplotlib `Figure` (used by notebooks, dashboard and report) |
| `make_figures.py` | Command line: writes every figure to `reports/figures/` |
| `robustness.py` | Command line: headline results on balanced samples (60 models per brand) |

### Dashboard and environment

| File | Purpose |
|---|---|
| `dashboard/app.py` | Streamlit dashboard (Deliverable 2) |
| `.streamlit/config.toml` | Dashboard theme |
| `environment.yml`, `requirements.txt` | Environment setup |

---

## 2. Setup

```bash
conda env create -f environment.yml
conda activate zara
python -m playwright install chromium        # only needed to run the scrapers
pip install streamlit plotly statsmodels     # if not already in environment.yml
```

Without conda: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.

---

## 3. Folder layout

```
FASHION_PROJECT/
├── scrapers/                      # data collection (.py files)
├── src/                           # cleaning, analysis and figure functions
├── dashboard/
│   └── app.py                     # Streamlit dashboard
├── data/
│   ├── raw/
│   │   ├── zara/      links/  products/  saved/
│   │   ├── stories/   links/  products/  saved/
│   │   └── …                      # folder name = --brand name
│   ├── merged/                    # models.csv, variants.csv, fibres.csv
│   └── clean/                     # models_clean.csv, variants_clean.csv
├── notebooks/
│   └── 01_descriptive_analysis.ipynb
├── reports/
│   ├── figures/                   # written by src.make_figures
│   ├── tables/                    # written by src.robustness
│   └── deliverable1/              # LaTeX report
├── .streamlit/config.toml
├── environment.yml
├── requirements.txt
├── README.md
└── .gitignore                     # __pycache__/  *.savedSearch  data/raw/
```

**Rules**
- Run commands from the **project root**: `python scrapers/process_products.py …`, `python -m src.build_dataset`.
  Default paths are built from `scrapers/common.py` and `src/paths.py`, so the scrapers find `data/` from any
  folder, but the `python -m src.…` commands need the project root.
- The brand folder under `data/raw/` must be named exactly like the `--brand` value
  (`stories`, not `otherstories`). The merge reads the brand key from this folder name;
  a different name changes the keys in `models.csv` / `variants.csv` and breaks the notebooks.
- Notebooks live in `notebooks/`, so their data paths start one level up:
  `pd.read_csv('../data/merged/models.csv')`, or better, `from src.cleaning import load_clean` (section 7).
- `data/raw/` is not committed to git (scraped pages); `data/merged/` and `data/clean/` are.

---

## 4. Default paths

| Script | Reads / writes by default | Override with |
|---|---|---|
| `collect_links.py` | writes `data/raw/<brand>/links/urls.txt`, `manifest.json` | `--out` |
| `process_products.py` (live) | reads `data/raw/<brand>/links/urls.txt` · writes `data/raw/<brand>/products/` | `--urls`, `--out` |
| `process_products.py --html` | reads the given folder (e.g. `data/raw/<brand>/saved/`) · writes `data/raw/<brand>/products/` | `--html`, `--out` |
| `merge_products.py` | reads `data/raw/*/products/products.csv` · writes `data/merged/` | `--root`, `--out-dir` |
| `src.build_dataset` | reads `data/merged/` · writes `data/clean/` | `--in`, `--out` |
| `src.make_figures` | reads `data/clean/` (+ `data/merged/variants.csv`) · writes `reports/figures/` | figure-name prefixes |
| `src.robustness` | reads `data/clean/` · writes `reports/tables/robustness_balanced.csv` | `--n`, `--reps` |

Contents of `data/raw/<brand>/products/`:
- `records/` → one JSON file per colour (the actual record)
- `excluded/` → out-of-scope products (vests, jackets, …)
- `incomplete_pages/` → pages of incomplete products (for debugging, or re-processing later with `--html`)
- `errors.jsonl` → error log
- `products.csv` → table of everything in `records/` (rewritten on every run)

In the merged tables, `source_csv` is stored relative to the project root
(e.g. `data/raw/bershka/products/products.csv`), so no local path ends up in the repository.

---

## 5. Typical workflow

```bash
# from the project root

# 1) Live brands (Zara, Mango, Massimo Dutti, Bershka)
python scrapers/collect_links.py --brand mango
python scrapers/process_products.py --brand mango --limit 5     # short trial first
python scrapers/process_products.py --brand mango

# 2) Saved pages (H&M, UNIQLO, COS, & Other Stories)
python scrapers/process_products.py --brand hm --html data/raw/hm/saved/

# 3) Merge -> data/merged/
python scrapers/merge_products.py

# 4) Clean -> data/clean/
python -m src.build_dataset

# 5) Figures, robustness table, dashboard
python -m src.make_figures
python -m src.robustness
streamlit run dashboard/app.py
```

- Colours that are already `complete` are skipped on re-runs; only incomplete ones are revisited.
- If a block is detected (403, "Access Denied", captcha) the script stops without retrying.
  Do not insist: save that brand's pages in your own browser and process them with `--html`.
- Different brands can run in parallel in separate terminals; do not run the same brand in parallel.
- To test a change without touching the data, write to a temporary folder:
  `python scrapers/merge_products.py --out-dir /tmp/merge_test`, `python -m src.build_dataset --out /tmp/clean_test`.

---

## 6. Output tables

| File | One row = | Key |
|---|---|---|
| `models.csv` | one model (number of colours, price range, mean fibre %) | `model_key` = `brand:model_id` |
| `variants.csv` | one colour (price, composition, origin, collection time) | `variant_key` = `brand:model_id:colour`, `model_key` |
| `fibres.csv` | one colour × one fibre (long format) | `variant_key`, `model_key` |
| `models_clean.csv` | one in-scope model with regular price, fibre groups and flags | `model_key` |
| `variants_clean.csv` | one in-scope colour with regular price, re-parsed composition, claim flags | `variant_key` |

Use `models.csv` / `models_clean.csv` for brand comparisons (each model counts once) and `variants.csv` for
colour-level differences.

Main cleaning choices (`src/cleaning.py`):
- Unit of analysis: the **model** (all colours of one product); colours are aggregated (median price, mean composition).
- 36 knit tops / T-shirts / polo shirts removed; 7 capes kept and flagged.
- 26 unparsed compositions re-parsed (first section summing to 100%); 20 recovered, 5 models stay missing.
- Regular price = current price, or the crossed-out price for items on sale; discount = 0 when not on sale.
- Origin and sustainability claims are only available for some brands; missing values are not imputed.

---

## 7. Using the analysis code in a notebook

```python
import sys; sys.path.insert(0, "..")          # notebook lives in notebooks/
from src.cleaning import load_clean
from src import figures as F, analysis as A

variants, models = load_clean()
F.fibre_heatmaps(models)                       # shows the figure inline
A.within_brand_spearman(models)                # the table behind it
```

`python -m src.make_figures fig7 fig12` re-draws only the figures whose names start with these prefixes.

---

## 8. Dashboard

```bash
streamlit run dashboard/app.py
```

Tabs: Overview (brands, missing values) · Q1 Price · Q2 Fibre mix · Q2 Price and fibre · Q3 Names vs. composition ·
Products (searchable table with links, CSV download). Sidebar filters: brands, category, price range, *UNIQLO as its
own segment*, *balanced sample (60 models per brand)*, exclude capes.

---

## 9. Robustness: unequal brand sizes

Brands contribute between 63 and 423 models. `python -m src.robustness` recomputes the pooled headline numbers on
200 random samples of 60 models per brand; all conclusions keep the same direction (brand explains even more of the
price ranking: ε² 0.72 vs 0.60).