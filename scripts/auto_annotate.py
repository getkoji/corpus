#!/usr/bin/env python3
"""Auto-annotate corpus documents using Koji extraction.

Runs extraction on documents that have placeholder expected JSON
(annotation_status: needs_review or auto_partial) and replaces
the expected output with the extraction result.

This is a FIRST PASS — the output should be human-reviewed for
correctness before being used as ground truth.

Usage:
  uv run --with httpx --with pyyaml python scripts/auto_annotate.py
  uv run --with httpx --with pyyaml python scripts/auto_annotate.py --category contracts
  uv run --with httpx --with pyyaml python scripts/auto_annotate.py --dry-run
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

CORPUS_ROOT = Path(__file__).resolve().parent.parent
EXTRACT_URL = "http://127.0.0.1:9412"


def find_unannotated(category: str | None = None) -> list[dict]:
    """Find documents with placeholder expected JSON."""
    entries = []

    categories = [category] if category else [
        d.name for d in CORPUS_ROOT.iterdir()
        if d.is_dir() and d.name != "scripts" and (d / "documents").is_dir()
    ]

    for cat in categories:
        cat_dir = CORPUS_ROOT / cat
        docs_dir = cat_dir / "documents"
        expected_dir = cat_dir / "expected"
        schemas_dir = cat_dir / "schemas"
        manifests_dir = cat_dir / "manifests"

        if not docs_dir.is_dir():
            continue

        # Find schema
        schema_files = list(schemas_dir.glob("*.yaml")) if schemas_dir.is_dir() else []
        if not schema_files:
            continue

        for doc_path in sorted(docs_dir.glob("*.md")):
            exp_path = expected_dir / f"{doc_path.stem}.expected.json"
            if not exp_path.exists():
                continue

            try:
                expected = json.loads(exp_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            status = expected.get("_annotation_status", "")
            if status not in ("needs_review", "auto_partial"):
                continue

            # Find schema from manifest or default
            manifest_path = manifests_dir / f"{doc_path.stem}.json"
            schema_path = schema_files[0]  # default
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text())
                    schema_rel = manifest.get("schema", "")
                    if schema_rel:
                        candidate = CORPUS_ROOT / schema_rel
                        if candidate.exists():
                            schema_path = candidate
                except (json.JSONDecodeError, OSError):
                    pass

            entries.append({
                "category": cat,
                "doc_path": doc_path,
                "exp_path": exp_path,
                "schema_path": schema_path,
                "current_expected": expected,
            })

    return entries


def extract_and_annotate(entry: dict, client: httpx.Client) -> dict | None:
    """Run extraction and return the extracted fields."""
    doc_text = entry["doc_path"].read_text()
    schema_def = yaml.safe_load(entry["schema_path"].read_text())

    try:
        resp = client.post(
            f"{EXTRACT_URL}/extract",
            json={"markdown": doc_text, "schema_def": schema_def},
            timeout=300,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("extracted", {})
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return None


def merge_annotation(current: dict, extracted: dict) -> dict:
    """Merge extracted values into current expected JSON.

    For auto_partial entries (legal filings), keep metadata fields
    that were auto-filled from the source (case_number, court, etc)
    and fill in fields that were null. For needs_review entries
    (contracts), replace everything.
    """
    status = current.get("_annotation_status", "")

    if status == "needs_review":
        # Replace all fields with extraction output
        result = {}
        for key, value in extracted.items():
            if key.startswith("_"):
                continue
            result[key] = value
        result["_annotation_status"] = "auto_extracted"
        return result

    elif status == "auto_partial":
        # Keep existing non-null values, fill nulls from extraction
        result = dict(current)
        for key, value in extracted.items():
            if key.startswith("_"):
                continue
            if result.get(key) is None and value is not None:
                result[key] = value
        result["_annotation_status"] = "auto_extracted"
        return result

    return current


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", type=str, default=None, help="Only annotate one category")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be annotated without writing")
    parser.add_argument("--limit", type=int, default=None, help="Max documents to annotate")
    args = parser.parse_args()

    entries = find_unannotated(args.category)
    print(f"[annotate] Found {len(entries)} unannotated documents")

    if args.limit:
        entries = entries[:args.limit]

    if args.dry_run:
        for e in entries:
            print(f"  {e['category']}/{e['doc_path'].name} ({e['current_expected'].get('_annotation_status')})")
        return 0

    # Check extract service
    try:
        health = httpx.get(f"{EXTRACT_URL}/health", timeout=5)
        if health.status_code != 200:
            print(f"[annotate] Extract service not healthy", file=sys.stderr)
            return 1
    except httpx.RequestError:
        print(f"[annotate] Cannot reach extract service at {EXTRACT_URL}", file=sys.stderr)
        return 1

    annotated = 0
    failed = 0

    by_category: dict[str, int] = {}

    with httpx.Client() as client:
        for i, entry in enumerate(entries):
            cat = entry["category"]
            doc_name = entry["doc_path"].name
            print(f"[annotate] ({i+1}/{len(entries)}) {cat}/{doc_name}", end="", flush=True)

            extracted = extract_and_annotate(entry, client)
            if extracted is None:
                print(" FAILED")
                failed += 1
                continue

            merged = merge_annotation(entry["current_expected"], extracted)

            # Write updated expected JSON
            entry["exp_path"].write_text(json.dumps(merged, indent=2) + "\n")

            non_null = sum(1 for k, v in merged.items() if not k.startswith("_") and v is not None)
            total = sum(1 for k in merged if not k.startswith("_"))
            print(f" OK ({non_null}/{total} fields)")

            annotated += 1
            by_category[cat] = by_category.get(cat, 0) + 1

            # Brief pause to avoid hammering extract service
            time.sleep(0.5)

    print(f"\n[annotate] Done: {annotated} annotated, {failed} failed")
    for cat, count in sorted(by_category.items()):
        print(f"  {cat}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
