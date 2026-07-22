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
>
> **Parse-eval harness (PB-3) is live:** `scripts/parse_eval_harness.py` scores
> parse providers end-to-end (field values vs ground truth, extract held
> constant) per `provider × doc-type`. Adding a provider is a one-liner — see
> [`docs/parse-eval-harness.md`](docs/parse-eval-harness.md).

## Current coverage

| Category | Documents | Real | Synthetic | Accuracy | Notes |
|----------|-----------|------|-----------|----------|-------|
| **irs_forms** | 20 | 0 | 20 | **100.0%** | IRS 1099-NEC forms with structured fields. |
| **multi_format** | 3 | 3 | 0 | **100.0%** | xlsx, docx, pptx parsed through docling. |
| **insurance_policies** | 97 | 17 | 80 | **99.2%** | Policy dec pages, endorsements, binders. Real: state DOIs, municipal board packets. |
| **sec_filings** | 288 | 288 | 0 | **98.3%** | EDGAR 10-K/10-Q/8-K/DEF 14A/S-1/20-F/6-K + amendments. |
| **medical_records** | 100 | 100 | 0 | **97.7%** | MTSamples transcriptions. 15 medical specialties. ⚠️ licensing under review |
| **adversarial** | 11 | 0 | 11 | **96.7%** | Blank docs, OCR noise, wrong-schema, stapled packets, multi-doc unions. |
| **legal_filings** | 61 | 61 | 0 | **96.3%** | Court opinions from CourtListener (Caselaw Access Project). CC0 license. |
| **insurance_claims** | 152 | 22 | 130 | **95.7%** | FEMA proof-of-loss, WC FROI from 11 states, loss runs. |
| **invoices** | 155 | 5 | 150 | **94.9%** | Synthetic invoices with full schema coverage (line items, tax, currency). |
| **contracts** | 100 | 100 | 0 | **90.8%** | Material contracts from SEC EDGAR 8-K Exhibit 10 filings. Copyright retained by filer. |
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
├── medical_records/       # 100 real MTSamples transcriptions (15 specialties)
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
| SEC filings | EDGAR full-text search API (public, no auth). Authored by the filing registrant — not a US Government work; see `DATA_LICENSE.md` |
| Receipts | SROIE dataset (ICDAR 2019, CC BY 4.0 — attribution required) |
| Invoices | Synthetic (`scripts/sources/synthetic_invoices.py`) + hand-crafted bootstrap samples |
| Insurance certificates | .gov/.edu (NYC, LA, Cal State, Georgia Tech, 15+ more) + synthetic |
| Insurance policies | State DOIs (OK, FL, DC, MD, NY, NV), municipal board packets (Ketchum, Rocky Mount, Cameron County TX), insurer specimens |
| Insurance claims | FEMA NFIP proof-of-loss, WC FROI from 11 states, Cameron County TX loss runs + synthetic |

## Ground truth

Each document has a `.expected.json`. Only fields with known ground truth are asserted — missing fields are omitted so the bench doesn't penalize correct extractions we didn't annotate.

For authoritative-index sources (EDGAR, SROIE), expected comes from the index. For everything else, expected is seeded via `koji extract` and manually reviewed.

## Contributing

See `CONTRIBUTING.md`. Key rules: public domain or CC-licensed only, expected JSONs require manual review, regressions > 5% must be called out in PR body.

**Where a document was found is not a licence.** Publication on a `.gov`, `.edu`, or
vendor website does not grant redistribution rights. Record the actual terms in the
manifest (`license`, `license_url`, `attribution`, `license_basis`) — and if there are
no explicit terms, say so rather than inferring a permissive one.

## License

- **Code** (`scripts/`, schemas): Apache 2.0 — see `LICENSE`
- **Ground-truth annotations** and **synthetic documents**: CC0
- **Third-party documents**: per-source, mixed terms — see **[`DATA_LICENSE.md`](DATA_LICENSE.md)**

> ⚠️ **A licensing audit (2026-07-22) found unresolved issues** affecting MTSamples,
> ACORD, and ISO/insurer-specimen documents. `DATA_LICENSE.md` lists them. Do not treat
> this corpus as licence-clean until they are closed.
