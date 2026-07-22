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

## Status

**The harness is built and verified. The experiment has not been run.** Running it means
pushing each level through parse + extract and scoring against the shared ground truth —
that needs the parse service and model credentials, and it is the next step.

Expected shape of the result, stated in advance so it is falsifiable:

- `L0 → L1` — small drop. Layout is introduced, but the text layer is intact.
- `L1 → L2` — the large drop, if parse quality dominates. OCR replaces a perfect text layer.
- `L2 → L3` — a further drop tracking artefact severity.

If `L1 → L2` is *not* the dominant step, the "parse quality is the hidden ceiling"
hypothesis is wrong, and that is worth knowing too.
