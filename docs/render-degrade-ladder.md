# Render/degrade ladder (BR-0b, Track A)

`docs/composition.md` records the problem: **only 8.9% of this corpus came from a rendered
page.** For the other ~91% the benchmark measures *extraction from clean text*, not
document extraction.

This ladder is the controlled test of what that costs. It takes documents that **already
have ground truth**, renders them into real documents, and degrades them along a fixed
ladder. Ground truth is identical at every level, so any accuracy drop is attributable to
the input becoming a document — nothing else changes.

```
L0  markdown          the current corpus input (control)
 │
L1  native PDF        real page geometry, real text layer
 │
L2  rasterized PDF    same pixels, no text layer — forces OCR
 │
L3  scan-simulated    L2 + skew, sensor noise, speckle, contrast/brightness shift,
                      lossy JPEG recompression
```

## Running it

```bash
python3 scripts/render_degrade.py --category invoices --limit 5
python3 scripts/render_degrade.py --all --out build/ladder --manifest build/ladder.json
```

**613 documents are eligible** (every tier C/D document — the ones that never had a page).
A full run takes ~4 minutes and produces ~670 MB, so output is **generated, not committed**.
`build/` is gitignored.

Output is **byte-for-byte deterministic** for a given `--seed`; `--manifest` records a
SHA-256 per artefact so reproducibility is verifiable rather than asserted. Each document
is seeded from its own ID, so a document's output does not depend on batch composition.

Requires `pymupdf`, `pillow`, `numpy`.

## Verified properties

- **L1 carries a text layer; L2 and L3 do not** — confirmed by extracting text from every
  generated PDF. L2/L3 genuinely force the OCR path rather than merely looking like scans.
- **Determinism** — two independent runs produce identical SHA-256 for all artefacts.
  (PyMuPDF writes a random `/ID` into the PDF trailer on every save; `pin_pdf_id()`
  rewrites it from the content hash, otherwise nothing here would reproduce.)
- **Validity** — every generated PDF reopens and renders after that rewrite.

## What this ladder does and does not isolate

**It isolates:** the input ceasing to be clean text. Layout geometry (L1), loss of the text
layer (L2), and scan artefacts (L3) are separated into distinct, individually attributable
steps.

**It does not isolate — and must not be read as covering:**

- **Layout diversity.** Every document is rendered through *one* plain stylesheet. Real
  forms fail in ways this cannot reproduce: unlabeled bottom-corner boxes, merged-cell
  grids, multi-column bodies, rotated inserts, stamps and handwriting. The corpus's own
  headline finding attributes real-ACORD failure to exactly those, so **this ladder is not
  a substitute for real documents** — it is a different variable.
- **Bad scanning.** L3 is a *good* desk scanner: mild skew (±1.2°), moderate noise, JPEG
  quality 38–55. Production documents are frequently far worse — multi-generation
  photocopies, dark bands, heavy skew, phone photos. Any degradation measured here is a
  **lower bound**.
- **Parser-specific pathologies.** Type-3 font space mangling, broken-`ToUnicode` glyph
  escapes, and similar defects come from how real PDFs were *produced*. A cleanly generated
  PDF will not exhibit them.

## Pilot result (2026-07-22) — prediction confirmed

12 documents × 3 categories × 4 levels. Parse via the real parse service, extract via the
production engine (`intelligentExtract`, arm `openai:gpt-4o-mini`, held constant across
levels), scored with **fieldbench 0.1.0** — the canonical scorer, not `koji bench`.

| Level | Accuracy | Δ vs L0 | Step |
|---|---:|---:|---:|
| L0 markdown (control) | 89.7% | — | — |
| L1 native PDF | 86.8% | −2.9pp | −2.9pp |
| **L2 rasterized (OCR)** | **72.1%** | **−17.6pp** | **−14.7pp** ← dominant |
| L3 scan-simulated | 64.7% | −25.0pp | −7.4pp |

Paired exact McNemar over the same 76 fields:

| Step | lost | gained | p |
|---|---:|---:|---:|
| L0 → L1 | 3 | 1 | 0.625 (n.s.) |
| **L1 → L2** | **13** | **3** | **0.021** |
| L2 → L3 | 11 | 6 | 0.332 (n.s.) |
| L0 → L3 | 18 | 1 | 0.0001 |

**The prediction stated in advance holds.** `L1 → L2` — losing the text layer to OCR — is
the dominant step and the only individual step that reaches significance. Introducing real
page layout while keeping a text layer (`L0 → L1`) costs little and is not significant.

Monotonic in all three categories independently:

| Category | L0 | L1 | L2 | L3 |
|---|---:|---:|---:|---:|
| insurance_certificates | 91.7% | 83.3% | 75.0% | 70.8% |
| invoices | 89.3% | 89.3% | 75.0% | 67.9% |
| medical_records | 87.5% | 87.5% | 62.5% | 50.0% |

### The mechanism: silent deletion, not garbling

OCR does not corrupt text into obvious noise. It **deletes clauses and leaves fluent prose
behind**. Same sentence, L1 vs L2:

> **L1:** `HISTORY OF PRESENT ILLNESS: The patient is a 61-year-old white female status post right total knee replacement secondary to degenerative joint disease performed by Dr. A...`
>
> **L2:** `HISTORY OF PRESENT ILLNESS: secondary to degenerative joint disease performed by Dr. A...`

Text volume retained vs L1: forms lose 3–14%, dense two-page prose loses 36–64%.

The four-way null semantics show what this does to extraction:

| Bucket | L0 | L1 | L2 | L3 |
|---|---:|---:|---:|---:|
| match | 57 | 55 | 45 | 40 |
| **wrong_value** | 10 | 12 | **21** | 21 |
| miss | 3 | 3 | 4 | 9 |
| hallucination | 1 | 1 | 1 | 1 |
| correct_absence | 5 | 5 | 5 | 5 |

**Degradation converts matches into *wrong values*, not into misses or hallucinations.**
The hallucination count is constant at 1 across every level. The model does not abstain
when the source is degraded — it confidently returns a wrong answer, and the wrong answer
*is* present in the corrupted text, so source-grounding cannot flag it. A faithfulness gate
that checks whether a value appears in the cited source will not catch any of this.

### Caveats

- **n = 12 documents / 68 fields, single run, single model.** Directionally clear and
  significant on the key step, but the magnitude needs the full 613-document run with
  repeats before it is quotable.
- `L2 → L3` is **not** individually significant at this n. Scan artefacts beyond
  rasterisation are not yet distinguishable from noise.
- Per-category cells are 4 documents each — far too small to compare categories against
  each other.
- 8 of 76 fields (`medications_at_discharge`, `procedures`) are excluded: the engine returns
  `[{medication: "X"}]` where the schema says `type: array` and ground truth is `["X"]`.
  That mismatch is **identical at all four levels**, so it contributes exactly zero to the
  deltas, but it depresses absolute medical_records accuracy from 87.5% to 62.5% and is a
  real engine bug worth filing separately.

## Reproducing

```bash
python3 scripts/ladder_build_corpora.py        # render, parse, build shadow corpora
# then run exp-m1 per level (see experiments/extraction-experiments/README.md)
~/dev/fieldbench/.venv/bin/python scripts/ladder_score.py
```

Each level is a shadow corpus (`documents/` = that level's parsed markdown;
`expected/`, `schemas/`, `manifests/` identical across levels), so extract is genuinely
held constant and no bespoke extraction code exists.
