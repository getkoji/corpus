#!/usr/bin/env python3
"""Parse-provider evaluation harness (PB-3) — the shared acceptance gate.

This is the corpus-matrix runner described in
``playbook/docs/parse-strategy.md`` → "Evaluation harness — the corpus as a
matrix". It answers one question, fairly, across many parse providers:

    Given the *same* source documents and the *same* extract config, which
    parse provider produces field values closest to ground truth?

How it works (everything-else-held-constant):

    bundle source  →  [swap ONLY the parse provider]  →  same extract
    (model/prompt/chunk logic)  →  final field values  →  score vs truth.json

The score is **end-to-end field-value accuracy** and is **representation-
agnostic**: we compare the *extracted field values* to the *ground-truth field
values*. We never compare markdown to JSON, so a markdown provider and a
JSON-native provider are scored on exactly the same axis. This is what lets the
harness catch e.g. the dec-page wrong-column bug as a plain accuracy drop with
no expensive structural ground truth.

────────────────────────────────────────────────────────────────────────────
ADDING A NEW PROVIDER IS A ONE-LINER
────────────────────────────────────────────────────────────────────────────

A "provider" maps to a cached representation in each doc bundle
(``<category>/docs/<doc-id>/parsed/<provider>-<representation>.{md,json}``).
Once PB-4..8 land and cache their parses into the corpus, registering them here
is a single line in ``PROVIDERS`` below:

    PROVIDERS["mistral"]     = CachedRepresentationProvider("mistral", "markdown")
    PROVIDERS["azure-di"]    = CachedRepresentationProvider("azure-di", "markdown")
    PROVIDERS["google-docai"] = CachedRepresentationProvider("google-docai", "json")

That's the entire contract. The runner, scorer, and report pick the new
provider up automatically. A provider that isn't cached for a given bundle is
reported as ``skipped`` for that bundle (not an error) so providers can be
added incrementally as they cache more of the corpus.

────────────────────────────────────────────────────────────────────────────
EXTRACT IS HELD CONSTANT
────────────────────────────────────────────────────────────────────────────

The extract step runs through the real Koji extract engine via the
``koji-extract`` service (``POST /extract`` with ``{markdown, schema_def}`` —
the same contract ``koji bench`` uses). Model, prompt, and chunk logic are
identical for every provider — only the parsed text varies. The backend is
injectable (``ExtractBackend``) so tests can run the full pipeline
deterministically without a live model.

Usage:
    # baseline docling over the whole sample, against the extract service
    python scripts/parse_eval_harness.py --providers docling \
        --extract-url http://127.0.0.1:9412 --model openai/gpt-4o-mini

    # compare providers, one category, JSON report for the dashboard
    python scripts/parse_eval_harness.py --providers docling,mistral \
        --category receipts --json -o report.json

Extract-URL resolution (in order): ``--extract-url`` flag → ``KOJI_EXTRACT_URL``
env → ``http://127.0.0.1:9412`` (the local koji-extract sidecar default).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Protocol

CORPUS_ROOT = Path(__file__).resolve().parent.parent
QUALITY_TAGS = ("digital", "scan", "fax", "mixed")


# ════════════════════════════════════════════════════════════════════════
# Bundle discovery
# ════════════════════════════════════════════════════════════════════════


@dataclass
class Bundle:
    """A doc-bundle: the representation-independent unit the harness scores."""

    path: Path
    meta: dict

    @property
    def doc_id(self) -> str:
        return self.meta.get("doc_id", self.path.name)

    @property
    def category(self) -> str:
        return self.meta.get("category", self.path.parent.parent.name)

    @property
    def quality(self) -> str:
        return self.meta.get("quality", "unknown")

    @property
    def schema_path(self) -> Path:
        return CORPUS_ROOT / self.meta["schema"]

    @property
    def truth_path(self) -> Path:
        return self.path / (self.meta.get("truth", {}).get("file", "truth.json"))

    def representation_meta(self, provider: str) -> dict | None:
        """Sidecar meta for a provider's cached representation, if present."""
        for rep in self.meta.get("representations", []):
            if rep.get("provider") == provider:
                return rep
        return None


