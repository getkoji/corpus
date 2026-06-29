#!/usr/bin/env python3
"""Tests for the parse-eval harness (PB-3).

Runs the FULL pipeline (discover → provider → extract → score → aggregate →
report) over the real migrated sample bundles using a deterministic in-process
extract backend, so the harness logic is verified with no live model. The live
``koji-extract`` service path is exercised separately against a running engine.

Run:  python -m pytest scripts/test_parse_eval_harness.py -q
"""

from __future__ import annotations

import json

import parse_eval_harness as h


# ── A deterministic, model-free extract backend ──────────────────────────


class OracleBackend:
    """Returns the bundle's ground truth as the extraction, so a correctly
    wired harness scores 100%. Lets us assert the plumbing without an LLM."""

    def __init__(self, mutate=None):
        self.mutate = mutate
        self.calls = 0

    def extract(self, text, schema_text, representation):
        self.calls += 1
        # The text we receive IS the parsed representation; the oracle answer
        # is encoded after a marker so we prove the harness fed parsed text in.
        truth = json.loads(text.split("\n<<TRUTH>>\n", 1)[1])
        fields = dict(truth)
        if self.mutate:
            fields = self.mutate(fields)
        return h.ExtractResult(fields=fields, extract_ms=42, model="oracle")

    def close(self):
        pass


class _OracleProvider:
    """Cached provider variant that appends the truth so OracleBackend can
    echo it — emulates a provider whose parse perfectly preserves the values."""

    name = "oracle"
    representation = "markdown"

    def parse(self, bundle: h.Bundle) -> h.ParseResult:
        base = h.CachedRepresentationProvider("docling", "markdown").parse(bundle)
        if base.skipped or base.text is None:
            return base
        truth = bundle.truth_path.read_text()
        return h.ParseResult(
            text=base.text + "\n<<TRUTH>>\n" + truth,
            representation="markdown",
            parse_ms=1234,
            cost_usd=0.0007,
        )


# ── Discovery ────────────────────────────────────────────────────────────


def test_discovers_sample_bundles():
    bundles = h.discover_bundles()
    assert len(bundles) >= 8, f"expected the PB-0 sample, got {len(bundles)}"
    qualities = {b.quality for b in bundles}
    assert {"digital", "scan", "fax", "mixed"} <= qualities


def test_filters():
    assert all(
        b.category == "receipts" for b in h.discover_bundles(category="receipts")
    )
    assert all(b.quality == "scan" for b in h.discover_bundles(quality="scan"))


# ── Docling baseline provider reads the cached representation ─────────────


def test_docling_provider_reads_cached_parse():
    bundle = h.discover_bundles(category="receipts", doc_id="sroie_000")[0]
    res = h.PROVIDERS["docling"].parse(bundle)
    assert not res.skipped
    assert res.text and "BOOK TA" in res.text
    assert res.representation == "markdown"


def test_unregistered_provider_skips_gracefully():
    bundle = h.discover_bundles(category="receipts", doc_id="sroie_000")[0]
    res = h.CachedRepresentationProvider("mistral", "markdown").parse(bundle)
    assert res.skipped and "mistral" in res.reason


# ── Representation-agnostic, null-aware scoring ──────────────────────────


def test_score_perfect():
    truth = {"a": "Acme Co", "b": 9.0, "c": "2024-01-02"}
    res = h.score(truth, {"a": "acme co", "b": "9.00", "c": "2024-1-2"})
    assert all(f.passed for f in res)


def test_score_null_aware():
    # expected null + actual null/absent → pass (no hallucination)
    assert h.compare_field("x", None, None).passed
    assert h.compare_field("x", None, "").passed
    # expected null + a value → hallucination fail
    f = h.compare_field("x", None, "surprise")
    assert not f.passed and "hallucinat" in f.detail
    # present expected + null actual → missing fail
    assert not h.compare_field("x", "Acme", None).passed


def test_score_fuzzy_threshold():
    assert not h.compare_field(
        "n", "Cornerstone Insurance Services", "Cornerstone Insurance Svc"
    ).passed
    assert h.compare_field(
        "n", "Cornerstone Insurance Services", "Cornerstone Insurance Svc", 0.7
    ).passed


# ── Full pipeline end-to-end (no LLM) ────────────────────────────────────


def test_full_pipeline_oracle_scores_100():
    bundles = h.discover_bundles()
    backend = OracleBackend()
    results = h.run([_OracleProvider()], bundles, backend)
    assert backend.calls == len(bundles), (
        "extract must run once per bundle (held constant)"
    )
    scored = [r for r in results if not r.skipped and r.error is None]
    assert scored, "no bundles scored"
    for r in scored:
        assert r.accuracy == 1.0, (
            f"{r.doc_id}: {[(f.name, f.detail) for f in r.fields if not f.passed]}"
        )


def test_aggregation_by_quality_and_report():
    bundles = h.discover_bundles()
    results = h.run([_OracleProvider()], bundles, OracleBackend())
    report = h.to_report(results, {"providers": ["oracle"], "model": "oracle"})

    rows = report["by_provider_quality"]
    qualities = {r["quality"] for r in rows}
    assert {"digital", "scan", "fax", "mixed"} <= qualities
    for row in rows:
        assert row["provider"] == "oracle"
        if row["scored_docs"]:
            assert row["accuracy"] == 1.0
            assert row["mean_parse_ms"] == 1234
            assert row["total_parse_cost_usd"] is not None

    # report renders without error and shows both axes
    text = h.format_report(report)
    assert "PER PROVIDER × DOC-TYPE" in text
    assert "PER PROVIDER × CATEGORY" in text


def test_aggregation_catches_a_regression():
    """A provider that drops a value shows up as an accuracy drop — the whole
    point of the harness (e.g. the wrong-column bug)."""
    bundles = h.discover_bundles(category="receipts")

    def drop_total(fields):
        fields["total_amount"] = 0.0  # wrong value
        return fields

    results = h.run([_OracleProvider()], bundles, OracleBackend(mutate=drop_total))
    scored = [r for r in results if not r.skipped and r.error is None]
    assert any(r.accuracy < 1.0 for r in scored)


if __name__ == "__main__":
    import subprocess
    import sys

    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
