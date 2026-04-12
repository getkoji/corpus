#!/usr/bin/env python3
"""Score extraction accuracy against the corpus.

Compares actual extraction output (from koji extract) against expected JSON
and produces per-field, per-document, and aggregate accuracy metrics.

Usage:
    python scripts/score.py --category invoices --model openai/gpt-4o-mini
    python scripts/score.py --all --model openai/gpt-4o-mini

This is a temporary standalone scorer until `koji bench` ships in the main
Koji CLI. Once that exists, this script should be deleted in favor of the
built-in benchmark runner.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CORPUS_ROOT = Path(__file__).parent.parent


@dataclass
class FieldResult:
    name: str
    passed: bool
    expected: Any = None
    actual: Any = None
    reason: str = ""


@dataclass
class DocumentResult:
    document: str
    fields: list[FieldResult] = field(default_factory=list)
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


@dataclass
class CategoryResult:
    category: str
    documents: list[DocumentResult] = field(default_factory=list)

    @property
    def total_docs(self) -> int:
        return len(self.documents)

    @property
    def total_fields(self) -> int:
        return sum(d.total for d in self.documents)

    @property
    def passed_fields(self) -> int:
        return sum(d.passed for d in self.documents)

    @property
    def accuracy(self) -> float:
        return self.passed_fields / self.total_fields if self.total_fields else 0.0


# ── Field comparison (mirrors cli/test_runner.py in the main koji repo) ──


def _normalize_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value)
    if match:
        y, m, d = match.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return None


def _to_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def compare_field(name: str, expected: Any, actual: Any) -> FieldResult:
    if actual is None:
        return FieldResult(name=name, passed=False, expected=expected, reason="missing")

    # Date comparison
    exp_date = _normalize_date(expected)
    act_date = _normalize_date(actual)
    if exp_date is not None and act_date is not None:
        return FieldResult(
            name=name,
            passed=exp_date == act_date,
            expected=expected,
            actual=actual,
        )

    # Number comparison with tolerance
    exp_num = _to_number(expected)
    act_num = _to_number(actual)
    if exp_num is not None and act_num is not None:
        ok = round(abs(exp_num - act_num), 10) <= 0.01
        return FieldResult(name=name, passed=ok, expected=expected, actual=actual)

    # Array comparison (length match, order-insensitive for dicts)
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return FieldResult(
                name=name,
                passed=False,
                expected=expected,
                actual=actual,
                reason=f"length mismatch: {len(expected)} vs {len(actual)}",
            )
        return FieldResult(name=name, passed=True, expected=expected, actual=actual)

    # Exact string match (case-insensitive)
    if isinstance(expected, str) and isinstance(actual, str):
        return FieldResult(
            name=name,
            passed=expected.lower().strip() == actual.lower().strip(),
            expected=expected,
            actual=actual,
        )

    return FieldResult(name=name, passed=expected == actual, expected=expected, actual=actual)


def compare_documents(expected: dict, actual: dict) -> list[FieldResult]:
    results = []
    for key, exp_value in expected.items():
        act_value = actual.get(key)
        results.append(compare_field(key, exp_value, act_value))
    return results


# ── Scoring runner ──


def score_category(category: str, actual_dir: Path) -> CategoryResult:
    """Compare actual extraction outputs against expected outputs for a category."""
    category_dir = CORPUS_ROOT / category
    expected_dir = category_dir / "expected"

    if not expected_dir.is_dir():
        print(f"Category not found: {category}", file=sys.stderr)
        return CategoryResult(category=category)

    result = CategoryResult(category=category)

    for expected_file in sorted(expected_dir.glob("*.expected.json")):
        doc_name = expected_file.name.replace(".expected.json", "")
        actual_file = actual_dir / f"{doc_name}.json"

        if not actual_file.exists():
            result.documents.append(
                DocumentResult(document=doc_name, error=f"no actual output: {actual_file}")
            )
            continue

        try:
            expected = json.loads(expected_file.read_text())
            actual = json.loads(actual_file.read_text())
        except json.JSONDecodeError as e:
            result.documents.append(DocumentResult(document=doc_name, error=str(e)))
            continue

        # Handle koji extract output format which wraps in "extracted"
        if "extracted" in actual:
            actual = actual["extracted"]

        fields = compare_documents(expected, actual)
        result.documents.append(DocumentResult(document=doc_name, fields=fields))

    return result


def print_report(results: list[CategoryResult]) -> int:
    """Print a human-readable accuracy report. Returns exit code."""
    total_docs = 0
    total_fields = 0
    total_passed = 0
    had_failures = False

    for cat in results:
        if not cat.documents:
            continue
        print(f"\n[{cat.category}]")
        print(f"  {cat.total_docs} documents, {cat.total_fields} fields checked")
        print(f"  {cat.passed_fields}/{cat.total_fields} passed ({cat.accuracy:.1%})")

        # Show failing docs
        for doc in cat.documents:
            if doc.error:
                print(f"  ERROR {doc.document}: {doc.error}")
                had_failures = True
                continue
            if doc.passed < doc.total:
                print(f"  {doc.document}: {doc.passed}/{doc.total}")
                for f in doc.fields:
                    if not f.passed:
                        print(f"    - {f.name}: expected {f.expected!r}, got {f.actual!r}")
                had_failures = True

        total_docs += cat.total_docs
        total_fields += cat.total_fields
        total_passed += cat.passed_fields

    print(f"\n{'=' * 50}")
    print(f"TOTAL: {total_passed}/{total_fields} fields across {total_docs} documents")
    if total_fields:
        print(f"Accuracy: {total_passed / total_fields:.1%}")

    return 1 if had_failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Score extraction accuracy against the corpus.")
    parser.add_argument(
        "--category",
        help="Category to score (invoices, sec_filings, irs_forms, contracts). Omit for all.",
    )
    parser.add_argument(
        "--actual-dir",
        type=Path,
        required=True,
        help="Directory containing actual extraction outputs (one JSON per document).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable text.",
    )
    args = parser.parse_args()

    categories = [args.category] if args.category else ["invoices", "sec_filings", "irs_forms", "contracts"]
    results = [score_category(c, args.actual_dir) for c in categories]

    if args.json:
        output = [
            {
                "category": c.category,
                "documents": c.total_docs,
                "fields": c.total_fields,
                "passed": c.passed_fields,
                "accuracy": c.accuracy,
            }
            for c in results
        ]
        print(json.dumps(output, indent=2))
        return 0

    return print_report(results)


if __name__ == "__main__":
    sys.exit(main())
