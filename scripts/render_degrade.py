#!/usr/bin/env python3
"""Render corpus markdown into real documents and degrade them (BR-0b, Track A).

Most of this corpus never existed as a rendered page (see docs/composition.md), so
it measures extraction-from-clean-text rather than document extraction. This script
builds a *paired* ladder from documents that already have ground truth: same
document, same ground truth, progressively more realistic input.

    L0  markdown          the current corpus input (control)
    L1  native PDF        real layout, real text layer
    L2  rasterized PDF    no text layer — forces OCR
    L3  scan-simulated    L2 plus skew, noise, JPEG artefacts, contrast shift

Because ground truth is identical across the ladder, any accuracy drop is
attributable to the input becoming a document. Nothing else changes.

Output is deterministic for a given --seed, so PDFs are regenerated rather than
committed. Use --manifest to record checksums for reproducibility.

Usage:
    python3 scripts/render_degrade.py --category insurance_certificates --limit 2
    python3 scripts/render_degrade.py --all --out build/ladder --manifest build/ladder.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import random
import re
import sys

try:
    import fitz  # PyMuPDF
    import numpy as np
    from PIL import Image, ImageEnhance
except ImportError as e:  # pragma: no cover
    sys.exit(f"missing dependency: {e}. Needs pymupdf, pillow, numpy.")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from composition_report import classify  # noqa: E402  (needs the path set above)

LEVELS = ("L1_native", "L2_raster", "L3_scan")
RASTER_DPI = 200

# A plain business-document stylesheet. Deliberately unremarkable: the point is to
# produce a realistic page, not a pretty one.
CSS = """
body { font-family: sans-serif; font-size: 9.5pt; color: #000; }
h1 { font-size: 15pt; margin: 0 0 6pt 0; }
h2 { font-size: 11pt; margin: 10pt 0 3pt 0; }
p  { margin: 0 0 5pt 0; }
th { font-size: 8.5pt; text-align: left; border: 1px solid #000; padding: 2pt; }
td { font-size: 8.5pt; border: 1px solid #000; padding: 2pt; }
table { width: 100%; border-collapse: collapse; margin: 4pt 0 8pt 0; }
li { margin: 0 0 2pt 0; }
"""


def md_to_html(md: str) -> str:
    """Minimal markdown -> HTML. Covers what the corpus actually uses:
    headings, pipe tables, bullets, horizontal rules, bold, paragraphs."""
    out, rows, buf = [], [], []

    def flush_para():
        if buf:
            out.append("<p>" + "<br/>".join(buf) + "</p>")
            buf.clear()

    def flush_table():
        if not rows:
            return
        # Drop the |---|---| separator row emitted by markdown tables.
        body = [r for r in rows if not re.fullmatch(r"[\s|:-]+", r)]
        out.append("<table>")
        for i, r in enumerate(body):
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            tag = "th" if i == 0 else "td"
            out.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
        out.append("</table>")
        rows.clear()

    for raw in md.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("|"):
            flush_para()
            rows.append(line)
            continue
        flush_table()
        if not line.strip():
            flush_para()
        elif line.startswith("#"):
            flush_para()
            level = min(len(line) - len(line.lstrip("#")), 6)
            out.append(f"<h{level}>{line.lstrip('#').strip()}</h{level}>")
        elif line.strip() in ("---", "***", "___"):
            flush_para()
            out.append("<hr/>")
        elif line.lstrip().startswith(("- ", "* ")):
            flush_para()
            out.append(f"<ul><li>{line.lstrip()[2:].strip()}</li></ul>")
        else:
            buf.append(line.strip())
    flush_para()
    flush_table()

    html = "\n".join(out)
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    return f"<html><body>{html}</body></html>"


def render_native(md: str) -> bytes:
    """L1 — markdown to a real PDF with a text layer and page geometry."""
    story = fitz.Story(html=md_to_html(md), user_css=CSS)
    writer = fitz.DocumentWriter(buf := io.BytesIO())
    page_rect = fitz.paper_rect("letter")
    content_rect = page_rect + (54, 54, -54, -54)  # 0.75in margins
    more = True
    guard = 0
    while more and guard < 200:  # guard against a pathological non-terminating story
        dev = writer.begin_page(page_rect)
        more, _ = story.place(content_rect)
        story.draw(dev)
        writer.end_page()
        guard += 1
    writer.close()
    return pin_pdf_id(buf.getvalue())


def pdf_to_images(pdf_bytes: bytes, dpi: int = RASTER_DPI):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        pages.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
    doc.close()
    return pages


# PyMuPDF writes a random /ID into the PDF trailer on every save, which would make
# otherwise-identical output non-reproducible. Rewrite it from the content hash so the
# same inputs really do produce the same bytes.
_TRAILER_ID = re.compile(rb"/ID\s*\[\s*<[0-9A-Fa-f]*>\s*<[0-9A-Fa-f]*>\s*\]")


def pin_pdf_id(raw: bytes) -> bytes:
    digest = hashlib.sha256(_TRAILER_ID.sub(b"/ID[<><>]", raw)).hexdigest()[:32].upper()
    return _TRAILER_ID.sub(f"/ID[<{digest}><{digest}>]".encode(), raw)


def images_to_pdf(images) -> bytes:
    """Wrap page images back into a PDF. The result has no text layer."""
    doc = fitz.open()
    for img in images:
        b = io.BytesIO()
        img.save(b, format="JPEG", quality=90)
        rect = fitz.Rect(
            0, 0, img.width * 72 / RASTER_DPI, img.height * 72 / RASTER_DPI
        )
        page = doc.new_page(width=rect.width, height=rect.height)
        page.insert_image(rect, stream=b.getvalue())
    out = doc.tobytes()
    doc.close()
    return pin_pdf_id(out)


def degrade(img: Image.Image, rng: random.Random) -> Image.Image:
    """L3 — the artefacts a desk scanner or a phone photo actually introduces."""
    # Skew: pages are never fed in straight.
    img = img.rotate(
        rng.uniform(-1.2, 1.2),
        resample=Image.BICUBIC,
        expand=False,
        fillcolor=(255, 255, 255),
    )
    # Sensor noise.
    arr = np.asarray(img).astype(np.int16)
    arr += (
        np.random.default_rng(rng.randrange(2**31))
        .normal(0, 7, arr.shape)
        .astype(np.int16)
    )
    # Speckle from dust and paper grain.
    flat = arr.reshape(-1, arr.shape[-1])
    idx = np.random.default_rng(rng.randrange(2**31)).choice(
        flat.shape[0], size=int(flat.shape[0] * 0.0006), replace=False
    )
    flat[idx] = 0
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    # Scanners wash out contrast and shift brightness.
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.82, 0.95))
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.94, 1.06))
    # Lossy recompression — almost every scanned PDF in the wild has been through this.
    b = io.BytesIO()
    img.save(b, format="JPEG", quality=rng.randint(38, 55))
    b.seek(0)
    return Image.open(b).convert("RGB")


def build_ladder(md: str, seed: int):
    rng = random.Random(seed)
    native = render_native(md)
    pages = pdf_to_images(native)
    raster = images_to_pdf(pages)
    scan = images_to_pdf([degrade(p, rng) for p in pages])
    return {"L1_native": native, "L2_raster": raster, "L3_scan": scan}, len(pages)


def find_documents(root: pathlib.Path, categories, limit):
    """Documents whose input never had a page (tiers C/D) — the ones this fixes.

    Tier classification is imported from composition_report so the two scripts cannot
    drift apart on what counts as "already came from a page"."""
    found = []
    for cat_dir in sorted(root.glob("*/documents")):
        cat = cat_dir.parent.name
        if categories and cat not in categories:
            continue
        picked = 0
        for doc in sorted(cat_dir.glob("*.md")):
            man = root / cat / "manifests" / f"{doc.stem}.json"
            if not man.exists():
                continue
            fmt = json.loads(man.read_text()).get("original_format")
            if classify(fmt) not in ("C", "D"):
                continue  # already went through a parse engine
            found.append((cat, doc))
            picked += 1
            if limit and picked >= limit:
                break
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--category", action="append", dest="categories")
    ap.add_argument("--limit", type=int, default=2, help="per category (0 = no limit)")
    ap.add_argument("--all", action="store_true", help="every eligible document")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("build/ladder"))
    ap.add_argument("--manifest", type=pathlib.Path)
    ap.add_argument("--seed", type=int, default=20260722)
    ap.add_argument("--root", type=pathlib.Path, default=pathlib.Path("."))
    args = ap.parse_args()

    docs = find_documents(args.root, args.categories, 0 if args.all else args.limit)
    if not docs:
        print("no eligible documents found", file=sys.stderr)
        return 1

    entries, failures = [], 0
    for cat, doc in docs:
        # Seed per document so a document's output is stable regardless of batch order.
        seed = args.seed ^ (int(hashlib.sha256(doc.stem.encode()).hexdigest()[:8], 16))
        try:
            ladder, npages = build_ladder(doc.read_text(), seed)
        except Exception as e:
            print(f"  FAIL {cat}/{doc.stem}: {type(e).__name__}: {e}", file=sys.stderr)
            failures += 1
            continue
        dest = args.out / cat / doc.stem
        dest.mkdir(parents=True, exist_ok=True)
        rec = {
            "category": cat,
            "doc_id": doc.stem,
            "pages": npages,
            "seed": seed,
            "levels": {},
        }
        for level, data in ladder.items():
            path = dest / f"{level}.pdf"
            path.write_bytes(data)
            rec["levels"][level] = {
                "path": str(path),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        entries.append(rec)
        sizes = "  ".join(
            f"{k.split('_')[0]}={len(v) // 1024}KB" for k, v in ladder.items()
        )
        print(f"  {cat}/{doc.stem}  {npages}p  {sizes}")

    print(
        f"\n{len(entries)} documents x {len(LEVELS)} levels -> {args.out}"
        + (f" ({failures} failed)" if failures else "")
    )
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(
                {"seed": args.seed, "raster_dpi": RASTER_DPI, "documents": entries},
                indent=2,
            )
            + "\n"
        )
        print(f"manifest -> {args.manifest}")
    return 1 if failures and not entries else 0


if __name__ == "__main__":
    raise SystemExit(main())
