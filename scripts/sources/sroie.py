#!/usr/bin/env python3
"""SROIE dataset sourcing script for the Koji validation corpus.

Fetches receipts from the SROIE (Scanned Receipt OCR and Information Extraction)
dataset, converts them to Koji corpus format, and writes them into the invoices
category.

SROIE is an ICDAR 2019 competition dataset containing receipt images and
annotated ground truth for four fields: company, date, address, total.

Dataset:
  - Official: https://rrc.cvc.uab.es/?ch=13 (requires registration)
  - Mirror: https://github.com/zzzDavid/ICDAR-2019-SROIE (Task 3 annotations)

Why we use SROIE:
  - Pre-annotated ground truth means no manual review needed for these fields
  - Receipt images exercise OCR and layout analysis
  - Diverse retailers from Singapore give variety beyond US-centric data

Prerequisites:
  - Koji parse service running at http://127.0.0.1:9411/parse
    (or pass --parse-url to override)
  - httpx installed

Usage:
  python scripts/sources/sroie.py --limit 20
  python scripts/sources/sroie.py --parse-url http://localhost:9411/parse --limit 50
  python scripts/sources/sroie.py --dataset-path ./sroie-dataset/

Steps the script performs:
  1. Download the SROIE Task 3 dataset (images + JSON annotations)
  2. For each receipt image, POST it to Koji parse service to get markdown
  3. Load the SROIE JSON annotation for that receipt
  4. Convert SROIE field names to Koji invoice_basic schema:
       - company -> merchant_name
       - date -> date (normalized to YYYY-MM-DD)
       - total -> total_amount
       - address stays as context only (not in our schema)
  5. Write document, expected JSON, and manifest to the corpus
  6. Skip receipts that already exist (idempotent)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import httpx

CORPUS_ROOT = Path(__file__).resolve().parent.parent.parent
INVOICES_DIR = CORPUS_ROOT / "invoices"

# Mirror of SROIE Task 3 (information extraction) — the only task with
# ground truth annotations we can use for validation.
SROIE_ZIP_URL = (
    "https://github.com/zzzDavid/ICDAR-2019-SROIE/archive/refs/heads/master.zip"
)

DEFAULT_PARSE_URL = "http://127.0.0.1:9411/parse"


def _normalize_date(value: str) -> str | None:
    """Convert a SROIE date string to YYYY-MM-DD. Returns None if unparseable."""
    if not value:
        return None
    value = value.strip()

    # Already ISO
    match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"

    # DD/MM/YYYY or DD-MM-YYYY (common in SROIE)
    match = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", value)
    if match:
        d, m, y = match.groups()
        if len(y) == 2:
            y = "20" + y
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"

    return None


def _normalize_total(value: str) -> float | None:
    """Parse a SROIE total string to a float. Returns None if unparseable."""
    if value is None:
        return None
    cleaned = re.sub(r"[^\d.,\-]", "", str(value))
    if not cleaned:
        return None
    # Assume period is decimal separator (SROIE uses periods)
    cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def download_dataset(dest: Path) -> Path:
    """Download and extract the SROIE dataset. Returns the extracted root directory."""
    if dest.exists() and any(dest.iterdir()):
        print(f"[sroie] Dataset already downloaded at {dest}", file=sys.stderr)
        return dest

    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "sroie.zip"
    print(f"[sroie] Downloading dataset from {SROIE_ZIP_URL}", file=sys.stderr)

    with httpx.stream("GET", SROIE_ZIP_URL, follow_redirects=True, timeout=600.0) as resp:
        resp.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)

    print(f"[sroie] Extracting to {dest}", file=sys.stderr)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)

    zip_path.unlink()
    return dest


def find_task3_pairs(dataset_root: Path) -> list[tuple[Path, Path]]:
    """Find all (image, annotation JSON) pairs in the SROIE dataset.

    Task 3 annotations live in: 0325updated.task3train/0325updated.task3train(626p)/
    with .jpg + .txt (key-value format) pairs, or as 'key' files.
    """
    pairs: list[tuple[Path, Path]] = []
    # Look for Task 3 directory (information extraction)
    candidates = list(dataset_root.rglob("*.jpg")) + list(dataset_root.rglob("*.png"))

    for image in candidates:
        # Look for matching annotation file (SROIE uses .txt with key:value pairs
        # or JSON depending on mirror)
        txt = image.with_suffix(".txt")
        if txt.exists():
            # Verify it's an annotation file, not an OCR transcript
            try:
                content = txt.read_text(encoding="utf-8", errors="replace")
                if '"company"' in content or "company:" in content.lower():
                    pairs.append((image, txt))
            except Exception:
                continue

    return pairs


def parse_sroie_annotation(txt_path: Path) -> dict:
    """Parse a SROIE annotation file into a dict.

    SROIE annotations come in two formats depending on the mirror:
      1. JSON: {"company": "...", "date": "...", "address": "...", "total": "..."}
      2. Key-value lines: company:XXX\\ndate:XXX\\naddress:XXX\\ntotal:XXX

    Returns a dict with normalized keys.
    """
    content = txt_path.read_text(encoding="utf-8", errors="replace").strip()
    if not content:
        return {}

    # Try JSON first
    if content.startswith("{"):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

    # Fall back to key:value format
    result: dict = {}
    for line in content.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip().lower()] = value.strip()

    return result


def parse_image_to_markdown(image_path: Path, parse_url: str, client: httpx.Client) -> str:
    """POST an image to Koji's parse service and return the markdown output."""
    with open(image_path, "rb") as f:
        files = {"file": (image_path.name, f, "image/jpeg")}
        resp = client.post(parse_url, files=files, timeout=300.0)

    resp.raise_for_status()
    data = resp.json()
    return data.get("markdown", "")