def discover_bundles(
    category: str | None = None,
    quality: str | None = None,
    doc_id: str | None = None,
) -> list[Bundle]:
    """Find doc-bundles, optionally filtered. Mirrors validate_bundles.py glob."""
    pattern = f"{category}/docs/*/meta.json" if category else "*/docs/*/meta.json"
    bundles: list[Bundle] = []
    for meta_path in sorted(CORPUS_ROOT.glob(pattern)):
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:  # noqa: BLE001
            continue
        b = Bundle(path=meta_path.parent, meta=meta)
        if quality and b.quality != quality:
            continue
        if doc_id and b.doc_id != doc_id:
            continue
        bundles.append(b)
    return bundles


# ════════════════════════════════════════════════════════════════════════
# Parse providers — the ONE thing that varies
# ════════════════════════════════════════════════════════════════════════


@dataclass
class ParseResult:
    """Output of a parse provider for one bundle."""

    text: str | None
    representation: str
    parse_ms: int | None = None
    cost_usd: float | None = None
    skipped: bool = False
    reason: str = ""


class Provider(Protocol):
    name: str
    representation: str

    def parse(self, bundle: Bundle) -> ParseResult: ...


@dataclass
class CachedRepresentationProvider:
    """Provider backed by a cached parse already in the corpus matrix.

    This is how every provider plugs in: the corpus stores
    ``parsed/<provider>-<representation>.{md,json}`` per bundle (the docling
    baseline today; PB-4..8 cache theirs as they land). The harness reads the
    cached text, so scoring needs no cloud spend and no re-parse. Parse latency
    and cost are read from the representation sidecar when recorded.
    """

    name: str
    representation: str = "markdown"

    @property
    def _ext(self) -> str:
        return "json" if self.representation == "json" else "md"

    def parse(self, bundle: Bundle) -> ParseResult:
        rep_file = (
            bundle.path / "parsed" / f"{self.name}-{self.representation}.{self._ext}"
        )
        if not rep_file.is_file():
            return ParseResult(
                text=None,
                representation=self.representation,
                skipped=True,
                reason=f"no cached {self.name}-{self.representation} parse",
            )
        rep_meta = bundle.representation_meta(self.name) or {}
        sidecar = rep_file.with_suffix(rep_file.suffix + ".meta.json")
        parse_ms = rep_meta.get("parse_ms")
        cost = rep_meta.get("cost_usd")
        if sidecar.is_file():
            try:
                sc = json.loads(sidecar.read_text())
                parse_ms = sc.get("parse_ms", parse_ms)
                cost = sc.get("cost_usd", cost)
            except Exception:  # noqa: BLE001
                pass
        return ParseResult(
            text=rep_file.read_text(),
            representation=self.representation,
            parse_ms=parse_ms,
            cost_usd=cost,
        )


# ── Provider registry — ADD A PROVIDER HERE (one line). ──────────────────
PROVIDERS: dict[str, Provider] = {
    # The existing docling parse, frozen into the corpus as the academic md
    # snapshot. The baseline every other provider is measured against.
    "docling": CachedRepresentationProvider("docling", "markdown"),
    # PB-4: PROVIDERS["mistral"]      = CachedRepresentationProvider("mistral", "markdown")
    # PB-5: PROVIDERS["azure-di"]     = CachedRepresentationProvider("azure-di", "markdown")
    # PB-6: PROVIDERS["positional"]   = CachedRepresentationProvider("positional", "markdown")
    # PB-7: PROVIDERS["google-docai"] = CachedRepresentationProvider("google-docai", "json")
    # PB-8: PROVIDERS["textract"]     = CachedRepresentationProvider("textract", "json")
}


# ════════════════════════════════════════════════════════════════════════
# Extract backend — HELD CONSTANT (same engine/model/prompt/chunk logic)
# ════════════════════════════════════════════════════════════════════════


@dataclass
class ExtractResult:
    fields: dict[str, Any] | None
    extract_ms: int = 0
    model: str | None = None
    cost_usd: float | None = None
    error: str | None = None


class ExtractBackend(Protocol):
    def extract(
        self, text: str, schema_def: dict, representation: str
    ) -> ExtractResult: ...


