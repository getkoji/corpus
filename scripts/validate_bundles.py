#!/usr/bin/env python3
"""Validate doc-bundles (PB-0) are machine-readable by a parse-eval harness.

This is the executable form of the PB-0 acceptance criterion: for every
migrated doc, a harness must be able to read
  - the source (bytes if present, else provenance + retrieved=false),
  - the field-value ground truth (truth.json),
  - the quality tag (digital/scan/fax/mixed),
  - the representation matrix (how each cached parse was produced).

Exit non-zero if any bundle is malformed, so this can gate CI.

Usage:
    python scripts/validate_bundles.py            # all bundles
    python scripts/validate_bundles.py receipts   # one category
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

CORPUS_ROOT = Path(__file__).resolve().parent.parent
QUALITY_TAGS = {"digital", "scan", "fax", "mixed"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_bundles(category: str | None) -> list[Path]:
    pattern = f"{category}/docs/*/meta.json" if category else "*/docs/*/meta.json"
    return [meta.parent for meta in sorted(CORPUS_ROOT.glob(pattern))]


def validate(bundle: Path) -> list[str]:
    errs: list[str] = []
    meta_path = bundle / "meta.json"
    try:
        meta = json.loads(meta_path.read_text())
    except Exception as e:  # noqa: BLE001
        return [f"meta.json unreadable: {e}"]

    # quality tag
    if meta.get("quality") not in QUALITY_TAGS:
        errs.append(f"quality {meta.get('quality')!r} not in {sorted(QUALITY_TAGS)}")

    # ground truth
    truth_file = (meta.get("truth") or {}).get("file", "truth.json")
    truth_path = bundle / truth_file
    if not truth_path.is_file():
        errs.append(f"missing truth file: {truth_file}")
    else:
        try:
            json.loads(truth_path.read_text())
        except Exception as e:  # noqa: BLE001
            errs.append(f"truth.json not valid JSON: {e}")

    # source: bytes present iff retrieved=true; sha256 must match
    src = meta.get("source") or {}
    if src.get("retrieved"):
        if not src.get("file"):
            errs.append("source.retrieved=true but no source.file")
        else:
            sp = bundle / src["file"]
            if not sp.is_file():
                errs.append(f"source bytes missing: {src['file']}")
            elif src.get("sha256") and sha256_file(sp) != src["sha256"]:
                errs.append(f"source sha256 drift: {src['file']}")
    else:
        # acceptable, but must carry enough provenance to refetch later
        if not (src.get("url") or src.get("name") or src.get("original_image")):
            errs.append(
                "source not retrieved AND no url/name/original_image to refetch"
            )

    # representation matrix
    reps = meta.get("representations") or []
    if not reps:
        errs.append("no representations recorded")
    for rep in reps:
        for k in ("file", "provider", "provider_version", "representation"):
            if not rep.get(k):
                errs.append(f"representation missing {k}: {rep.get('file')}")
        rp = bundle / rep["file"]
        if not rp.is_file():
            errs.append(f"representation file missing: {rep['file']}")
        elif rep.get("sha256") and sha256_text(rp.read_text()) != rep["sha256"]:
            errs.append(f"representation sha256 drift: {rep['file']}")
    return errs


def main() -> int:
    category = sys.argv[1] if len(sys.argv) > 1 else None
    bundles = find_bundles(category)
    if not bundles:
        print("no bundles found", file=sys.stderr)
        return 1
    bad = 0
    for b in bundles:
        errs = validate(b)
        rel = b.relative_to(CORPUS_ROOT)
        if errs:
            bad += 1
            print(f"FAIL {rel}")
            for e in errs:
                print(f"     - {e}")
        else:
            print(f"ok   {rel}")
    print(f"\n{len(bundles) - bad}/{len(bundles)} bundles valid")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