def convert_to_koji_format(sroie_annotation: dict) -> dict:
    """Convert a SROIE annotation dict to a Koji invoice_basic expected output."""
    return {
        "merchant_name": sroie_annotation.get("company") or None,
        "date": _normalize_date(sroie_annotation.get("date", "")),
        "total_amount": _normalize_total(sroie_annotation.get("total", "")),
        "subtotal": None,
        "tax": None,
        "currency": "SGD",  # SROIE is Singaporean, default SGD
        "items": None,
    }


def write_sample(
    receipt_id: str,
    markdown: str,
    expected: dict,
    source_image: str,
) -> None:
    """Write a SROIE receipt into the corpus as document, expected, and manifest."""
    doc_path = INVOICES_DIR / "documents" / f"sroie_{receipt_id}.md"
    exp_path = INVOICES_DIR / "expected" / f"sroie_{receipt_id}.expected.json"
    man_path = INVOICES_DIR / "manifests" / f"sroie_{receipt_id}.json"

    doc_path.write_text(markdown + "\n")
    exp_path.write_text(json.dumps(expected, indent=2) + "\n")

    manifest = {
        "filename": doc_path.name,
        "source_name": "SROIE Dataset (ICDAR 2019)",
        "source_url": "https://rrc.cvc.uab.es/?ch=13",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "ICDAR 2019 Robust Reading Challenge on SROIE",
        "original_format": "JPEG image (parsed via Koji parse service)",
        "original_image": source_image,
        "r2_url": None,
        "pages": 1,
        "added_date": "2026-04-12",
        "added_by": "corpus-bootstrap",
        "schema": "invoices/schemas/invoice_basic.yaml",
        "notes": "Singaporean receipt from SROIE Task 3. Ground truth from dataset annotations (company, date, total). Subtotal, tax, and line items left null — SROIE doesn't annotate them.",
    }
    man_path.write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of receipts to process (default: 20)",
    )
    parser.add_argument(
        "--parse-url",
        default=DEFAULT_PARSE_URL,
        help=f"Koji parse service URL (default: {DEFAULT_PARSE_URL})",
    )
    parser.add_argument(
        "--dataset-path",
        type=Path,
        default=CORPUS_ROOT / ".sroie-cache",
        help="Path to download and cache the SROIE dataset",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download and use an already-extracted dataset at --dataset-path",
    )
    args = parser.parse_args()

    # Ensure target dirs exist
    for sub in ("documents", "expected", "manifests"):
        (INVOICES_DIR / sub).mkdir(parents=True, exist_ok=True)

    # Download dataset
    if not args.skip_download:
        download_dataset(args.dataset_path)

    # Find all annotated receipts
    pairs = find_task3_pairs(args.dataset_path)
    if not pairs:
        print(
            f"[sroie] No annotated receipts found in {args.dataset_path}. "
            f"Check that the dataset download extracted correctly.",
            file=sys.stderr,
        )
        return 1

    print(f"[sroie] Found {len(pairs)} annotated receipts", file=sys.stderr)

    # Process receipts
    processed = 0
    skipped = 0
    failed = 0

    with httpx.Client() as client:
        for i, (image, txt) in enumerate(pairs):
            if processed >= args.limit:
                break

            receipt_id = image.stem
            doc_path = INVOICES_DIR / "documents" / f"sroie_{receipt_id}.md"
            if doc_path.exists():
                skipped += 1
                continue

            try:
                annotation = parse_sroie_annotation(txt)
                if not annotation or "company" not in annotation:
                    failed += 1
                    continue

                markdown = parse_image_to_markdown(image, args.parse_url, client)
                expected = convert_to_koji_format(annotation)
                write_sample(receipt_id, markdown, expected, image.name)

                processed += 1
                print(f"[sroie] ({processed}/{args.limit}) {receipt_id}", file=sys.stderr)

                # Rate limit — don't hammer the parse service
                time.sleep(0.5)

            except httpx.HTTPError as e:
                print(f"[sroie] HTTP error on {receipt_id}: {e}", file=sys.stderr)
                failed += 1
            except Exception as e:
                print(f"[sroie] Error on {receipt_id}: {e}", file=sys.stderr)
                failed += 1

    print(
        f"\n[sroie] Done. Processed: {processed}, Skipped: {skipped}, Failed: {failed}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