class HttpExtractBackend:
    """Calls the real Koji extract engine via the koji-extract service.

    Same contract ``koji bench`` uses: ``POST {extract_url}/extract`` with
    ``{markdown, schema_def, model?, strategy?}`` → ``{extracted, model,
    elapsed_ms}``. The parsed text is sent in the ``markdown`` field regardless
    of the source representation — a JSON-native provider serializes its
    structured form to the text view the engine consumes (parse-strategy:
    "markdown is a derived view"). Held constant across providers: the engine,
    model, prompt, and chunk logic. Only the parsed text varies.
    """

    def __init__(
        self,
        extract_url: str,
        model: str | None,
        strategy: str | None = None,
        timeout: float = 1800.0,
    ):
        self.extract_url = extract_url.rstrip("/")
        if not self.extract_url.endswith("/extract"):
            self.extract_url = f"{self.extract_url}/extract"
        self.model = model
        self.strategy = strategy
        self.timeout = timeout
        import httpx  # local import so the module imports without httpx for tests

        self._client = httpx.Client(timeout=timeout)

    def extract(
        self, text: str, schema_def: dict, representation: str
    ) -> ExtractResult:
        payload: dict[str, Any] = {"markdown": text, "schema_def": schema_def}
        if self.model:
            payload["model"] = self.model
        if self.strategy:
            payload["strategy"] = self.strategy
        started = time.time()
        try:
            resp = self._client.post(self.extract_url, json=payload)
        except Exception as e:  # noqa: BLE001
            return ExtractResult(fields=None, error=f"extract request failed: {e}")
        elapsed_ms = int((time.time() - started) * 1000)
        if resp.status_code != 200:
            try:
                msg = resp.json().get("error", f"HTTP {resp.status_code}")
            except Exception:  # noqa: BLE001
                msg = resp.text[:200] or f"HTTP {resp.status_code}"
            return ExtractResult(fields=None, extract_ms=elapsed_ms, error=msg)
        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            return ExtractResult(
                fields=None, extract_ms=elapsed_ms, error=f"bad response: {e}"
            )
        return ExtractResult(
            fields=_unwrap_extracted(data),
            extract_ms=data.get("elapsed_ms", elapsed_ms),
            model=data.get("model"),
            cost_usd=data.get("cost_usd"),
        )

    def close(self) -> None:
        self._client.close()


def _unwrap_extracted(data: Any) -> dict | None:
    """Collapse the extract response to one field dict.

    Mirrors cli/bench.py::_unwrap_extracted — handles the flat shape
    ``{"extracted": {...}}`` and the classify-wrapped ``{"sections": [...]}``
    shape (empty → {}, one → that section, many → first-non-null union).
    """
    if not isinstance(data, dict):
        return None
    if "sections" in data and isinstance(data["sections"], list):
        sections = data["sections"]
        if not sections:
            return {}
        if len(sections) == 1:
            return sections[0].get("extracted") or {}
        merged: dict = {}
        for section in sections:
            fields = section.get("extracted")
            if not isinstance(fields, dict):
                continue
            for k, v in fields.items():
                if merged.get(k) is None and v is not None:
                    merged[k] = v
        return merged
    extracted = data.get("extracted")
    if isinstance(extracted, dict):
        return extracted
    return data


# ════════════════════════════════════════════════════════════════════════
# Representation-agnostic field-value scoring (null-aware + fuzzy)
# ════════════════════════════════════════════════════════════════════════
#
# Mirrors koji cli/test_runner.py's null-aware comparison: an expected-null
# field is satisfied by null/empty (no hallucination), a present field must be
# matched. Numbers compare with tolerance, dates by normalized form, strings
# exactly or by fuzzy ratio when the schema sets compare.fuzzy_threshold.


@dataclass
class FieldResult:
    name: str
    passed: bool
    expected: Any = None
    actual: Any = None
    detail: str = ""


