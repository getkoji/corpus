#!/usr/bin/env python3
"""Pipe every source file in multi_format/sources/ through koji parse.

The bench reads markdown from `documents/*.md`, so we need a
deterministic way to (re)populate `documents/` from the binary
source files committed in `sources/`. This script runs each source
through `/api/parse` on a running koji cluster and writes the
returned markdown as `documents/<stem>.md`. Run it any time the
source files change or after a parse-service update to verify
docling still produces the same markdown.

Dependencies: httpx. Run via uv:

    uv run --with httpx python scripts/reparse_multi_format.py

Requires:
    - A running koji cluster reachable at http://127.0.0.1:9401
    - OPENAI_API_KEY not strictly required (parse is docling, not LLM)
"""
from __future__ import annotations

import mimetypes
import sys
from pathlib import Path

import httpx

CORPUS_ROOT = Path(__file__).resolve().parent.parent
CATEGORY_DIR = CORPUS_ROOT / "multi_format"
SOURCES_DIR = CATEGORY_DIR / "sources"
DOCUMENTS_DIR = CATEGORY_DIR / "documents"

DEFAULT_SERVER_URL = "http://127.0.0.1:9401"
PARSE_TIMEOUT = 600.0


def guess_content_type(path: Path) -> str:
    """Best-effort content type. Falls back to the generic binary type."""
    mt, _ = mimetypes.guess_type(path.name)
    if mt:
        return mt
    # mimetypes sometimes misses modern office formats on older Python builds
    suffix = path.suffix.lower()
    extra = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    return extra.get(suffix, "application/octet-stream")


def parse_source(path: Path, server_url: str, client: httpx.Client) -> str | None:
    """POST a single source file to /api/parse and return the markdown."""
    content_type = guess_content_type(path)
    files = {"file": (path.name, path.read_bytes(), content_type)}
    try:
        resp = client.post(f"{server_url}/api/parse", files=files)
    except httpx.RequestError as exc:
        print(f"[reparse] {path.name}: request error: {exc}", file=sys.stderr)
        return None
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", resp.text[:200])
        except Exception:
            err = resp.text[:200]
        print(f"[reparse] {path.name}: HTTP {resp.status_code}: {err}", file=sys.stderr)
        return None
    body = resp.json()
    md = body.get("markdown") or ""
    if not md.strip():
        print(f"[reparse] {path.name}: parse returned empty markdown", file=sys.stderr)
        return None
    return md


def main() -> int:
    server_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SERVER_URL
    if not SOURCES_DIR.is_dir():
        print(f"[reparse] no sources directory at {SOURCES_DIR}", file=sys.stderr)
        return 1

    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

    sources = sorted(SOURCES_DIR.iterdir())
    sources = [p for p in sources if p.is_file() and not p.name.startswith(".")]
    if not sources:
        print(f"[reparse] no source files in {SOURCES_DIR}", file=sys.stderr)
        return 0

    with httpx.Client(timeout=PARSE_TIMEOUT) as client:
        processed = 0
        failed = 0
        for src in sources:
            # Encode the source format in the output stem so docx/xlsx/pptx
            # versions of the same doc don't overwrite each other. The
            # manifest for each resulting markdown points back at its
            # source via the `source_filename` sidecar field.
            suffix = src.suffix.lstrip(".").lower()
            stem = f"{src.stem}_{suffix}" if suffix else src.stem
            out_path = DOCUMENTS_DIR / f"{stem}.md"
            print(f"[reparse] {src.name} -> {out_path.name}", file=sys.stderr)
            md = parse_source(src, server_url, client)
            if md is None:
                failed += 1
                continue
            out_path.write_text(md)
            processed += 1
            print(f"[reparse]   wrote {len(md)} chars", file=sys.stderr)

    print(
        f"\n[reparse] Done. Processed: {processed}, Failed: {failed}",
        file=sys.stderr,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
