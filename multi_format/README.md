# Multi-format corpus

Stress-tests the `parse → extract` path on non-markdown source formats.
`koji extract` only consumes markdown; `koji parse` (docling) is what
turns binary office documents, PDFs, and images into the markdown that
extract reads. This category verifies that real-world office formats
survive the round trip and still produce correct extractions.

## Structure

```
multi_format/
├── sources/      # committed binary source files (.docx, .xlsx, .pptx, .pdf)
├── documents/    # parsed markdown, produced by scripts/reparse_multi_format.py
├── expected/     # ground truth JSON per parsed markdown file
├── manifests/    # sidecar metadata (schema reference, source_filename, etc.)
└── schemas/      # empty — manifests reference schemas from other categories
```

The `documents/` markdown files are derived artifacts. Running
`scripts/reparse_multi_format.py` against a live koji cluster
regenerates them from `sources/`. Re-running catches parse-service
regressions (e.g. a docling upgrade changing markdown output).

## Expected-JSON convention

Each source file's content is authored to match a known ground truth,
and the expected JSON asserts exactly those values. The same Meridian
Supply Co. invoice appears in three formats (docx, xlsx, pptx) — all
three expected JSONs are identical, so format-specific failures show
up cleanly as per-doc bench diffs.

## Adding a new format

1. Add a source file under `multi_format/sources/` (e.g. `some_doc.pdf`).
2. Run `python scripts/reparse_multi_format.py` to populate
   `multi_format/documents/some_doc_pdf.md`.
3. Inspect the parsed markdown and write `expected/some_doc_pdf.expected.json`
   with the fields that should be extracted.
4. Add `manifests/some_doc_pdf.json` pointing at the appropriate schema
   from another category (invoices, sec_filings, insurance_certificates,
   etc.). Include `source_filename`, `original_format`, and
   `original_format_mime` in the manifest so downstream tooling can
   look up the binary source if needed.
5. Re-run `koji bench --corpus . --category multi_format`.

The reparse script disambiguates output stems with the source format
(e.g. `meridian_invoice.docx` → `meridian_invoice_docx.md`) so the
same doc in multiple formats doesn't collide.

## Generating synthetic fixtures

`scripts/generate_multi_format_fixtures.py` regenerates the deterministic
source files from a Python payload. Use it to add more test docs or
refresh existing ones after editing the payload:

```bash
uv run --with python-docx --with openpyxl --with python-pptx \
    python scripts/generate_multi_format_fixtures.py
```

## Current coverage

| Format | Doc | Schema | Parse notes |
|---|---|---|---|
| `.docx` | `meridian_invoice_docx.md` | `invoices/schemas/invoice_basic.yaml` | Cleanest output — `#` heading, `**bold**` emphasis, proper line-items table |
| `.xlsx` | `meridian_invoice_xlsx.md` | `invoices/schemas/invoice_basic.yaml` | Every block becomes a markdown table (even single-cell headers). Raw numbers without `$`/comma formatting. No `#` headings |
| `.pptx` | `meridian_invoice_pptx.md` | `invoices/schemas/invoice_basic.yaml` | Slides flatten into reading order. Table preserved. No `#` headings |

## Bench status

18/18 fields = **100.0%** on `openai/gpt-4o-mini` as of 2026-04-14.
All three office formats round-trip through docling + the existing
invoice schema without surfacing any parse, chunk, routing, or
extraction bugs. docling handles the dense-table case (xlsx) without
losing numeric precision.

## Out of scope for this first pass

- **Scanned / image-based PDF** (OCR path). Generating deterministic
  scanned-PDF fixtures is a larger effort than the office trio and
  needs its own task. Filed as a follow-up under accuracy when ready.
- **Domain variety.** Current coverage is invoices only. Expanding to
  COI / policy / SEC filing in each format will happen as more
  format-specific bugs surface.
- **Malformed or corrupt source files.** That's adversarial territory —
  belongs in `corpus/adversarial/` when we add format-breakage cases.

## Running the bench

```bash
koji bench --corpus . --category multi_format --model openai/gpt-4o-mini
```

## Regenerating after source changes

```bash
# Regenerate sources from the Python payload (only if the content
# has been edited in the generator script):
uv run --with python-docx --with openpyxl --with python-pptx \
    python scripts/generate_multi_format_fixtures.py

# Always: re-parse sources through the running cluster:
uv run --with httpx python scripts/reparse_multi_format.py
```
