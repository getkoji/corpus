#!/usr/bin/env python3
"""Pilot for the render/degrade ablation (BR-0b Track A).

Builds one shadow corpus per ladder level so exp-m1.ts can be run against each,
unchanged, with extract held constant:

    /tmp/ladder-eval/<level>/<category>/{documents,expected,schemas}

L0 documents are the corpus markdown as-is (the control). L1/L2/L3 documents are
the generated PDFs pushed through the real parse service, so the only thing that
varies between levels is how degraded the input was.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

CORPUS = pathlib.Path("/Users/trankly/dev/koji/playbook/corpus")
LADDER = pathlib.Path("/tmp/ladder-pilot/pdfs")
OUT = pathlib.Path("/tmp/ladder-eval")
PARSE_URL = "http://127.0.0.1:9411/parse"
CATEGORIES = ["invoices", "insurance_certificates", "medical_records"]
PER_CAT = 4
LEVELS = ["L1_native", "L2_raster", "L3_scan"]


def parse_pdf(path: pathlib.Path, timeout=600) -> str:
    """POST a PDF to the parse service, return markdown."""
    boundary = "----ladderpilot"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode()
        + path.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        PARSE_URL,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r).get("markdown") or ""


def main() -> int:
    print("=== 1. generating ladders ===", flush=True)
    cmd = [
        sys.executable,
        "scripts/render_degrade.py",
        "--limit",
        str(PER_CAT),
        "--out",
        str(LADDER),
    ]
    for c in CATEGORIES:
        cmd += ["--category", c]
    subprocess.run(cmd, cwd=CORPUS, check=True)

    docs = sorted(LADDER.glob("*/*"))
    print(f"\n=== 2. parsing {len(docs)} docs x {len(LEVELS)} levels ===", flush=True)

    for level in ["L0_markdown"] + LEVELS:
        for cat in CATEGORIES:
            for sub in ("documents", "expected", "schemas"):
                (OUT / level / cat / sub).mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    done = fail = 0
    for doc_dir in docs:
        cat, doc_id = doc_dir.parent.name, doc_dir.name
        # ground truth + schema are identical across levels — that is the whole design
        exp_src = CORPUS / cat / "expected" / f"{doc_id}.expected.json"
        if not exp_src.exists():
            print(f"  skip {cat}/{doc_id}: no expected", flush=True)
            continue
        for level in ["L0_markdown"] + LEVELS:
            dest = OUT / level / cat
            shutil.copy(exp_src, dest / "expected" / exp_src.name)
            for y in (CORPUS / cat / "schemas").glob("*.yaml"):
                shutil.copy(y, dest / "schemas" / y.name)

        # L0 control: the corpus markdown, untouched
        shutil.copy(
            CORPUS / cat / "documents" / f"{doc_id}.md",
            OUT / "L0_markdown" / cat / "documents" / f"{doc_id}.md",
        )
        for level in LEVELS:
            pdf = doc_dir / f"{level}.pdf"
            target = OUT / level / cat / "documents" / f"{doc_id}.md"
            if target.exists():
                done += 1
                continue
            try:
                el = time.time()
                md = parse_pdf(pdf)
                target.write_text(md)
                done += 1
                print(
                    f"  [{done}/{len(docs) * 3}] {cat}/{doc_id} {level}: "
                    f"{len(md)} chars in {time.time() - el:.0f}s",
                    flush=True,
                )
            except Exception as e:
                fail += 1
                print(
                    f"  FAIL {cat}/{doc_id} {level}: {type(e).__name__}: {e}",
                    flush=True,
                )

    print(
        f"\nparsed {done} ok, {fail} failed, {time.time() - t0:.0f}s total", flush=True
    )
    for level in ["L0_markdown"] + LEVELS:
        n = len(list((OUT / level).glob("*/documents/*.md")))
        chars = sum(len(p.read_text()) for p in (OUT / level).glob("*/documents/*.md"))
        print(f"  {level:<14} {n:>3} docs  {chars:>8} chars", flush=True)
    print(f"\nshadow corpora -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