def _normalize_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    return None


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def compare_field(
    name: str, expected: Any, actual: Any, fuzzy_threshold: float = 0.0
) -> FieldResult:
    # Null-aware: expected absent/null → must not hallucinate a value.
    if _is_empty(expected):
        ok = _is_empty(actual)
        return FieldResult(
            name,
            ok,
            expected,
            actual,
            "" if ok else f"hallucinated: expected null, got {actual!r}",
        )
    if _is_empty(actual):
        return FieldResult(name, False, expected, actual, "missing")

    exp_date, act_date = _normalize_date(expected), _normalize_date(actual)
    if exp_date is not None and act_date is not None:
        return FieldResult(name, exp_date == act_date, expected, actual)

    exp_num, act_num = _to_number(expected), _to_number(actual)
    if exp_num is not None and act_num is not None:
        ok = round(abs(exp_num - act_num), 10) <= 0.01
        return FieldResult(name, ok, expected, actual)

    if isinstance(expected, list) and isinstance(actual, list):
        ok = len(expected) == len(actual)
        return FieldResult(
            name,
            ok,
            expected,
            actual,
            "" if ok else f"length mismatch: {len(expected)} vs {len(actual)}",
        )

    if isinstance(expected, str) and isinstance(actual, str):
        e, a = expected.lower().strip(), actual.lower().strip()
        if e == a:
            return FieldResult(name, True, expected, actual)
        if fuzzy_threshold > 0:
            ratio = SequenceMatcher(None, e, a).ratio()
            if ratio >= fuzzy_threshold:
                return FieldResult(name, True, expected, actual, f"fuzzy {ratio:.2f}")
            return FieldResult(
                name, False, expected, actual, f"fuzzy {ratio:.2f} < {fuzzy_threshold}"
            )
        return FieldResult(name, False, expected, actual)

    return FieldResult(name, expected == actual, expected, actual)


def score(
    truth: dict, extracted: dict, fuzzy_threshold: float = 0.0
) -> list[FieldResult]:
    """Field-value vs field-value — representation never enters here."""
    return [
        compare_field(k, v, (extracted or {}).get(k), fuzzy_threshold)
        for k, v in truth.items()
    ]


# ════════════════════════════════════════════════════════════════════════
# Runner
# ════════════════════════════════════════════════════════════════════════


@dataclass
class DocResult:
    provider: str
    doc_id: str
    category: str
    quality: str
    fields: list[FieldResult] = field(default_factory=list)
    parse_ms: int | None = None
    extract_ms: int = 0
    parse_cost_usd: float | None = None
    skipped: bool = False
    error: str | None = None

    @property
    def passed(self) -> int:
        return sum(1 for f in self.fields if f.passed)

    @property
    def total(self) -> int:
        return len(self.fields)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0


def run_doc(
    provider: Provider,
    bundle: Bundle,
    backend: ExtractBackend,
) -> DocResult:
    res = DocResult(
        provider=provider.name,
        doc_id=bundle.doc_id,
        category=bundle.category,
        quality=bundle.quality,
    )
    parsed = provider.parse(bundle)
    res.parse_ms = parsed.parse_ms
    res.parse_cost_usd = parsed.cost_usd
    if parsed.skipped or parsed.text is None:
        res.skipped = True
        res.error = parsed.reason or "no parse"
        return res

    try:
        schema_text = bundle.schema_path.read_text()
        schema_def = _load_yaml(schema_text)
        truth = json.loads(bundle.truth_path.read_text())
    except Exception as e:  # noqa: BLE001
        res.error = f"setup: {e}"
        return res

    fuzzy = 0.0
    if isinstance(schema_def, dict):
        fuzzy = float((schema_def.get("compare") or {}).get("fuzzy_threshold", 0.0))

    out = backend.extract(parsed.text, schema_def, parsed.representation)
    res.extract_ms = out.extract_ms
    if out.error or out.fields is None:
        res.error = out.error or "no fields returned"
        return res

    res.fields = score(truth, out.fields, fuzzy)
    return res


def _load_yaml(text: str) -> Any:
    import yaml

    return yaml.safe_load(text)


def run(
    providers: list[Provider],
    bundles: list[Bundle],
    backend: ExtractBackend,
    progress: Callable[[str, str, int, int], None] | None = None,
) -> list[DocResult]:
    results: list[DocResult] = []
    total = len(providers) * len(bundles)
    i = 0
    for provider in providers:
        for bundle in bundles:
            i += 1
            if progress:
                progress(provider.name, bundle.doc_id, i, total)
            results.append(run_doc(provider, bundle, backend))
    return results


# ════════════════════════════════════════════════════════════════════════
# Aggregation + report (per provider × doc-type[=quality], + per category)
# ════════════════════════════════════════════════════════════════════════


