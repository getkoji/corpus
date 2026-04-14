# Adversarial corpus

Stress tests for extraction failure modes. These documents intentionally
provoke edge cases so we can verify the pipeline degrades gracefully
instead of hallucinating plausible-looking nonsense. Initial cases were
seeded alongside the SEC filing_metadata schema, but the category is
domain-agnostic — adversarial inputs should cover every category Koji
supports over time.

## Test case classes

| Case | What it probes | Positive assertions? |
|---|---|---|
| `anomaly_blank` | Empty input. Extractor should not crash or hallucinate. | None — pure null |
| `anomaly_header_only` | SEC boilerplate header only, no filer or form. | None — pure null |
| `anomaly_xbrl_only` | Pure XBRL inline-taxonomy noise (real, lifted from a production filing). Tests extractor ignores structured-but-non-human content. | None — pure null |
| `anomaly_out_of_scope` | A cooking recipe. Tests extractor recognizes "this isn't the kind of document I was built for." | None — pure null |
| `anomaly_wrong_schema` | A certificate of liability insurance, with the SEC `filing_metadata` schema applied. Tests cross-domain robustness — the single most common real-world adversarial case (users uploading the wrong document for their pipeline). | None — pure null |
| `anomaly_truncated` | Partial SEC cover page cut mid-sentence. Only `form_type` is legitimately present. | `form_type: 10-K` |
| `anomaly_misleading_form` | 8-K cover page with "Form 10-K" mentioned in body prose. Tests the extractor picks the cover-page declaration, not body references. | filer, form_type, filing_date, period_date_of_report |
| `anomaly_ocr_typos` | Realistic OCR character confusions (1/l, 0/O, typos). Tests fuzzy recognition of filer + form type. | filer, form_type |
| `anomaly_stapled` | Two fictional SEC cover pages (10-K + 10-Q) concatenated. | None — pure null |
| `anomaly_multi_union` | Three SEC cover pages (8-K + 10-Q + DEF 14A) concatenated. | None — pure null |

## Expected-JSON convention

### Positive assertion cases
Expected JSON contains the fields the document legitimately has. Bench validates
them the normal way.

### Pure-null cases (expected: explicit nulls)
Each pure-null doc's expected JSON contains every schema field set to
`null`. `compare_field` in `koji/cli/test_runner.py` (since **oss-25**,
PR koji#21) handles these under a four-case matrix:

  1. `expected=None, actual=None` → **pass**, detail `"correctly absent"`
  2. `expected=None, actual=non-None` → **fail**, detail `"hallucinated"`
  3. `expected=non-None, actual=None` → **fail**, detail `"missing"`
  4. Both non-None → normal value comparison

This is how bench directly validates "the model returned null on input
it shouldn't have extracted anything from". A clean pure-null case
passes all 7 field assertions; any field the model hallucinated counts
as a real failure on the bench score, not a probe-script finding.

The earlier `{}` placeholder convention is gone — it was only needed
until oss-25 landed.

## Known findings (2026-04-13, gpt-4o-mini, post oss-25 migration)

**Bench:** 56/60 fields = **93.3%** across 11 adversarial docs.

**Clean (4 of 7 pure-null cases, 28/28 null assertions pass):** the
extractor correctly returns all null on `anomaly_blank`,
`anomaly_header_only`, `anomaly_xbrl_only`, and `anomaly_out_of_scope`.
No SEC metadata fabricated from empty or unrelated content.

**Hallucinations (3 of 7 pure-null cases, 4/21 null assertions fail):**

- **`anomaly_wrong_schema` (5/7 — 2 hallucinations):**
  - `filer_name: "Zephyr Logistics LLC"` — the INSURED party from the COI
  - `filing_date: "2026-03-15"` — the COI's issue date
  Model maps insurance concepts to SEC fields. Worst offender — genuine
  cross-domain confusion.
- **`anomaly_stapled` (6/7 — 1 hallucination):** `filer_name` leaks
  from one of the two concatenated cover pages. Pick is non-deterministic
  across engine versions.
- **`anomaly_multi_union` (6/7 — 1 hallucination):** same pattern on
  the three-form concatenation.

All four hallucinations are in scope of **oss-28** (configurable classify
+ split pipeline stage). None can be fixed with schema hints alone —
the extractor needs upstream document classification so the wrong schema
never gets applied to a whole section, and multi-doc packets get split
before extraction.

Positive-assertion cases (4/4 all passing): `anomaly_truncated` (1/1),
`anomaly_misleading_form` (4/4), `anomaly_ocr_typos` (2/2),
`anomaly_three_doc_packet` (4/4). The three-doc packet passing cleanly
is the notable result — applying the COI schema to an
invoice+COI+policy packet still lands on the COI section correctly.

## Running the bench

```bash
koji bench --corpus . --category adversarial --model openai/gpt-4o-mini
```

## Running the hallucination probe

`scripts/probe_adversarial.py` is kept around as a quick standalone
diagnostic — same hallucination check without needing to run the full
bench. Useful for iterating on a single anomaly doc during debugging.

```bash
python scripts/probe_adversarial.py .
```

(Requires a running koji cluster and `OPENAI_API_KEY` in the environment.)

Since oss-25 landed the null-aware comparator, the probe's findings
are now fully reproducible through `koji bench` — the probe is no
longer a substitute for bench validation, just a faster single-doc
troubleshooter.
