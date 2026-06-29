# Corpus doc-bundle layout (PB-0)

> Status: **introduced 2026-06-28 (accuracy-31 / PB-0).** Applied to a
> representative sample; the rest of the corpus migrates incrementally with
> `scripts/migrate_to_bundles.py`. The legacy layout still exists and the
> legacy scorer (`scripts/score.py`) still reads it — migration is **additive
> and lossless**, nothing is deleted.

## Why this layout exists

The corpus drives a **parse-provider evaluation harness** (PB-3). Parse
providers consume the *original source document* (PDF/image/office file) and
produce a parsed representation (markdown today; structured JSON tomorrow). To
score many providers fairly we have to anchor on the representation-independent
things and treat every parse as a derived, cached artifact.

The legacy layout anchored on **markdown** (`<category>/documents/<id>.md`),
which is itself a docling output — i.e. it baked one provider's parse in as if
it were the source. The bundle layout re-anchors on:

1. **The source document** — the immutable input every provider consumes.
2. **The field-value ground truth** — the right answer, independent of parse.

Parsed representations become a **matrix** of `source × provider ×
representation`, each tagged with *how it was produced* so drift is detectable.

This is the structure required by the parse-strategy design intent
(`playbook/docs/parse-strategy.md` → "Evaluation harness — the corpus as a
matrix").

## Layout

A **bundle** is one self-contained directory per document, grouped under its
category (category grouping is preserved so scores can be sliced by domain):

```
<category>/docs/<doc-id>/
├── meta.json                      # quality tag + source provenance +
│                                  #   representation matrix + schema ref
├── truth.json                     # field-value ground truth (the answer)
├── source.<ext>                   # original source bytes, IF available
└── parsed/
    ├── docling-markdown.md        # cached parse (frozen academic md snapshot)
    ├── docling-markdown.meta.json # how it was produced (drift metadata)
    ├── mistral-markdown.md        # (future) another provider's parse
    ├── mistral-markdown.meta.json
    ├── google-docai-json.json     # (future) structured representation
    └── google-docai-json.meta.json
```

Representations are named `<provider>-<representation>` (`docling-markdown`,
`mistral-markdown`, `google-docai-json`, `azure-di-markdown`, ...). Each parse
file gets a sidecar `*.meta.json` recording provider, version, parse config,
date, and sha256.

### Why nested under the category (not a flat top-level `docs/`)

The harness slices provider scores by **document quality** and by **domain**.
Domain is the category. Keeping bundles under `<category>/docs/` preserves that
grouping for free, parallels the existing `documents/`/`expected/` dirs, and
lets the migration run category-by-category. Doc-ids are unique within a
category (the same convention the legacy layout already relies on).

## `meta.json` schema (`doc-bundle/v1`)

```jsonc
{
  "doc_id": "sroie_000",
  "category": "receipts",
  "doc_type": null,                 // from legacy manifest, if any
  "synthetic": false,
  "anomaly": false,

  "quality": "scan",                // digital | scan | fax | mixed
  "quality_reviewed": true,         // false => tag was inferred, needs review
  "quality_notes": "Real scanned receipt (SROIE JPEG).",

  "schema": "receipts/schemas/invoice_basic.yaml",

  "source": {
    "file": null,                   // "source.<ext>" when bytes are present
    "format": "jpg",
    "sha256": null,                 // set when bytes are present
    "retrieved": false,             // are the actual source bytes in the repo?
    "name": "SROIE Dataset (ICDAR 2019)",
    "url": "https://rrc.cvc.uab.es/?ch=13",
    "original_image": "000.jpg",
    "pages": 1,
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "attribution": "ICDAR 2019 Robust Reading Challenge on SROIE"
  },

  "truth": {
    "file": "truth.json",
    "anchored_to": "source.name",   // "source.sha256" when bytes are present
    "source_sha256": null
  },

  "representations": [
    {
      "file": "parsed/docling-markdown.md",
      "provider": "docling",
      "provider_version": "unknown (pre-PB-0; legacy docling parse)",
      "representation": "markdown",
      "produced": "2026-04-12",
      "sha256": "9102b7c8...",
      "frozen_for": ["academic-md-snapshot-v1"]
    }
  ],

  "provenance": {
    "added_date": "2026-04-12",
    "added_by": "corpus-bootstrap",
    "migrated_by": "accuracy-31",
    "migrated_from": { "document": "...", "expected": "...", "manifest": "..." }
  },

  "schema_version": "doc-bundle/v1"
}
```

### Quality tags

`digital` · `scan` · `fax` · `mixed`. These let provider scores be sliced by
input quality so we measure the real-world distribution (clean PDFs →
degraded scans), not just pretty PDFs. `quality_reviewed: false` means the tag
was **inferred** by the migration heuristic and a human still needs to confirm
it. The curated PB-0 sample is all `quality_reviewed: true`.

### Source bytes: present vs. referenced

`source.retrieved` is the honest flag. When the original bytes are in the repo,
`source.file`/`source.sha256` are set and ground truth is versioned against
that hash (`truth.anchored_to: "source.sha256"`). When the bytes are not yet
available (link rot, registration-gated datasets), `retrieved` is `false` and
the bundle carries enough provenance (`url`/`name`/`original_image`) for a
later fetch pass. **The migration does not fabricate or guess source bytes.**

> Finding from migration: several legacy `source_url`s have rotted (e.g. the
> Arizona COI gov URL now returns HTML, not the PDF). This is *exactly* why
> source-first-class matters — and why we should store source bytes in the
> repo (or R2) rather than relying on external URLs.

### The frozen academic markdown snapshot

The existing docling markdown is preserved verbatim as the
`docling-markdown` representation and tagged `frozen_for:
["academic-md-snapshot-v1"]`. This is the "freeze a markdown snapshot for
reproducibility" requirement: papers that hold parse constant read this
representation. Because it is byte-identical to the legacy
`documents/<id>.md` (verified by sha256), no academic baseline is lost. To
make the freeze a hard guarantee, tag the corpus repo
`academic-md-snapshot-v1` at the migration commit (out of band — this PR does
not tag).

## Tooling

| Script | Purpose |
|---|---|
| `scripts/migrate_to_bundles.py` | Build bundles from the legacy layout. Idempotent, additive, never deletes legacy files. |
| `scripts/validate_bundles.py`   | Assert every bundle is harness-readable (source/truth/quality/representations present + sha256 integrity). Exits non-zero on any problem → CI gate. |

```bash
# migrate the curated PB-0 sample (spans digital/scan/fax/mixed)
python scripts/migrate_to_bundles.py --sample

# migrate one doc / one whole category (quality inferred + flagged)
python scripts/migrate_to_bundles.py --category receipts --doc sroie_000
python scripts/migrate_to_bundles.py --category invoices --all

# validate
python scripts/validate_bundles.py            # all bundles
python scripts/validate_bundles.py receipts   # one category
```

## What was migrated in PB-0 (the sample)

Eight docs, one per axis we care about, all `quality_reviewed: true`:

| Bundle | Quality | Source bytes | Why it's in the sample |
|---|---|---|---|
| `multi_format/docs/meridian_invoice_xlsx` | digital | **yes** (`.xlsx`) | proves source-first-class end-to-end with real bytes |
| `insurance_certificates/docs/arizona_coi` | digital | no (url dead) | real born-digital PDF; demonstrates link rot → `retrieved:false` |
| `receipts/docs/sroie_000` | **scan** | no (gated) | real OCR'd receipt; the scan tier |
| `adversarial/docs/anomaly_ocr_typos` | **fax** | no (synthetic) | degraded/low-DPI tier |
| `adversarial/docs/anomaly_three_doc_packet` | **mixed** | no (synthetic) | multi-doc packet tier |
| `irs_forms/docs/synthetic_1099nec_001` | digital | no (synthetic) | clean structured form |
| `sec_filings/docs/edgar_10k_001` | digital | no | real EDGAR text filing |
| `medical_records/docs/mts-001-...-discharge-summary` | digital | no | real transcription text |

## Migrating the rest

1. Per category: `python scripts/migrate_to_bundles.py --category <cat> --all`.
   Quality is inferred from the legacy manifest (`original_format`,
   `original_image`, `anomaly`) and written with `quality_reviewed: false`.
2. **Review every inferred quality tag**, flip `quality_reviewed: true`. This is
   the one step that genuinely needs human eyes (the manifest's `original_format`
   is a weak signal — a "PDF" can be a scan).
3. Backfill source bytes where obtainable: re-fetch live URLs, pull
   registration-gated datasets into R2, regenerate synthetic sources from their
   generator scripts. Set `source.file`/`sha256`/`retrieved: true`.
4. `python scripts/validate_bundles.py` must pass.
5. Once the harness (PB-3) and a bundle-aware scorer read bundles for a
   category, the legacy `documents/`/`expected/`/`manifests/` dirs for that
   category can be retired in a *separate* PR (not before — keep it lossless).

## Open questions (for review)

- **Where do source bytes live** for large/binary corpora — in-repo (simple,
  but bloats git) vs. R2 with a pointer + sha256 in `meta.json` (the legacy
  `r2_url` field hints this was always the plan)? PB-0 stores the one small
  `.xlsx` in-repo; a policy decision is needed before bulk backfill.
- **Schemas stay shared** at `<category>/schemas/` (referenced by path from
  `meta.json`), not copied per bundle. Confirm that's the desired seam.
- **Scorer cutover**: `scripts/score.py` still reads the legacy layout. PB-3
  (the parse-eval harness, `scripts/parse_eval_harness.py`) reads bundles —
  see [`parse-eval-harness.md`](./parse-eval-harness.md). The two coexist until
  the corpus fully migrates to bundles.
