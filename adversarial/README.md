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

### Pure-null cases (expected = `{}`)
Expected JSON is empty. Bench trivially passes them at 0/0 fields. **This does
not verify the extractor returned nulls — it only verifies it didn't crash.**
To actually validate null returns, run `scripts/probe_adversarial.py` against
a live cluster; the script hits `/api/extract` for each pure-null doc and
prints any non-null fields the extractor returned (i.e. hallucinations).

The pure-null convention is a placeholder until **oss-23** (comparator null
semantics) lands. Today, `compare_field` in `koji/cli/test_runner.py` treats
`actual=null` as always-failing regardless of what `expected` is, so explicit
`expected: null` assertions would fail every time the extractor does the
right thing. Once oss-23 ships, we'll migrate the pure-null cases from `{}`
to explicit nulls and the bench will catch hallucinations directly.

## Known findings (2026-04-13, gpt-4o-mini)

**Clean (4 of 7 pure-null cases):** the extractor correctly returns all
null on blank, header-only, XBRL-only, and out-of-scope inputs. No
SEC metadata fabricated from empty or unrelated content.

**Hallucinations (3 of 7 pure-null cases):**

- **`anomaly_wrong_schema`**: returns `filer_name: "Zephyr Logistics LLC"`
  (the INSURED party) and `filing_date: "2026-03-15"` (the COI issue date).
  Model maps "insured" to "filer" and grabs a top-of-doc date as the
  filing date. Worst offender — cross-domain confusion.
- **`anomaly_stapled`**: returns a filer_name from one of the two cover
  pages, picked non-deterministically (the specific pick shifts with
  engine version; current: "BETA SERVICES INC."). No form_type returned
  but filer_name leaks.
- **`anomaly_multi_union`**: similar non-deterministic pick across the
  three concatenated filings (current: Delta + 10-Q).

All three are in scope of **oss-28** (configurable classify + split
pipeline stage). None of them can be fixed with schema hints alone —
the extractor needs upstream document classification so that the wrong
schema never gets applied to a whole section, and multi-doc packets
get split before extraction.

### Blocked on oss-25

Pure-null expected JSONs are currently empty `{}`, so the bench trivially
passes them at 0/0 fields. Once **oss-25** (comparator null semantics)
ships, those `{}` files migrate to explicit nulls (one null per schema
field), and the bench will catch the hallucinations above as real test
failures instead of relying on the probe script.

## Running the bench

```bash
koji bench --corpus . --category adversarial --model openai/gpt-4o-mini
```

## Running the hallucination probe

```bash
python scripts/probe_adversarial.py .
```

(Requires a running koji cluster and `OPENAI_API_KEY` in the environment.)
