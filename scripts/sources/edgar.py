#!/usr/bin/env python3
"""SEC EDGAR sourcing script for the Koji validation corpus.

Fetches SEC filings via the EDGAR full-text search API and bulk archive
endpoints, then writes filing metadata as corpus samples. Ground truth
comes from EDGAR's own index, so the expected outputs are authoritative.

Why this approach:
  - SEC filings are public domain (US government records)
  - EDGAR's index provides filer name, CIK, form type, filing date, and
    period of report — exactly the fields we want to extract
  - Using the index as ground truth means zero manual annotation work

Key constraints:
  - SEC requires a User-Agent header identifying the requester
  - Rate limit is 10 requests/second; we use 8/sec with safety margin
  - EDGAR does not require authentication

Usage:
  python scripts/sources/edgar.py --form-type 10-K --limit 20
  python scripts/sources/edgar.py --form-type 8-K --limit 50 --start-date 2024-01-01
  python scripts/sources/edgar.py --form-type all --limit 100

Form types supported:
  10-K, 10-Q, 8-K, DEF 14A, S-1, 20-F, 6-K, and variants.

References:
  - EDGAR full-text search: https://efts.sec.gov/LATEST/search-index?q=&forms=10-K
  - EDGAR submissions endpoint: https://data.sec.gov/submissions/CIK{cik}.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

CORPUS_ROOT = Path(__file__).resolve().parent.parent.parent
FILINGS_DIR = CORPUS_ROOT / "sec_filings"

USER_AGENT = "Koji Corpus bot@getkoji.dev"
RATE_LIMIT_DELAY = 0.125  # 8 req/sec, safely under SEC's 10/sec limit

SUPPORTED_FORMS = [
    "10-K", "10-K/A",
    "10-Q", "10-Q/A",
    "8-K", "8-K/A",
    "S-1", "S-1/A",
    "DEF 14A",
    "20-F",
    "6-K",
]

# ── HTTP helpers ─────────────────────────────────────────────────


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        timeout=60.0,
        follow_redirects=True,
    )


def edgar_search(form_type: str, start_date: str | None, end_date: str | None, limit: int, client: httpx.Client) -> list[dict]:
    """Search EDGAR full-text index for filings of a given form type.

    Returns a list of hit dicts with keys: adsh (accession), cik, form, file_date.
    """
    params = {
        "q": "",
        "forms": form_type,
        "dateRange": "custom" if (start_date or end_date) else "",
    }
    if start_date:
        params["startdt"] = start_date
    if end_date:
        params["enddt"] = end_date

    # EDGAR's search endpoint — returns a structured JSON result
    url = "https://efts.sec.gov/LATEST/search-index"

    hits: list[dict] = []
    offset = 0
    page_size = 100

    while len(hits) < limit:
        query_params = {**params, "from": offset}
        resp = client.get(url, params=query_params)
        if resp.status_code != 200:
            print(f"[edgar] Search request failed: {resp.status_code}", file=sys.stderr)
            break

        data = resp.json()
        page_hits = data.get("hits", {}).get("hits", [])
        if not page_hits:
            break

        for hit in page_hits:
            src = hit.get("_source", {})
            hits.append({
                "accession": src.get("adsh") or hit.get("_id", "").split(":")[0],
                "cik": (src.get("ciks", [None]) or [None])[0],
                "form": src.get("form"),
                "file_date": src.get("file_date"),
                "display_names": src.get("display_names", []),
            })
            if len(hits) >= limit:
                break

        offset += page_size
        time.sleep(RATE_LIMIT_DELAY)

    return hits


def fetch_submission_index(cik: str, client: httpx.Client) -> dict | None:
    """Fetch a company's submission index from EDGAR's data.sec.gov endpoint.

    This gives us authoritative metadata (name, periods of report, filing dates)
    for all of the company's recent filings.
    """
    padded_cik = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{padded_cik}.json"
    resp = client.get(url)
    if resp.status_code != 200:
        return None
    return resp.json()


def build_sample_from_submission(cik: str, accession: str, submission: dict) -> dict | None:
    """Extract metadata for a single filing from a company submission index."""
    filer_name = submission.get("name")
    if not filer_name:
        return None

    recent = submission.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    try:
        idx = accessions.index(accession.replace("-", ""))
    except ValueError:
        # Try with original format
        try:
            idx = accessions.index(accession)
        except ValueError:
            return None

    return {
        "filer_name": filer_name,
        "cik": cik.zfill(10),
        "form_type": recent.get("form", [None] * (idx + 1))[idx],
        "filing_date": recent.get("filingDate", [None] * (idx + 1))[idx],
        "period_of_report": recent.get("reportDate", [None] * (idx + 1))[idx] or None,
        "accession_number": accession,
    }


# ── Sample writer ────────────────────────────────────────────────


def build_markdown(metadata: dict) -> str:
    """Render a filing's metadata as a short markdown document."""
    form_type = metadata.get("form_type", "Unknown")
    filer_name = metadata.get("filer_name", "Unknown")
    cik = metadata.get("cik", "")
    filing_date = metadata.get("filing_date", "")
    period = metadata.get("period_of_report") or filing_date
    accession = metadata.get("accession_number", "")

    return f"""# Form {form_type}

**UNITED STATES SECURITIES AND EXCHANGE COMMISSION**
Washington, D.C. 20549

---

**Filer:** {filer_name}
**CIK:** {cik}
**Form Type:** {form_type}
**Filing Date:** {filing_date}
**Period of Report:** {period}
**Accession Number:** {accession}

This filing was retrieved from SEC EDGAR and is part of the Koji validation corpus.
"""


