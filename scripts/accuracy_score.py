#!/usr/bin/env python3
"""Score extraction predictions into a committed accuracy artifact (accuracy-40).

This is the *expensive* half of the accuracy table: it needs the canonical
fieldbench scorer and a predictions directory produced by running the corpus
through the extract engine. It writes a machine-readable results file with full
provenance. The README table is then generated from that file by
`accuracy_table.py`, which is stdlib-only so CI can verify it without a run.

Predictions layout (one flat {field: value} JSON per document):
    <preds>/<category>/<doc-stem>.json

Usage (run with the fieldbench venv):
    ~/dev/fieldbench/.venv/bin/python scripts/accuracy_score.py \
        --preds /tmp/acc40-preds --model gpt-4o-mini --koji-sha <sha> \
        --out .benchmarks/accuracy-2026-07-23.json
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path.home() / "dev/fieldbench/src"))
try:
    from fieldbench import SCORER_VERSION, score_corpus
except ImportError:
    sys.exit("fieldbench not importable — run with ~/dev/fieldbench/.venv/bin/python")


def doc_is_synthetic(corpus: pathlib.Path, cat: str, stem: str) -> bool:
    """Classify real vs synthetic the same way composition_report.py does.

    fieldbench derives this from the format string ("synth" in original_format),
    but this corpus records synthetic-ness in source_name while leaving the
    format as plain "markdown" — so fieldbench's own classifier mislabels every
    synthetic doc as real. Read source_name directly.
    """
    man = corpus / cat / "manifests" / f"{stem}.json"
    if not man.exists():
        return False
    src = json.loads(man.read_text()).get("source_name") or ""
    return ("ynthetic" in src) or ("Hand-crafted" in src) or src.startswith("Koji ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preds", type=pathlib.Path, required=True)
    ap.add_argument("--corpus", type=pathlib.Path, default=pathlib.Path("."))
    ap.add_argument("--model", required=True)
    ap.add_argument("--koji-sha", default="unknown")
    ap.add_argument("--date", required=True, help="run date YYYY-MM-DD (provenance)")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()

    categories = sorted(p.name for p in args.preds.iterdir() if p.is_dir())
    if not categories:
        sys.exit(f"no category dirs under {args.preds}")

    cats_out = {}
    tot_fields = tot_pass = tot_docs = 0
    for cat in categories:
        # score_corpus scores the WHOLE category's expected set; restrict to the
        # documents we actually produced predictions for (a capped run must not have
        # its un-run documents counted as all-null misses). Every doc we ran wrote a
        # prediction file (failures wrote {}), so `predicted` is exactly the run set.
        predicted = {p.stem for p in (args.preds / cat).glob("*.json")}
        if not predicted:
            continue
        all_docs, _ = score_corpus(args.corpus, args.preds / cat, category=cat)
        docs = [d for d in all_docs if d.stem in predicted]
        # A prediction with no matching expected doc means a stem mismatch — surface it.
        missing = len(predicted) - len(docs)
        if not docs:
            continue
        flat = [f for d in docs for f in d.fields]
        synth_stems = {
            d.stem for d in docs if doc_is_synthetic(args.corpus, cat, d.stem)
        }
        real = [f for d in docs if d.stem not in synth_stems for f in d.fields]
        synth = [f for d in docs if d.stem in synth_stems for f in d.fields]

        def acc(fs):
            return (
                round(sum(1 for f in fs if f.passed) / len(fs) * 100, 1) if fs else None
            )

        cats_out[cat] = {
            "documents": len(docs),
            "fields": len(flat),
            "passed": sum(1 for f in flat if f.passed),
            "accuracy": acc(flat),
            "real_accuracy": acc(real),
            "synthetic_accuracy": acc(synth),
            "missing_predictions": missing,
        }
        tot_fields += len(flat)
        tot_pass += sum(1 for f in flat if f.passed)
        tot_docs += len(docs)

    result = {
        "scorer": f"fieldbench {SCORER_VERSION}",
        "model": args.model,
        "koji_sha": args.koji_sha,
        "date": args.date,
        "note": (
            "Per-category N is capped (see documents field); numbers are scoped to "
            "that sample. Regenerate the README table with accuracy_table.py."
        ),
        "total": {
            "documents": tot_docs,
            "fields": tot_fields,
            "passed": tot_pass,
            "accuracy": round(tot_pass / tot_fields * 100, 1) if tot_fields else None,
        },
        "categories": cats_out,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    # Maintain a stable pointer the generator + CI read.
    (args.out.parent / "accuracy-latest.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    miss = sum(c["missing_predictions"] for c in cats_out.values())
    print(f"scored {tot_docs} docs, {tot_fields} fields -> {args.out}")
    print(
        f"overall {result['total']['accuracy']}%  ({len(cats_out)} categories, {miss} missing)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
