# Koji Validation Corpus

A public, versioned corpus of real-world and synthetic documents with ground-truth extraction outputs. Used to validate [Koji](https://github.com/getkoji/koji) extraction accuracy, benchmark model performance, and catch regressions in CI.

## Current coverage

| Category | Documents | Real | Synthetic | Accuracy | Notes |
|----------|-----------|------|-----------|----------|-------|
| **sec_filings** | 101 | 101 | 0 | **~100%** | EDGAR 10-K/10-Q/8-K/DEF 14A/S-1/20-F/6-K + amendments. 50-doc held-out validation set (99.4% cold). |
| **invoices** | 107 | 52 | 55 | **90.4%** | 52 SROIE scanned receipts (real OCR) + 55 synthetic with full schema coverage. |
| **insurance_certificates** | 61 | 21 | 40 | **94.8%** | Real COIs from .gov/.edu + 40 synthetic targeting 6 pain points (carrier letter-codes, per-policy AIs, complex limits, layout variations). |
| **insurance_policies** | 97 | 30 | 67 | **95.3%** | Policy dec pages, endorsements, binders. Real: state DOIs, municipal board packets, Cameron County TX. Synthetic: all 9 policy types. |
| **insurance_claims** | 142 | 17 | 125 | **75.0%** | FEMA proof-of-loss, WC FROI from 11 states, Cameron County loss runs. Synthetic: filled-in claims, loss runs, demand letters. Active tuning. |
| **adversarial** | 11 | 0 | 11 | **~93%** | Blank docs, OCR noise, wrong-schema, stapled packets, multi-doc unions. |
| **multi_format** | 3 | 3 | 0 | **100%** | xlsx, docx, pptx parsed through docling. |
| **TOTAL** | **522** | **224** | **298** | | **4 domains, 7 categories** |

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
├── sec_filings/           # 101 real EDGAR filings
├── invoices/              # 52 SROIE + 55 synthetic
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