def safe_filename(form_type: str, n: int) -> str:
    slug = form_type.lower().replace("/", "_").replace(" ", "_").replace("-", "")
    return f"edgar_{slug}_{n:03d}"


def write_sample(metadata: dict, sample_id: str) -> None:
    doc_path = FILINGS_DIR / "documents" / f"{sample_id}.md"
    exp_path = FILINGS_DIR / "expected" / f"{sample_id}.expected.json"
    man_path = FILINGS_DIR / "manifests" / f"{sample_id}.json"

    doc_path.write_text(build_markdown(metadata))
    exp_path.write_text(json.dumps(metadata, indent=2) + "\n")

    form_type = metadata.get("form_type", "")
    cik = metadata.get("cik", "")
    manifest = {
        "filename": doc_path.name,
        "source_name": "SEC EDGAR",
        "source_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}",
        "license": "Public Domain (US Government Work)",
        "license_url": "https://www.sec.gov/privacy",
        "attribution": "US Securities and Exchange Commission",
        "original_format": "HTML",
        "r2_url": None,
        "pages": 1,
        "added_date": "2026-04-12",
        "added_by": "corpus-bootstrap",
        "schema": "sec_filings/schemas/filing_metadata.yaml",
        "notes": f"{form_type} filing metadata retrieved from EDGAR index. Ground truth is authoritative (source is the index itself).",
    }
    man_path.write_text(json.dumps(manifest, indent=2) + "\n")


# ── Main ─────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--form-type",
        default="10-K",
        help="Form type to fetch (10-K, 10-Q, 8-K, DEF 14A, etc., or 'all')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of filings to process (default: 20)",
    )
    parser.add_argument(
        "--start-date",
        help="Earliest filing date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        help="Latest filing date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    form_types = SUPPORTED_FORMS if args.form_type == "all" else [args.form_type]

    for sub in ("documents", "expected", "manifests"):
        (FILINGS_DIR / sub).mkdir(parents=True, exist_ok=True)

    processed = 0
    skipped = 0
    failed = 0
    counters: dict[str, int] = {}

    with _client() as client:
        for form_type in form_types:
            if processed >= args.limit:
                break

            per_form_limit = args.limit - processed
            print(f"[edgar] Searching for {form_type} filings (up to {per_form_limit})", file=sys.stderr)
            hits = edgar_search(form_type, args.start_date, args.end_date, per_form_limit, client)
            print(f"[edgar] Found {len(hits)} hits", file=sys.stderr)

            for hit in hits:
                if processed >= args.limit:
                    break

                cik = hit.get("cik")
                accession = hit.get("accession")
                if not cik or not accession:
                    failed += 1
                    continue

                try:
                    submission = fetch_submission_index(cik, client)
                    if not submission:
                        failed += 1
                        continue

                    metadata = build_sample_from_submission(cik, accession, submission)
                    if not metadata:
                        failed += 1
                        continue

                    actual_form = metadata.get("form_type", form_type)
                    n = counters.get(actual_form, 0) + 1
                    counters[actual_form] = n
                    sample_id = safe_filename(actual_form, n)

                    if (FILINGS_DIR / "documents" / f"{sample_id}.md").exists():
                        skipped += 1
                        continue

                    write_sample(metadata, sample_id)
                    processed += 1
                    print(
                        f"[edgar] ({processed}/{args.limit}) {sample_id} "
                        f"{metadata.get('filer_name')} {actual_form}",
                        file=sys.stderr,
                    )

                    time.sleep(RATE_LIMIT_DELAY)

                except Exception as e:
                    print(f"[edgar] Error on {accession}: {e}", file=sys.stderr)
                    failed += 1

    print(
        f"\n[edgar] Done. Processed: {processed}, Skipped: {skipped}, Failed: {failed}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
