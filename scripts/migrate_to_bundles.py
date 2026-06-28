#!/usr/bin/env python3
"""Migrate corpus documents into the doc-bundle layout (PB-0).

The legacy corpus layout splits each document across four parallel
directories per category:

    <category>/documents/<id>.md          # docling markdown (a DERIVED view)
    <category>/expected/<id>.expected.json # field-value ground truth
    <category>/manifests/<id>.json         # source provenance
    <category>/schemas/<name>.yaml         # extraction schema (shared)

That treats *markdown* as the anchor. But parse providers consume the
*source document* (PDF/image/office file), and we want to score many
providers against one ground truth. So the bundle layout re-anchors on the
source and treats every parsed representation as a cached, derived artifact:

    <category>/docs/<id>/
        meta.json                       # quality tag + source provenance +
                                        #   representation matrix (how each
                                        #   parse was produced) + schema ref
        truth.json                      # field-value ground truth (the answer)
        source.<ext>                    # original source bytes IF available
        parsed/
            docling-markdown.md         # frozen academic md snapshot
            docling-markdown.meta.json  # how it was produced (drift metadata)

This script is idempotent: re-running it overwrites the bundle for a doc.
It NEVER deletes the legacy files — migration is additive until the harness
(PB-3) and scorer are cut over to read bundles.

Usage:
    # migrate the curated PB-0 sample (spans digital/scan/fax/mixed)
    python scripts/migrate_to_bundles.py --sample

    # migrate specific docs
    python scripts/migrate_to_bundles.py --category receipts --doc sroie_000

    # migrate an entire category (quality inferred + flagged for review)
    python scripts/migrate_to_bundles.py --category invoices --all
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

CORPUS_ROOT = Path(__file__).resolve().parent.parent

# Quality vocabulary used to slice provider scores by document quality.
QUALITY_TAGS = {"digital", "scan", "fax", "mixed"}

# ---------------------------------------------------------------------------
# Curated PB-0 sample. Quality tags here are HUMAN-REVIEWED (quality_reviewed
# = true in the emitted meta). Everything else gets an inferred tag flagged
# for review. The sample deliberately spans the four quality tiers and the
# real/synthetic + present/absent-source axes.
# ---------------------------------------------------------------------------
SAMPLE: list[dict[str, Any]] = [
    # digital, real source bytes present in-repo (native office file)
    {
        "category": "multi_format",
        "doc": "meridian_invoice_xlsx",
        "quality": "digital",
        "quality_notes": "Native digital .xlsx; source bytes present in repo.",
    },
    # digital, real PDF but source link rotted (url no longer fetchable)
    {
        "category": "insurance_certificates",
        "doc": "arizona_coi",
        "quality": "digital",
        "quality_notes": "Born-digital gov sample PDF. Source URL dead at migration "
        "time (returned HTML) -> source.retrieved=false; refetch needed.",
    },
    # scan, real OCR'd image source (registration-gated dataset)
    {
        "category": "receipts",
        "doc": "sroie_000",
        "quality": "scan",
        "quality_notes": "Real scanned receipt (SROIE JPEG). Source image gated behind "
        "dataset registration -> source.retrieved=false.",
    },
    # fax-grade degradation (synthetic OCR noise)
    {
        "category": "adversarial",
        "doc": "anomaly_ocr_typos",
        "quality": "fax",
        "quality_notes": "Synthetic OCR-typo noise; stands in for fax/low-DPI degradation.",
    },
    # mixed (multi-document packet)
    {
        "category": "adversarial",
        "doc": "anomaly_three_doc_packet",
        "quality": "mixed",
        "quality_notes": "Synthetic stapled multi-doc packet; mixed content/quality.",
    },
    # digital, synthetic structured form
    {
        "category": "irs_forms",
        "doc": "synthetic_1099nec_001",
        "quality": "digital",
        "quality_notes": "Programmatically generated 1099-NEC; clean structured text.",
    },
    # digital, real EDGAR filing (text)
    {
        "category": "sec_filings",
        "doc": "edgar_10k_001",
        "quality": "digital",
        "quality_notes": "Real EDGAR 10-K; born-digital HTML/text filing.",
    },
    # digital, real transcription text
    {
        "category": "medical_records",
        "doc": "mts-001-discharge-summary-knee-surgery-discharge-summary",
        "quality": "digital",
        "quality_notes": "MTSamples transcription; clean digital text.",
    },
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def infer_quality(manifest: dict[str, Any]) -> str:
    """Best-effort quality guess from the legacy manifest.

    This is a HEURISTIC. Anything inferred is flagged quality_reviewed=false
    so a human confirms before the tag is trusted for slicing.
    """
    fmt = (manifest.get("original_format") or "").lower()
    if manifest.get("anomaly"):
        return "mixed"
    if (
        "jpeg" in fmt
        or "image" in fmt
        or "scan" in fmt
        or manifest.get("original_image")
    ):
        return "scan"
    # PDFs, HTML, office docs, synthetic markdown -> assume born-digital.
    return "digital"


def find_source_binary(category_dir: Path, manifest: dict[str, Any]) -> Path | None:
    """Locate an original source binary for a doc if one exists in the repo.

    Today only multi_format ships real source bytes (in <category>/sources/).
    Receipts/COIs reference an external URL/image that is not stored. This
    returns the path if found, else None (caller records retrieved=false).
    """
    src_name = manifest.get("source_filename") or manifest.get("original_image")
    if not src_name:
        return None
    candidate = category_dir / "sources" / src_name
    return candidate if candidate.is_file() else None


def source_ext(manifest: dict[str, Any], binary: Path | None) -> str:
    if binary is not None:
        return binary.suffix.lstrip(".").lower()
    fmt = (manifest.get("original_format") or "").lower()
    if "pdf" in fmt:
        return "pdf"
    if "jpeg" in fmt or "jpg" in fmt:
        return "jpg"
    if "png" in fmt:
        return "png"
    if "docx" in fmt:
        return "docx"
    if "xlsx" in fmt:
        return "xlsx"
    if "pptx" in fmt:
        return "pptx"
    if "html" in fmt:
        return "html"
    return "txt"


def migrate_doc(
    category: str,
    doc_id: str,
    quality: str | None = None,
    quality_notes: str | None = None,
    quality_reviewed: bool = False,
) -> Path:
    category_dir = CORPUS_ROOT / category
    md_path = category_dir / "documents" / f"{doc_id}.md"
    expected_path = category_dir / "expected" / f"{doc_id}.expected.json"
    manifest_path = category_dir / "manifests" / f"{doc_id}.json"

    if not md_path.is_file():
        raise FileNotFoundError(f"missing markdown: {md_path}")
    if not expected_path.is_file():
        raise FileNotFoundError(f"missing ground truth: {expected_path}")

    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}

    if quality is None:
        quality = infer_quality(manifest)
        quality_reviewed = False
    if quality not in QUALITY_TAGS:
        raise ValueError(f"quality {quality!r} not in {sorted(QUALITY_TAGS)}")

    bundle = category_dir / "docs" / doc_id
    parsed = bundle / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)

    # --- truth.json (field-value ground truth) ---
    truth_text = expected_path.read_text()
    (bundle / "truth.json").write_text(truth_text)

    # --- source binary (if we have the real bytes) ---
    binary = find_source_binary(category_dir, manifest)
    ext = source_ext(manifest, binary)
    source_meta: dict[str, Any]
    if binary is not None:
        dest = bundle / f"source.{ext}"
        shutil.copy2(binary, dest)
        source_meta = {
            "file": dest.name,
            "format": ext,
            "sha256": sha256_file(dest),
            "retrieved": True,
        }
    else:
        source_meta = {
            "file": None,
            "format": ext,
            "sha256": None,
            "retrieved": False,
        }
    source_meta.update(
        {
            "name": manifest.get("source_name"),
            "url": manifest.get("source_url"),
            "original_image": manifest.get("original_image"),
            "pages": manifest.get("pages"),
            "license": manifest.get("license"),
            "license_url": manifest.get("license_url"),
            "attribution": manifest.get("attribution"),
        }
    )

    # --- cached docling-markdown representation (frozen academic snapshot) ---
    md_text = md_path.read_text()
    (parsed / "docling-markdown.md").write_text(md_text)
    repr_meta = {
        "file": "docling-markdown.md",
        "provider": "docling",
        # the legacy corpus predates per-parse version capture; record that
        # honestly rather than inventing a version number.
        "provider_version": "unknown (pre-PB-0; legacy docling parse)",
        "api_version": None,
        "representation": "markdown",
        "parse_config": {},
        "produced": manifest.get("added_date"),
        "produced_by": manifest.get("added_by"),
        "sha256": sha256_text(md_text),
        "frozen_for": ["academic-md-snapshot-v1"],
        "migrated_from": f"{category}/documents/{doc_id}.md",
    }
    (parsed / "docling-markdown.meta.json").write_text(
        json.dumps(repr_meta, indent=2) + "\n"
    )

    # --- doc-level meta.json ---
    meta = {
        "doc_id": doc_id,
        "category": category,
        "doc_type": manifest.get("doc_type"),
        "synthetic": bool(manifest.get("synthetic"))
        or "synthetic" in (manifest.get("original_format") or "").lower(),
        "anomaly": bool(manifest.get("anomaly", False)),
        "quality": quality,
        "quality_reviewed": quality_reviewed,
        "quality_notes": quality_notes,
        "schema": manifest.get("schema"),
        "source": source_meta,
        "truth": {
            "file": "truth.json",
            # GT is versioned against the source bytes when we have them;
            # otherwise it is anchored to the (named) source document.
            "anchored_to": "source.sha256" if source_meta["sha256"] else "source.name",
            "source_sha256": source_meta["sha256"],
        },
        "representations": [
            {
                "file": f"parsed/{repr_meta['file']}",
                "provider": repr_meta["provider"],
                "provider_version": repr_meta["provider_version"],
                "representation": repr_meta["representation"],
                "produced": repr_meta["produced"],
                "sha256": repr_meta["sha256"],
                "frozen_for": repr_meta["frozen_for"],
            }
        ],
        "provenance": {
            "added_date": manifest.get("added_date"),
            "added_by": manifest.get("added_by"),
            "migrated_by": "accuracy-31",
            "migrated_from": {
                "document": f"{category}/documents/{doc_id}.md",
                "expected": f"{category}/expected/{doc_id}.expected.json",
                "manifest": f"{category}/manifests/{doc_id}.json"
                if manifest_path.is_file()
                else None,
            },
        },
        "schema_version": "doc-bundle/v1",
    }
    (bundle / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    flag = "" if quality_reviewed else "  (quality INFERRED - review!)"
    src = "source.%s" % ext if source_meta["retrieved"] else "no source bytes"
    print(f"  migrated {category}/{doc_id}  [{quality}{flag}]  {src}")
    return bundle


def migrate_category(category: str) -> None:
    docs_dir = CORPUS_ROOT / category / "documents"
    for md in sorted(docs_dir.glob("*.md")):
        try:
            migrate_doc(category, md.stem)
        except FileNotFoundError as e:
            print(f"  SKIP {category}/{md.stem}: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--sample", action="store_true", help="migrate the curated PB-0 sample set"
    )
    ap.add_argument("--category", help="category name")
    ap.add_argument("--doc", help="single doc id (requires --category)")
    ap.add_argument(
        "--all", action="store_true", help="migrate every doc in --category"
    )
    args = ap.parse_args()

    if args.sample:
        print("Migrating PB-0 sample set:")
        for spec in SAMPLE:
            migrate_doc(
                spec["category"],
                spec["doc"],
                quality=spec["quality"],
                quality_notes=spec.get("quality_notes"),
                quality_reviewed=True,
            )
        return 0
    if args.category and args.doc:
        migrate_doc(args.category, args.doc)
        return 0
    if args.category and args.all:
        print(f"Migrating category {args.category}:")
        migrate_category(args.category)
        return 0
    ap.error("specify --sample, or --category with --doc, or --category --all")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
