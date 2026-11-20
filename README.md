# Knitwear Dataset — Code and Folder Guide

This project collects women's sweaters and cardigans from the US online stores of 8 brands
(Zara, Mango, H&M, Bershka, UNIQLO, COS, Massimo Dutti, & Other Stories) — price, fibre
composition, country of production and sustainability claims — and merges them into three
linked tables.

---

## 1. Files

| File | Purpose |
|---|---|
| `common.py` | Shared helpers for all brands: fibre parsing, sweater/cardigan classification, block detection, saving |
| `collect_links.py` | Collects product (and colour) links from a category page → `urls.txt` |
| `process_products.py` | Opens and parses product pages (live mode) or processes saved HTML files (`--html`) |
| `merge_products.py` | Merges every brand's `products.csv` → `models.csv`, `variants.csv`, `fibres.csv` |
| `zara.py`, `mango.py`, `hm.py`, `shein.py`, `uniqlo.py`, `cos.py`, `massimodutti.py`, `stories.py`, `bershka.py` | Brand-specific URLs and parsers |
| `environment.yml`, `requirements.txt` | Environment setup |

**Brand names (`--brand`):** `zara`, `mango`, `hm`, `shein`, `uniqlo`, `cos`, `massimodutti`, `stories`, `bershka`.
& Other Stories is `stories` (not `otherstories`).

---

## 2. Setup

```bash
conda env create -f environment.yml
conda activate zara
python -m playwright install chromium
```

---

## 3. Folder layout

```
FASHION_PROJECT/
├── scrapers/                      # all .py files
├── data/
│   ├── raw/
│   │   ├── zara/      links/  products/  saved/
│   │   ├── stories/   links/  products/  saved/
│   │   └── …                      # folder name = --brand name
│   ├── dataset/                   # models.csv, variants.csv, fibres.csv
│   └── clean/                     # models_clean.csv, variants_clean.csv
├── analysis/
│   ├── descriptive_analysis_knitwear.ipynb
│   └── figures/
├── environment.yml
├── requirements.txt
├── README.md
└── .gitignore                     # __pycache__/  *.savedSearch
```

**Rules**
- Always run commands from the **project root**: `python scrapers/process_products.py …`
  (paths are resolved relative to the folder you run from).
- The brand folder under `data/raw/` must be named exactly like the `--brand` value
  (`stories`, not `otherstories`). The merge reads the brand key from this folder name;
  a different name changes the keys in `models.csv` / `variants.csv` and breaks the notebooks.
- Notebooks live in `analysis/`, so their data paths start one level up:
  `pd.read_csv('../data/dataset/models.csv')`.

---

## 4. Default paths

| Script | Reads / writes by default | Override with |
|---|---|---|
| `collect_links.py` | writes `data/raw/<brand>/links/urls.txt`, `manifest.json` | `--out` |
| `process_products.py` (live) | reads `data/raw/<brand>/links/urls.txt` · writes `data/raw/<brand>/products/` | `--urls`, `--out` |
| `process_products.py --html` | reads the given folder (e.g. `data/raw/<brand>/saved/`) · writes `data/raw/<brand>/products/` | `--html`, `--out` |
| `merge_products.py` | reads `data/raw/*/products/products.csv` · writes `data/dataset/` | `--root`, `--out-dir` |

Contents of `data/raw/<brand>/products/`:
- `records/` → one JSON file per colour (the actual record)
- `excluded/` → out-of-scope products (vests, jackets, …)
- `incomplete_pages/` → pages of incomplete products (for debugging, or re-processing later with `--html`)
- `errors.jsonl` → error log
- `products.csv` → table of everything in `records/` (rewritten on every run)

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

# 3) Merge -> data/dataset/
python scrapers/merge_products.py
```

- Colours that are already `complete` are skipped on re-runs; only incomplete ones are revisited.
- If a block is detected (403, "Access Denied", captcha) the script stops without retrying.
  Do not insist: save that brand's pages in your own browser and process them with `--html`.
- Different brands can run in parallel in separate terminals; do not run the same brand in parallel.

---

## 6. Output tables

| File | One row = | Key |
|---|---|---|
| `models.csv` | one model (number of colours, price range, mean fibre %) | `model_key` = `brand:model_id` |
| `variants.csv` | one colour (price, composition, origin, collection time) | `variant_key` = `brand:model_id:colour`, `model_key` |
| `fibres.csv` | one colour × one fibre (long format) | `variant_key`, `model_key` |

Use `models.csv` for brand comparisons (each model counts once) and `variants.csv` for
colour-level differences.