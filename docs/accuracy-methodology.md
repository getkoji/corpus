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

## Declared equivalence policy (`match:`) — accuracy-48

Whether two values count as the same is a judgement, and since koji 0.115.0 the corpus
schemas state theirs explicitly with a per-field `match:` key instead of leaving it to
whichever scorer runs (see koji's `docs/schema-guide.md`, "Scoring equivalence").
`normalized` remains the default for every field, so a field with no `match:` scores
exactly as it did before.

What the corpus declares, and why:

| Mode | Fields | Rationale |
|------|--------|-----------|
| `contains` | `contracts/governing_law`, `legal_filings/{plaintiff,defendant}` | The document states the value inside a wrapper the field does not want — a governing-law clause ("the laws of the State of Delaware") or a caption party ("HOWARD LUTNICK, et al.", "TODD BLANCHE, Acting Attorney General"). |
| `date` | every `type: date` field with measured coverage | `normalized` falls back to a quantity comparison when one side does not parse as a date, so expected `2026` scores as a **match** against extracted `2026-05-01` (both read as 2026). `date` closes that. |
| `numeric` + `tolerance: 0.02` | `receipts/total_amount` | SROIE receipts carry a "Rounding adj −0.01" line, so the printed and payable totals legitimately differ by a cent. The default 0.01 tolerance is meant to forgive that and misses it to floating point. |
| `enum` | the five enum fields (`contract_type`, `filing_type`, `policy_type`, both `form_type`s) | Scores against the declared vocabulary, so `claim_form.yaml`'s `mappings` aliases ("Sworn Statement in Proof of Loss" → "Proof of Loss") count as equal. Measured zero-delta: all 678 enum ground-truth values in the corpus are already in-vocabulary. |

`contains` is permissive on purpose — it accepts any substring. Where it would have
recovered failures but masked real extraction errors it is **deliberately not declared**,
and the reason sits in a comment on the field itself (`case_number`, `judge`,
`filer_name`, `sec_filings/form_type`, `primary_diagnosis`, `employer_name`,
`named_insured`, `certificate_holder_name`, `description_of_loss`,
`receipts/merchant_name`). Read those before loosening a field.

### Which scorers honour it

`match:` is read by `@koji/score`, which backs `koji score` and `koji validate`. The
README accuracy table is produced by the **fieldbench** scorer, whose `score_field` takes
`mappings` and `enum_options` but has no `match` parameter — so declaring a policy here
does **not** move the README numbers. Verify a declaration with the scorer that reads it:

```bash
koji score --expected <doc>.expected.json --actual <extracted>.json \
           --schema <category>/schemas/<schema>.yaml --json
```
