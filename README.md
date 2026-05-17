# Koji Validation Corpus

A public, versioned corpus of real-world and synthetic documents with ground-truth extraction outputs. Used to validate [Koji](https://github.com/getkoji/koji) extraction accuracy, benchmark model performance, and catch regressions in CI.

## Current coverage

| Category | Documents | Real | Synthetic | Accuracy | Notes |
|----------|-----------|------|-----------|----------|-------|
| **sec_filings** | 102 | 102 | 0 | **99.2%** | EDGAR 10-K/10-Q/8-K/DEF 14A/S-1/20-F/6-K + amendments. |
| **invoices** | 155 | 0 | 155 | **95.2%** | Synthetic invoices with full schema coverage (line items, tax, currency). |
| **receipts** | 52 | 52 | 0 | **81.0%** | SROIE scanned receipts (real OCR). Accuracy limited by OCR quality. |
| **insurance_certificates** | 61 | 21 | 40 | **89.2%** | Real COIs from .gov/.edu + 40 synthetic targeting 6 pain points. |
| **insurance_policies** | 97 | 30 | 67 | **95.2%** | Policy dec pages, endorsements, binders. Real: state DOIs, municipal board packets. Synthetic: all 9 policy types. |
| **insurance_claims** | 142 | 17 | 125 | **92.4%** | FEMA proof-of-loss, WC FROI from 11 states, loss runs. Synthetic: filled-in claims, loss runs, demand letters. |
| **adversarial** | 11 | 0 | 11 | **91.7%** | Blank docs, OCR noise, wrong-schema, stapled packets, multi-doc unions. |
| **multi_format** | 3 | 3 | 0 | **100%** | xlsx, docx, pptx parsed through docling. |
| **TOTAL** | **623** | **225** | **398** | **93.5%** | **5 domains, 8 categories** |

Accuracy dashboard coming at `accuracy.getkoji.dev`.

## Why this exists

Document extraction tools make accuracy claims that are impossible to verify. This corpus makes them verifiable:

- **Benchmarking** — `koji bench --corpus . --model openai/gpt-4o-mini` gives an honest per-category accuracy score
- **Held-out validation** — SEC filings has a 50-doc cold set the schemas were never tuned against (99.4%)
- **Pain-point testing** — insurance COIs have targeted synthetic docs for each known extraction failure mode
- **Regression testing** — every engine change is benched against the full corpus before merging

## Structure

```
corpus/
├── sec_filings/           # 102 real EDGAR filings
├── invoices/              # 155 synthetic invoices
├── receipts/              # 52 real SROIE scanned receipts
├── insurance_certificates/ # 21 real + 40 synthetic COIs
├── insurance_policies/    # 30 real + 67 synthetic
├── insurance_claims/      # 17 real + 125 synthetic
├── adversarial/           # 11 synthetic edge cases
├── multi_format/          # 3 real (xlsx/docx/pptx)
└── scripts/sources/       # Sourcing + generation scripts
```

Each category has `documents/`, `schemas/`, `expected/`, and `manifests/` subdirectories.

## Running benchmarks

```bash
# Full corpus
koji bench --corpus . --model openai/gpt-4o-mini

# One category
koji bench --corpus . --category sec_filings

# JSON output for CI
koji bench --corpus . --json --output results.json
```

## Document sources

| Category | Sources |
|----------|---------|
| SEC filings | EDGAR full-text search API (public, no auth) |
| Invoices | SROIE dataset (ICDAR 2019, CC BY 4.0) + synthetic |
| Insurance certificates | .gov/.edu (NYC, LA, Cal State, Georgia Tech, 15+ more) + synthetic |
| Insurance policies | State DOIs (OK, FL, DC, MD, NY, NV), municipal board packets (Ketchum, Rocky Mount, Cameron County TX), insurer specimens |
| Insurance claims | FEMA NFIP proof-of-loss, WC FROI from 11 states, Cameron County TX loss runs + synthetic |

## Ground truth

Each document has a `.expected.json`. Only fields with known ground truth are asserted — missing fields are omitted so the bench doesn't penalize correct extractions we didn't annotate.

For authoritative-index sources (EDGAR, SROIE), expected comes from the index. For everything else, expected is seeded via `koji extract` and manually reviewed.

## Contributing

See `CONTRIBUTING.md`. Key rules: public domain or CC-licensed only, expected JSONs require manual review, regressions > 5% must be called out in PR body.

## License

- **Code** (scripts, schemas): Apache 2.0
- **Documents**: per-document (check manifests). Most are public domain (US Government) or CC BY 4.0. Synthetic documents are CC0.