def _mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def aggregate(results: list[DocResult], axis: str) -> dict[tuple[str, str], dict]:
    """Group by (provider, axis) where axis ∈ {'quality','category'}."""
    groups: dict[tuple[str, str], list[DocResult]] = {}
    for r in results:
        key = (r.provider, getattr(r, axis))
        groups.setdefault(key, []).append(r)

    out: dict[tuple[str, str], dict] = {}
    for key, rs in sorted(groups.items()):
        scored = [r for r in rs if not r.skipped and r.error is None]
        passed = sum(r.passed for r in scored)
        total_fields = sum(r.total for r in scored)
        out[key] = {
            "provider": key[0],
            axis: key[1],
            "docs": len(rs),
            "scored_docs": len(scored),
            "skipped": sum(1 for r in rs if r.skipped),
            "errors": sum(1 for r in rs if r.error and not r.skipped),
            "fields_checked": total_fields,
            "passed_fields": passed,
            "accuracy": (passed / total_fields) if total_fields else None,
            "mean_extract_ms": _mean([float(r.extract_ms) for r in scored]),
            "mean_parse_ms": _mean(
                [r.parse_ms for r in scored if r.parse_ms is not None]
            ),
            "total_parse_cost_usd": (
                sum(r.parse_cost_usd for r in scored if r.parse_cost_usd is not None)
                or None
            ),
        }
    return out


def to_report(results: list[DocResult], meta: dict) -> dict:
    return {
        **meta,
        "by_provider_quality": list(aggregate(results, "quality").values()),
        "by_provider_category": list(aggregate(results, "category").values()),
        "documents": [
            {
                "provider": r.provider,
                "doc_id": r.doc_id,
                "category": r.category,
                "quality": r.quality,
                "accuracy": None if (r.skipped or r.error) else r.accuracy,
                "passed": r.passed,
                "total": r.total,
                "parse_ms": r.parse_ms,
                "extract_ms": r.extract_ms,
                "parse_cost_usd": r.parse_cost_usd,
                "skipped": r.skipped,
                "error": r.error,
                "failures": [
                    {
                        "field": f.name,
                        "expected": f.expected,
                        "actual": f.actual,
                        "detail": f.detail,
                    }
                    for f in r.fields
                    if not f.passed
                ],
            }
            for r in results
        ],
    }


def _fmt_pct(v: float | None) -> str:
    return f"{v * 100:5.1f}%" if v is not None else "   n/a"


def _fmt_ms(v: float | None) -> str:
    return f"{v / 1000:6.1f}s" if v is not None else "   n/a"


def _fmt_cost(v: float | None) -> str:
    return f"${v:.4f}" if v is not None else "  n/a"


