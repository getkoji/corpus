# Parse-provider evaluation harness (PB-3)

> Status: **introduced 2026-06-28 (accuracy-32 / PB-3).** The shared acceptance
> gate for every parse provider (PB-4..8). Script:
> [`scripts/parse_eval_harness.py`](../scripts/parse_eval_harness.py). Tests:
> [`scripts/test_parse_eval_harness.py`](../scripts/test_parse_eval_harness.py).

## What it measures

One question, asked fairly across many parse providers:

> Given the **same** source documents and the **same** extract config, which
> parse provider produces field values closest to ground truth?

```
bundle source → [swap ONLY the parse provider] → same extract
(model/prompt/chunk logic) → final field values → score vs truth.json
```

The score is **end-to-end field-value accuracy** and is **representation-
agnostic**: it compares the *extracted field values* against the *ground-truth
field values* (`truth.json`). It never compares markdown to JSON, so a
markdown-native provider (docling, Mistral, Azure-layout) and a JSON-native
provider (Google Doc AI, Textract) are scored on exactly the same axis. A
provider that garbles a dec-page column shows up as a plain accuracy drop — no
expensive structural ground truth required.

Everything except the parse provider is held constant: the extract engine,
model, prompt, and chunk logic are identical for every provider.

## How a provider plugs in (the contract for PB-4..8)

A **provider** maps to a cached representation already stored in each doc
bundle:

```
<category>/docs/<doc-id>/parsed/<provider>-<representation>.{md,json}
```

The docling baseline reads `parsed/docling-markdown.md` (the frozen academic md
snapshot). When your driver (PB-4..8) lands, cache its parse output into the
bundles under your `<provider>-<representation>` name (with the usual
`*.meta.json` sidecar — see [`bundle-layout.md`](./bundle-layout.md)), then
register it in `scripts/parse_eval_harness.py` with **one line**:

```python
# in PROVIDERS, parse_eval_harness.py
PROVIDERS["mistral"]      = CachedRepresentationProvider("mistral", "markdown")   # PB-4
PROVIDERS["azure-di"]     = CachedRepresentationProvider("azure-di", "markdown")  # PB-5
PROVIDERS["positional"]   = CachedRepresentationProvider("positional", "markdown")# PB-6
PROVIDERS["google-docai"] = CachedRepresentationProvider("google-docai", "json")  # PB-7
PROVIDERS["textract"]     = CachedRepresentationProvider("textract", "json")      # PB-8
```

That's the whole contract. The runner, scorer, and report pick it up
automatically. A provider that isn't cached for a given bundle is reported as
`skipped` for that bundle (not an error), so providers can be added
incrementally as they cache more of the corpus.

**"Done" for any driver = green on this harness over the standard suite.**
One harness, every provider scored identically.

### JSON-native providers

JSON representations are serialized to the text view the extract engine consumes
(parse-strategy: "markdown is a derived view"). Today `CachedRepresentationProvider`
passes the cached file's text straight through; a JSON provider that needs a
specific serialization can subclass it and override `parse()` to emit the text
the engine should see, while still being scored on field values.

### Live (non-cached) providers

If you want to parse live source bytes instead of reading a cached file, add a
provider class with the same `.parse(bundle) -> ParseResult` shape that calls
your driver/endpoint and populates `parse_ms`/`cost_usd`. Most bundles have no
source bytes yet (`source.retrieved: false`), so the cached-representation path
is the default; caching your parse into the corpus also makes runs reproducible
and free.

## The extract step (held constant)

Extraction runs through the real Koji extract engine via the `koji-extract`
service — the same contract `koji bench` uses:

```
POST {extract-url}/extract   {markdown, schema_def, model?, strategy?}
  → {extracted, model, elapsed_ms}
```

The backend (`ExtractBackend`) is injectable, so the test suite exercises the
full pipeline (discover → provider → extract → score → aggregate → report)
deterministically with no live model.

## Running it

```bash
# baseline docling over the whole sample suite
python scripts/parse_eval_harness.py --providers docling \
    --extract-url http://127.0.0.1:9412 --model openai/gpt-4o-mini --strategy intelligent

# compare providers, one category, JSON report for the dashboard
python scripts/parse_eval_harness.py --providers docling,mistral \
    --category receipts --json -o report.json

# slice by quality tier
python scripts/parse_eval_harness.py --providers docling --quality scan
```

Extract-URL resolution: `--extract-url` → `KOJI_EXTRACT_URL` env →
`http://127.0.0.1:9412` (the local koji-extract sidecar). Model and strategy are
pinned for reproducibility.

The report is emitted per **provider × doc-type** (doc-type = the bundle quality
tag: digital / scan / fax / mixed) and per **provider × category** (domain),
each with accuracy, mean parse latency, mean extract latency, and parse cost
(`n/a` when a cached representation has no recorded parse cost). A machine-
readable JSON form (`--json` / `-o`) feeds the accuracy dashboard and CI.

## Baseline result (2026-06-28)

docling baseline over the 8 PB-0 sample bundles, `openai/gpt-4o-mini`,
`intelligent` strategy: **97.6% (40/41 fields), 0 errors**. Full report:
[`.benchmarks/2026-06-28/parse-eval/docling.json`](../.benchmarks/2026-06-28/parse-eval/docling.json).
The single miss is a medical-records `procedures` array length mismatch — a real
extract result, reported honestly (not a harness bug). This is the number every
other provider is measured against.

## Relationship to `koji bench` / `score.py`

`koji bench` and the legacy `scripts/score.py` score extraction over the legacy
`documents/`/`expected/` layout with parse held implicitly constant (the baked
markdown). This harness scores over the **bundle** layout with the **parse
provider as the variable**. The two coexist until the corpus fully migrates to
bundles; this harness is the one that gates parse providers.
