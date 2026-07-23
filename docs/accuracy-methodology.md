# Accuracy table — how it is produced (accuracy-40)

The per-category accuracy numbers in the README are **generated from a real run**, not
hand-maintained. This exists because the old numbers were typed in by hand with no
reproducible source — the newest committed benchmark was a 3-document run, and a
spot-recompute found `medical_records` at 65.8% against a claimed 97.7%.

The pipeline is split into an expensive half and a cheap half so CI can keep the README
honest without ever running extraction.

```
             EXPENSIVE (manual, needs a model + fieldbench)          CHEAP (CI, stdlib only)
  corpus ──► extract engine ──► predictions ──► accuracy_score.py ──► accuracy-latest.json ──► accuracy_table.py
             (run-accuracy.ts)   (per doc)      (fieldbench)          (committed artifact)      render / write / check
```

## 1. Produce predictions (extract engine)

Predictions are one flat `{field: value}` JSON per document, under
`<preds>/<category>/<doc-stem>.json`. The reference runner is
[`scripts/run-accuracy.ts`](../scripts/run-accuracy.ts) — it imports the **production**
`intelligentExtract` engine and runs it over `<corpus>/<cat>/{documents,expected,schemas}`,
so the numbers reflect the real engine, not a reimplementation. It is TypeScript because
the engine is; copy it into a `getkoji/koji` checkout to run it against that engine (the
same pattern the koji extraction experiments use):

```bash
# from a koji checkout at the commit you want to measure
cp /path/to/corpus/scripts/run-accuracy.ts api/src/extract/
set -a; . /path/to/.env; set +a          # OPENAI_API_KEY
RUN_DATE=2026-07-23 LIMIT=40 CONC=4 \
  node_modules/.bin/tsx src/extract/run-accuracy.ts /path/to/corpus /tmp/acc-preds
```

`LIMIT` caps documents per category (0 = all). The README table reports the N actually
scored, so a capped run is honest — it is a sample, labelled as one.

## 2. Score (fieldbench → committed artifact)

```bash
~/dev/fieldbench/.venv/bin/python scripts/accuracy_score.py \
    --preds /tmp/acc-preds --model gpt-4o-mini --date 2026-07-23 \
    --koji-sha "$(git -C /path/to/koji rev-parse HEAD)" \
    --out .benchmarks/accuracy-2026-07-23.json
```

This scores every category with the canonical fieldbench scorer (four-way null semantics,
not the lenient `koji bench` scorer) and writes a machine-readable results file plus a
stable `.benchmarks/accuracy-latest.json` pointer, both carrying full provenance: model,
koji SHA, scorer version, date, and per-category N / real / synthetic accuracy.

Missing predictions are scored as all-null, never skipped, so a failed document can't
inflate a score. `missing_predictions` is recorded per category.

## 3. Generate / verify the README table

```bash
python3 scripts/accuracy_table.py write     # splice the table into README.md
python3 scripts/accuracy_table.py check      # CI: exit 1 if README drifts from the artifact
```

`accuracy_table.py` is **stdlib-only** and reads only the committed
`.benchmarks/accuracy-latest.json` — it never runs extraction. The table lives between
`<!-- ACCURACY-TABLE:START -->` / `<!-- ACCURACY-TABLE:END -->` markers so it is replaced
and checked deterministically. CI runs `check`, so the numbers can never silently drift
from the artifact again (the exact failure mode this replaces).

## What the numbers do and do not mean

- **Scoped to the run.** A number is `model × koji-sha × scored-N`. Change any of those and
  regenerate — the provenance line in the table records all three.
- **Composition still applies.** Most of the corpus is clean text (see
  [`composition.md`](composition.md)), so these are extraction-from-text numbers, not
  document-extraction numbers. The render/degrade ladder ([`render-degrade-ladder.md`](render-degrade-ladder.md))
  quantifies that gap separately.
- **Not a leaderboard.** This is Koji's own accuracy over its own corpus, for regression
  visibility. Cross-system comparison belongs to the external-baselines work.