def format_report(report: dict) -> str:
    lines: list[str] = []
    lines.append("")
    lines.append(
        f"parse-eval harness — model held constant: {report.get('model', '?')}"
    )
    lines.append(f"providers: {', '.join(report.get('providers', []))}")
    lines.append(
        f"bundles: {report.get('bundles', '?')}    extract: {report.get('extract_url', 'in-process')}"
    )
    lines.append("")

    header = f"{'provider':<14} {'doc-type':<9} {'docs':>4} {'skip':>4} {'err':>3} {'acc':>7} {'parse':>7} {'extract':>8} {'cost':>8}"
    lines.append("PER PROVIDER × DOC-TYPE (quality)")
    lines.append(header)
    lines.append("-" * len(header))
    for row in report["by_provider_quality"]:
        lines.append(
            f"{row['provider']:<14} {row['quality']:<9} {row['docs']:>4} {row['skipped']:>4} "
            f"{row['errors']:>3} {_fmt_pct(row['accuracy'])} {_fmt_ms(row['mean_parse_ms'])} "
            f"{_fmt_ms(row['mean_extract_ms'])} {_fmt_cost(row['total_parse_cost_usd'])}"
        )

    lines.append("")
    lines.append("PER PROVIDER × CATEGORY (domain)")
    lines.append(header.replace("doc-type", "category"))
    lines.append("-" * len(header))
    for row in report["by_provider_category"]:
        lines.append(
            f"{row['provider']:<14} {row['category']:<9} {row['docs']:>4} {row['skipped']:>4} "
            f"{row['errors']:>3} {_fmt_pct(row['accuracy'])} {_fmt_ms(row['mean_parse_ms'])} "
            f"{_fmt_ms(row['mean_extract_ms'])} {_fmt_cost(row['total_parse_cost_usd'])}"
        )

    # Per-provider overall
    lines.append("")
    lines.append("OVERALL (per provider)")
    by_prov: dict[str, list[dict]] = {}
    for row in report["by_provider_quality"]:
        by_prov.setdefault(row["provider"], []).append(row)
    for prov, rows in by_prov.items():
        pf = sum(r["passed_fields"] for r in rows)
        tf = sum(r["fields_checked"] for r in rows)
        acc = (pf / tf) if tf else None
        skipped = sum(r["skipped"] for r in rows)
        errs = sum(r["errors"] for r in rows)
        lines.append(
            f"  {prov:<14} {_fmt_pct(acc)}  ({pf}/{tf} fields, {skipped} skipped, {errs} errors)"
        )

    # Failures detail
    failing = [d for d in report["documents"] if d["error"] or d["failures"]]
    if failing:
        lines.append("")
        lines.append("FAILURES / ERRORS")
        for d in failing:
            if d["skipped"]:
                continue
            if d["error"]:
                lines.append(f"  x {d['provider']}/{d['doc_id']}: {d['error']}")
            else:
                lines.append(
                    f"  - {d['provider']}/{d['doc_id']} ({d['quality']}): {d['passed']}/{d['total']}"
                )
                for f in d["failures"]:
                    detail = (
                        f["detail"]
                        or f"expected {f['expected']!r}, got {f['actual']!r}"
                    )
                    lines.append(f"      {f['field']}: {detail}")
    lines.append("")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════
# Server / token resolution + CLI
# ════════════════════════════════════════════════════════════════════════


DEFAULT_EXTRACT_URL = "http://127.0.0.1:9412"


def resolve_extract_url(cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    return os.environ.get("KOJI_EXTRACT_URL", DEFAULT_EXTRACT_URL)


def build_providers(names: list[str]) -> list[Provider]:
    providers: list[Provider] = []
    for n in names:
        if n not in PROVIDERS:
            raise SystemExit(
                f"unknown provider {n!r}. Registered: {', '.join(PROVIDERS)}. "
                f"Add it to PROVIDERS in {Path(__file__).name}."
            )
        providers.append(PROVIDERS[n])
    return providers


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--providers",
        default="docling",
        help="comma-separated provider names (default: docling)",
    )
    ap.add_argument("--category", help="only this category")
    ap.add_argument("--quality", choices=QUALITY_TAGS, help="only this quality tier")
    ap.add_argument("--doc", dest="doc_id", help="only this doc-id")
    ap.add_argument(
        "--extract-url",
        help=f"koji-extract service URL (default: env KOJI_EXTRACT_URL or {DEFAULT_EXTRACT_URL})",
    )
    ap.add_argument(
        "--model", help="model held constant for extract, e.g. openai/gpt-4o-mini"
    )
    ap.add_argument(
        "--strategy", help="extract strategy held constant (default: service default)"
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON instead of a table",
    )
    ap.add_argument("-o", "--output", help="write JSON report to this file")
    args = ap.parse_args(argv)

    provider_names = [p.strip() for p in args.providers.split(",") if p.strip()]
    providers = build_providers(provider_names)
    bundles = discover_bundles(args.category, args.quality, args.doc_id)
    if not bundles:
        print("no bundles matched the filters", file=sys.stderr)
        return 1

    extract_url = resolve_extract_url(args.extract_url)
    backend = HttpExtractBackend(extract_url, args.model, args.strategy)

    def progress(prov: str, doc: str, i: int, total: int) -> None:
        if not args.json:
            print(f"  ({i}/{total}) {prov} :: {doc}", file=sys.stderr)

    try:
        results = run(providers, bundles, backend, progress)
    finally:
        backend.close()

    report = to_report(
        results,
        meta={
            "providers": provider_names,
            "model": args.model or "default",
            "strategy": args.strategy or "default",
            "extract_url": extract_url,
            "bundles": len(bundles),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))

    # Non-zero if any provider hit a hard error (skips are fine).
    had_error = any(d["error"] and not d["skipped"] for d in report["documents"])
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
