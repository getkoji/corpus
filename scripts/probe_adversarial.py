#!/usr/bin/env python3
"""Hallucination probe for the adversarial corpus.

Until oss-23 (comparator null semantics) lands, `koji bench` cannot
directly validate that an extractor returned `null` for an anomaly doc —
expected JSONs for pure-null cases are empty `{}` and the bench trivially
passes them at 0/0 fields. This script fills that gap: it hits
`/api/extract` for every adversarial doc whose expected is empty, then
prints any non-null fields the extractor returned.

A non-null field on a pure-null case is a hallucination worth filing as
an oss task. See adversarial/README.md for the current findings.

Usage:
    python scripts/probe_adversarial.py <corpus-root>

Requirements:
    - A running koji cluster reachable at http://127.0.0.1:9401
    - OPENAI_API_KEY in the environment
    - httpx + pyyaml (install via: uv run --with httpx --with pyyaml ...)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

DEFAULT_SERVER_URL = "http://127.0.0.1:9401"
DEFAULT_MODEL = "openai/gpt-4o-mini"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/probe_adversarial.py <corpus-root>", file=sys.stderr)
        return 2

    corpus = Path(sys.argv[1]).resolve()
    adv = corpus / "adversarial"
    if not adv.is_dir():
        print(f"[probe] no adversarial/ directory in {corpus}", file=sys.stderr)
        return 1

    docs_dir = adv / "documents"
    expected_dir = adv / "expected"
    manifest_dir = adv / "manifests"

    hallucinations: list[tuple[str, dict]] = []
    clean: list[str] = []

    with httpx.Client(timeout=600) as client:
        for doc_path in sorted(docs_dir.glob("*.md")):
            stem = doc_path.stem
            expected_path = expected_dir / f"{stem}.expected.json"
            manifest_path = manifest_dir / f"{stem}.json"

            if not expected_path.exists() or not manifest_path.exists():
                continue

            # Only probe docs with EMPTY expected — those are the pure-null
            # cases the bench can't validate directly.
            expected = json.loads(expected_path.read_text())
            if expected:
                continue

            manifest = json.loads(manifest_path.read_text())
            schema_ref = manifest.get("schema")
            if not schema_ref:
                continue
            schema_path = corpus / schema_ref
            if not schema_path.exists():
                print(f"[probe] schema not found for {stem}: {schema_ref}", file=sys.stderr)
                continue

            markdown = doc_path.read_text()
            schema_text = schema_path.read_text()

            try:
                resp = client.post(
                    f"{DEFAULT_SERVER_URL}/api/extract",
                    json={"markdown": markdown, "schema": schema_text, "model": DEFAULT_MODEL},
                )
            except httpx.RequestError as exc:
                print(f"[probe] {stem}: request failed: {exc}", file=sys.stderr)
                continue

            if resp.status_code != 200:
                print(f"[probe] {stem}: HTTP {resp.status_code}", file=sys.stderr)
                continue

            data = resp.json()
            extracted = data.get("extracted") or {}
            non_null = {k: v for k, v in extracted.items() if v not in (None, "", [])}

            if non_null:
                hallucinations.append((stem, non_null))
            else:
                clean.append(stem)

    print("=" * 60)
    print(f"Probed {len(clean) + len(hallucinations)} pure-null cases")
    print(f"  ✓ {len(clean)} returned all null (clean)")
    print(f"  ✗ {len(hallucinations)} returned non-null fields (hallucinations)")
    print("=" * 60)

    if clean:
        print("\nCLEAN (extractor correctly returned all null):")
        for stem in clean:
            print(f"  ✓ {stem}")

    if hallucinations:
        print("\nHALLUCINATIONS (extractor returned values for pure-null docs):")
        for stem, fields in hallucinations:
            print(f"\n  ✗ {stem}")
            for k, v in fields.items():
                print(f"      {k}: {v!r}")
        print()
        print("File each unique hallucination class as an oss task if not already tracked.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
