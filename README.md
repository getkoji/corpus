# Koji Validation Corpus

A public, versioned corpus of real-world and synthetic documents with ground-truth extraction outputs. Used to validate [Koji](https://github.com/getkoji/koji) extraction accuracy, benchmark model performance, and catch regressions in CI.

> **New layout in progress (PB-0):** the corpus is migrating to a **doc-bundle**
> layout (`<category>/docs/<doc-id>/{source, truth.json, parsed/, meta.json}`)
> that makes the source document first-class and treats each parse as a cached
> `source × provider × representation` artifact — the foundation for the
> parse-provider evaluation harness. See
> [`docs/bundle-layout.md`](docs/bundle-layout.md). A representative sample is
> migrated; the legacy per-category `documents/`/`expected/`/`manifests/`
> layout below is unchanged and still authoritative until cutover.

## Current coverage

| Category | Documents | Real | Synthetic | Accuracy | Notes |
|----------|-----------|------|-----------|----------|-------|
| **irs_forms** | 20 | 0 | 20 | **100.0%** | IRS 1099-NEC forms with structured fields. |
| **multi_format** | 3 | 3 | 0 | **100.0%** | xlsx, docx, pptx parsed through docling. |
| **insurance_policies** | 97 | 17 | 80 | **99.2%** | Policy dec pages, endorsements, binders. Real: state DOIs, municipal board packets. |
| **sec_filings** | 288 | 288 | 0 | **98.3%** | EDGAR 10-K/10-Q/8-K/DEF 14A/S-1/20-F/6-K + amendments. |
| **medical_records** | 100 | 100 | 0 | **97.7%** | MTSamples transcriptions (CC0). 15 medical specialties. |
| **adversarial** | 11 | 0 | 11 | **96.7%** | Blank docs, OCR noise, wrong-schema, stapled packets, multi-doc unions. |
| **legal_filings** | 61 | 61 | 0 | **96.3%** | Court opinions from CourtListener (Caselaw Access Project). CC0 license. |
| **insurance_claims** | 152 | 22 | 130 | **95.7%** | FEMA proof-of-loss, WC FROI from 11 states, loss runs. |
| **invoices** | 155 | 5 | 150 | **94.9%** | Synthetic invoices with full schema coverage (line items, tax, currency). |
| **contracts** | 100 | 100 | 0 | **90.8%** | Material contracts from SEC EDGAR 8-K Exhibit 10 filings. Public domain. |
| **insurance_certificates** | 61 | 21 | 40 | **90.2%** | Real COIs from .gov/.edu + 40 synthetic targeting 6 pain points. |
| **receipts** | 52 | 52 | 0 | **81.0%** | SROIE scanned receipts (real OCR). Accuracy limited by source scan quality. |
| **TOTAL** | **1,100** | **669** | **431** | **96.1%** | **8 domains, 12 categories** |

Accuracy dashboard coming at `accuracy.getkoji.dev`.

## Why this exists

Document extraction tools make accuracy claims that are impossible to verify. This corpus makes them verifiable:

- **Benchmarking** — `koji bench --corpus . --model openai/gpt-4o-mini` gives an honest per-category accuracy score
- **Multi-domain coverage** — 7 domains (insurance, finance, legal, tax, retail, adversarial, multi-format) with 11 categories
- **Pain-point testing** — insurance COIs have targeted synthetic docs for each known extraction failure mode
- **Regression testing** — every engine change is benched against the full corpus before merging

## Structure

```
corpus/
├── sec_filings/           # 288 real EDGAR filings (10-K, 10-Q, 8-K, DEF 14A, S-1, 20-F, 6-K)
├── insurance_claims/      # 152 (22 real + 130 synthetic)
├── invoices/              # 155 (5 real + 150 synthetic)
├── contracts/             # 100 real EDGAR 8-K material contracts
├── medical_records/       # 100 real MTSamples transcriptions (CC0, 15 specialties)
├── insurance_policies/    # 97 (17 real + 80 synthetic)
├── legal_filings/         # 61 real court opinions (CourtListener)
├── insurance_certificates/ # 61 (21 real + 40 synthetic)
├── receipts/              # 52 real SROIE scanned receipts
├── irs_forms/             # 20 synthetic IRS 1099-NEC
├── adversarial/           # 11 synthetic edge cases
├── multi_format/          # 3 real (xlsx/docx/pptx)
└── scripts/sources/       # Sourcing scripts (EDGAR, CourtListener, SROIE)
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
