"""Generate targeted loss run corpus entries for structural gap testing.

Creates documents that test specific multi-page PDF challenges:
  GAP 1 — Header carry-forward (headers only on page 1)
  GAP 2 — Page-break row splits (claim split across pages)
  GAP 4 — Multi-section (GL + Auto in one document)

GAP 3 (carrier format variation) is already covered — the existing 50
docs span 13 carrier formats. We just tag 3 of them explicitly.

Output:
  insurance_claims/documents/structural_loss_run_*.md
  insurance_claims/expected/structural_loss_run_*.expected.json
  insurance_claims/manifests/structural_loss_run_*.json
"""

from __future__ import annotations

import json
import random
from pathlib import Path

CORPUS = Path(__file__).parent.parent / "insurance_claims"
DOCS = CORPUS / "documents"
EXPECTED = CORPUS / "expected"
MANIFESTS = CORPUS / "manifests"

CARRIERS = [
    ("Hartford Financial Services", "HF"),
    ("Zurich American Insurance", "ZA"),
    ("Liberty Mutual Insurance", "LM"),
    ("CNA Financial Corporation", "CNA"),
    ("Erie Insurance Group", "EI"),
]

NAMES = [
    "James Rodriguez", "Patricia Wilson", "Robert Martinez", "Jennifer Davis",
    "Michael Brown", "Linda Garcia", "William Anderson", "Elizabeth Thomas",
    "David Jackson", "Barbara White", "Richard Harris", "Susan Martin",
    "Joseph Thompson", "Margaret Robinson", "Charles Clark", "Dorothy Lewis",
]

DESCRIPTIONS_GL = [
    "Slip and fall on wet floor — broken hip",
    "Product liability — defective valve failure",
    "Third-party bodily injury — scaffolding collapse",
    "Property damage — fire from electrical work",
    "Completed operations — water damage after plumbing job",
    "Advertising injury — trademark infringement claim",
]

DESCRIPTIONS_AUTO = [
    "Rear-end collision on highway",
    "Side-swipe while merging on interstate",
    "T-bone collision at uncontrolled intersection",
    "Company van hit parked vehicle",
    "Cargo spill on highway — hazmat response required",
    "Multi-vehicle pileup in construction zone",
]

DESCRIPTIONS_WC = [
    "Lower back herniated disc — material handling",
    "Fall from scaffold — fractured wrist",
    "Repetitive motion injury — carpal tunnel syndrome",
    "Chemical exposure — respiratory irritation",
    "Struck by falling object — head injury",
    "Shoulder rotator cuff tear — overhead work",
]


def _claim_num(carrier_prefix: str, i: int) -> str:
    return f"{carrier_prefix}-2025-{random.randint(10000, 99999)}"


def _amount() -> str:
    return f"${random.randint(500, 500000):,.2f}"


def _small_amount() -> str:
    return f"${random.randint(100, 50000):,.2f}"


def _date() -> str:
    m = random.randint(1, 12)
    d = random.randint(1, 28)
    return f"{m:02d}/{d:02d}/2025"


