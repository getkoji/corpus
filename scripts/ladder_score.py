#!/usr/bin/env python3
"""Score the render/degrade ladder with the canonical fieldbench scorer.

exp-m1 emits one JSON per level holding raw extracted values. This converts each
into fieldbench's prediction layout and scores every level against ONE scoring
corpus — expected/manifests/schemas are identical across levels by construction,
so only the predictions differ.

Run with the fieldbench venv:
    ~/dev/fieldbench/.venv/bin/python score_ladder.py
"""

import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path.home() / "dev/fieldbench/src"))
from fieldbench import SCORER_VERSION, score_corpus  # noqa: E402

CORPUS = pathlib.Path("/Users/trankly/dev/koji/playbook/corpus")
EVAL = pathlib.Path("/tmp/ladder-eval")
SCORING = EVAL / "_scoring"
PREDS = EVAL / "_preds"
LEVELS = ["L0_markdown", "L1_native", "L2_raster", "L3_scan"]


def build_scoring_corpus():
    """expected + manifests + schemas for exactly the piloted documents."""
    stems = {}
    for md in (EVAL / "L0_markdown").glob("*/documents/*.md"):
        stems.setdefault(md.parts[-3], []).append(md.stem)
    if SCORING.exists():
        shutil.rmtree(SCORING)
    for cat, ss in stems.items():
        # documents/ must exist for discover_categories() to see the category at all;
        # the scorer never reads it (it compares predictions to expected).
        for sub in ("expected", "manifests", "schemas", "documents"):
            (SCORING / cat / sub).mkdir(parents=True, exist_ok=True)
        for s in ss:
            shutil.copy(
                EVAL / "L0_markdown" / cat / "documents" / f"{s}.md",
                SCORING / cat / "documents" / f"{s}.md",
            )
        for y in (CORPUS / cat / "schemas").glob("*.yaml"):
            shutil.copy(y, SCORING / cat / "schemas" / y.name)
        for s in ss:
            shutil.copy(
                CORPUS / cat / "expected" / f"{s}.expected.json",
                SCORING / cat / "expected" / f"{s}.expected.json",
            )
            man = CORPUS / cat / "manifests" / f"{s}.json"
            if man.exists():
                shutil.copy(man, SCORING / cat / "manifests" / f"{s}.json")
            else:
                print(f"  WARNING no manifest: {cat}/{s} (will be skipped by scorer)")
    return stems


def write_predictions(level: str, arm: str) -> int:
    """exp-m1 output -> fieldbench prediction files."""
    raw = EVAL / f"{level}.json"
    if not raw.exists():
        return -1
    payload = json.loads(raw.read_text())
    out = PREDS / level
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for rec in payload.get("data", []):
        stem = rec["document"].removesuffix(".md")
        arms = rec.get("arms", {})
        entry = arms.get(arm) or (next(iter(arms.values())) if arms else None)
        if entry is None:
            continue
        # A failed extraction is written as {} (all-null), never skipped — otherwise
        # a level that errored would look like a level that scored well.
        (out / f"{stem}.json").write_text(
            json.dumps(entry.get("values") or {}, indent=2)
        )
        n += 1
    return n


def main() -> int:
    arm = sys.argv[1] if len(sys.argv) > 1 else "openai:gpt-4o-mini"
    stems = build_scoring_corpus()
    total = sum(len(v) for v in stems.values())
    print(f"scoring corpus: {total} docs across {len(stems)} categories")
    print(f"scorer: fieldbench {SCORER_VERSION}\n")

    rows = []
    for level in LEVELS:
        n = write_predictions(level, arm)
        if n < 0:
            print(f"{level:<14} NOT RUN (missing {EVAL / f'{level}.json'})")
            continue
        docs, missing = score_corpus(SCORING, PREDS / level)
        if not docs:
            print(f"{level:<14} no documents scored")
            continue
        flat = [f for d in docs for f in d.fields]
        acc = sum(1 for f in flat if f.passed) / len(flat) * 100
        buckets = {}
        for f in flat:
            buckets[f.bucket] = buckets.get(f.bucket, 0) + 1
        per_cat = {}
        for d in docs:
            c = per_cat.setdefault(d.category, [0, 0])
            c[0] += sum(1 for f in d.fields if f.passed)
            c[1] += len(d.fields)
        rows.append((level, acc, len(docs), len(flat), missing, per_cat, buckets))
        flag = f"  ⚠ {missing} MISSING PREDICTIONS" if missing else ""
        print(f"{level:<14} {acc:6.1f}%  ({len(docs)} docs, {len(flat)} fields){flag}")

    if len(rows) > 1:
        base = rows[0][1]
        print("\ndelta vs L0 (markdown control):")
        for level, acc, *_ in rows[1:]:
            print(f"  {level:<14} {acc - base:+6.1f}pp")
        print("\nper-category:")
        cats = sorted({c for r in rows for c in r[5]})
        print(
            f"  {'category':<26}"
            + "".join(f"{lv.split('_')[0]:>10}" for lv, *_ in rows)
        )
        for cat in cats:
            cells = ""
            for r in rows:
                ok, tot = r[5].get(cat, [0, 0])
                cells += f"{(ok / tot * 100 if tot else 0):>9.1f}%"
            print(f"  {cat:<26}{cells}")

        print("\nfour-way null semantics (field counts):")
        all_b = sorted({b for r in rows for b in r[6]})
        print(
            f"  {'bucket':<26}" + "".join(f"{lv.split('_')[0]:>10}" for lv, *_ in rows)
        )
        for b in all_b:
            print(f"  {b:<26}" + "".join(f"{r[6].get(b, 0):>10}" for r in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