def _write(stem: str, doc: str, expected: dict, manifest: dict):
    (DOCS / f"{stem}.md").write_text(doc)
    (EXPECTED / f"{stem}.expected.json").write_text(json.dumps(expected, indent=2) + "\n")
    (MANIFESTS / f"{stem}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"  wrote {stem}")


# -------------------------------------------------------------------------
# GAP 1 — Header carry-forward
# Headers appear ONLY on page 1. Pages 2+ have bare data rows.
# -------------------------------------------------------------------------

def gen_gap1():
    """Generate 5 loss runs with headers only on page 1."""
    print("\nGAP 1 — Header carry-forward (5 docs)")

    for i in range(5):
        carrier_name, prefix = CARRIERS[i]
        insured = f"Structural Test Corp {i + 1}"
        policy = f"CGL-{random.randint(1000000, 9999999)}"
        state = ["TX", "CA", "NY", "FL", "IL"][i]

        claims = []
        for j in range(12):  # enough claims to span "pages"
            claims.append({
                "num": _claim_num(prefix, j),
                "date": _date(),
                "name": random.choice(NAMES),
                "desc": random.choice(DESCRIPTIONS_GL),
                "status": random.choice(["Open", "Closed", "Closed", "Closed"]),
                "reserve": _amount() if random.random() > 0.5 else "$0.00",
                "paid": _amount(),
            })

        # Page 1: full header + first 5 claims
        lines = [
            f"# {carrier_name}",
            "",
            "## Loss Run / Claims History Report",
            "",
            f"Insured: {insured}",
            f"Policy: {policy} (General Liability)",
            f"Period: 01/01/2025 — 12/31/2025",
            f"As of: 07/15/2025",
            "",
            "---",
            "",
            "| Claim No. | Loss Date | Claimant Name | Description | Status | Reserve | Paid to Date |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in claims[:5]:
            lines.append(f"| {c['num']} | {c['date']} | {c['name']} | {c['desc']} | {c['status']} | {c['reserve']} | {c['paid']} |")

        # Page 2+: NO headers, just bare rows (simulates parsed multi-page PDF)
        lines.append("")
        lines.append("<!-- page break — headers not repeated -->")
        lines.append("")
        for c in claims[5:9]:
            lines.append(f"| {c['num']} | {c['date']} | {c['name']} | {c['desc']} | {c['status']} | {c['reserve']} | {c['paid']} |")

        lines.append("")
        lines.append("<!-- page break — headers not repeated -->")
        lines.append("")
        for c in claims[9:]:
            lines.append(f"| {c['num']} | {c['date']} | {c['name']} | {c['desc']} | {c['status']} | {c['reserve']} | {c['paid']} |")

        doc = "\n".join(lines)
        stem = f"structural_loss_run_gap1_{i + 1:03d}"

        _write(stem, doc, {
            "form_type": "Loss Run",
            "claimant_name": None,
            "employer_name": insured,
            "policy_number": policy,
            "state": state,
        }, {
            "filename": f"{stem}.md",
            "source_name": "Synthetic generator (generate_loss_run_structural.py)",
            "source_url": None,
            "license": "Apache-2.0",
            "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
            "attribution": "Koji corpus contributors",
            "original_format": "markdown",
            "r2_url": None,
            "pages": 3,
            "added_date": "2026-04-17",
            "added_by": "accuracy-oss-79",
            "schema": "insurance_claims/schemas/claim_form.yaml",
            "doc_type": "loss_run",
            "tags": ["loss-run-no-repeat-headers"],
            "notes": f"GAP 1 — Headers only on page 1. {len(claims)} claims across 3 pages. {carrier_name} format.",
        })


# -------------------------------------------------------------------------
# GAP 2 — Page-break row splits
# A claim row is split across a page boundary.
# -------------------------------------------------------------------------

def gen_gap2():
    """Generate 3 loss runs with split rows at page boundaries."""
    print("\nGAP 2 — Page-break row splits (3 docs)")

    for i in range(3):
        carrier_name, prefix = CARRIERS[i + 2]  # use different carriers from gap1
        insured = f"PageBreak Industries {i + 1}"
        policy = f"WC-{random.randint(1000000, 9999999)}"
        state = ["OH", "PA", "GA"][i]

        claims = []
        for j in range(8):
            claims.append({
                "num": _claim_num(prefix, j),
                "date": _date(),
                "name": random.choice(NAMES),
                "desc": random.choice(DESCRIPTIONS_WC),
                "status": random.choice(["Open", "Closed", "Closed"]),
                "reserve": _amount() if random.random() > 0.5 else "$0.00",
                "paid": _amount(),
            })

        # The split row: claim 4 has a long description that wraps across
        # the page boundary. Parser outputs the first part on page 1 and
        # the continuation on page 2.
        split_claim = claims[4]
        split_claim["desc"] = (
            "Worker fell from elevated platform approximately 12 feet while performing "
            "routine maintenance on HVAC equipment — sustained compound fracture of left "
            "tibia and fibula plus cervical strain"
        )

        lines = [
            f"# {carrier_name}",
            "",
            "## Loss Run / Claims History Report",
            "",
            f"Insured: {insured}",
            f"Policy: {policy} (Workers Compensation)",
            f"Period: 01/01/2025 — 12/31/2025",
            "",
            "---",
            "",
            "| Claim No. | Loss Date | Claimant Name | Description | Status | Reserve | Paid to Date |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in claims[:4]:
            lines.append(f"| {c['num']} | {c['date']} | {c['name']} | {c['desc']} | {c['status']} | {c['reserve']} | {c['paid']} |")

        # Split row: first part ends page 1
        sc = split_claim
        desc_part1 = "Worker fell from elevated platform approximately 12 feet while performing"
        desc_part2 = "routine maintenance on HVAC equipment — sustained compound fracture of left tibia and fibula plus cervical strain"

        lines.append(f"| {sc['num']} | {sc['date']} | {sc['name']} | {desc_part1}")
        lines.append("")
        lines.append("<!-- page break — row continues -->")
        lines.append("")
        lines.append(f"{desc_part2} | {sc['status']} | {sc['reserve']} | {sc['paid']} |")

        # Rest of claims on page 2
        lines.append("")
        for c in claims[5:]:
            lines.append(f"| {c['num']} | {c['date']} | {c['name']} | {c['desc']} | {c['status']} | {c['reserve']} | {c['paid']} |")

        doc = "\n".join(lines)
        stem = f"structural_loss_run_gap2_{i + 1:03d}"

        _write(stem, doc, {
            "form_type": "Loss Run",
            "claimant_name": None,
            "employer_name": insured,
            "policy_number": policy,
            "state": state,
        }, {
            "filename": f"{stem}.md",
            "source_name": "Synthetic generator (generate_loss_run_structural.py)",
            "source_url": None,
            "license": "Apache-2.0",
            "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
            "attribution": "Koji corpus contributors",
            "original_format": "markdown",
            "r2_url": None,
            "pages": 2,
            "added_date": "2026-04-17",
            "added_by": "accuracy-oss-79",
            "schema": "insurance_claims/schemas/claim_form.yaml",
            "doc_type": "loss_run",
            "tags": ["loss-run-split-row"],
            "notes": f"GAP 2 — Claim row split across page boundary. {carrier_name} format.",
        })


# -------------------------------------------------------------------------
# GAP 4 — Multi-section documents
# GL section then Auto section, each with its own table.
# -------------------------------------------------------------------------

def gen_gap4():
    """Generate 2 multi-section loss runs (GL + Auto in one doc)."""
    print("\nGAP 4 — Multi-section documents (2 docs)")

    for i in range(2):
        carrier_name, prefix = CARRIERS[i]
        insured = f"MultiCov Enterprises {i + 1}"
        policy_gl = f"CGL-{random.randint(1000000, 9999999)}"
        policy_auto = f"AUT-{random.randint(1000000, 9999999)}"
        state = ["NJ", "MA"][i]

        gl_claims = []
        for j in range(4):
            gl_claims.append({
                "num": _claim_num(prefix, j),
                "date": _date(),
                "name": random.choice(NAMES),
                "desc": random.choice(DESCRIPTIONS_GL),
                "status": random.choice(["Open", "Closed", "Closed"]),
                "reserve": _amount() if random.random() > 0.5 else "$0.00",
                "paid": _amount(),
            })

        auto_claims = []
        for j in range(3):
            auto_claims.append({
                "num": _claim_num(prefix, j + 10),
                "date": _date(),
                "name": random.choice(NAMES),
                "desc": random.choice(DESCRIPTIONS_AUTO),
                "status": random.choice(["Open", "Closed", "Closed"]),
                "reserve": _amount() if random.random() > 0.5 else "$0.00",
                "paid": _amount(),
            })

        lines = [
            f"# {carrier_name}",
            "",
            f"## Combined Loss Run Report — {insured}",
            "",
            f"Prepared: 07/15/2025",
            "",
            "---",
            "",
            "## SECTION 1: GENERAL LIABILITY",
            "",
            f"Policy: {policy_gl}",
            f"Period: 01/01/2025 — 12/31/2025",
            "",
            "| Claim No. | Loss Date | Claimant | Description | Status | Reserve | Paid |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in gl_claims:
            lines.append(f"| {c['num']} | {c['date']} | {c['name']} | {c['desc']} | {c['status']} | {c['reserve']} | {c['paid']} |")

        lines.extend([
            "",
            "---",
            "",
            "## SECTION 2: COMMERCIAL AUTO",
            "",
            f"Policy: {policy_auto}",
            f"Period: 01/01/2025 — 12/31/2025",
            "",
            "| Claim No. | Loss Date | Claimant | Description | Status | Reserve | Paid |",
            "|---|---|---|---|---|---|---|",
        ])
        for c in auto_claims:
            lines.append(f"| {c['num']} | {c['date']} | {c['name']} | {c['desc']} | {c['status']} | {c['reserve']} | {c['paid']} |")

        doc = "\n".join(lines)
        stem = f"structural_loss_run_gap4_{i + 1:03d}"

        # Expected: use the GL policy since it's listed first
        _write(stem, doc, {
            "form_type": "Loss Run",
            "claimant_name": None,
            "employer_name": insured,
            "policy_number": policy_gl,
            "state": state,
        }, {
            "filename": f"{stem}.md",
            "source_name": "Synthetic generator (generate_loss_run_structural.py)",
            "source_url": None,
            "license": "Apache-2.0",
            "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
            "attribution": "Koji corpus contributors",
            "original_format": "markdown",
            "r2_url": None,
            "pages": 2,
            "added_date": "2026-04-17",
            "added_by": "accuracy-oss-79",
            "schema": "insurance_claims/schemas/claim_form.yaml",
            "doc_type": "loss_run",
            "tags": ["loss-run-multi-section"],
            "notes": f"GAP 4 — GL + Auto sections in one document. {carrier_name} format.",
        })


if __name__ == "__main__":
    random.seed(42)  # reproducible
    gen_gap1()
    gen_gap2()
    gen_gap4()
    print(f"\nDone. 10 structural test cases created.")
