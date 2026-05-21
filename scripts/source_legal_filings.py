#!/usr/bin/env python3
"""Source legal filings from CourtListener's free RECAP archive.

Uses the CourtListener REST API to find court filings that are freely
available (already in the RECAP archive), downloads the text, and
creates corpus entries.

API docs: https://www.courtlistener.com/help/api/rest/
No PACER credentials needed — only downloads documents already in RECAP.
"""

import json
import os
import sys
import time
from pathlib import Path

import httpx

CORPUS_DIR = Path(__file__).resolve().parent.parent / "legal_filings"
API_BASE = "https://www.courtlistener.com/api/rest/v4"
# CourtListener requires auth token for API access (free account)
TOKEN = os.environ.get("COURTLISTENER_TOKEN", "")

HEADERS = {}
if TOKEN:
    HEADERS["Authorization"] = f"Token {TOKEN}"

# Filing types we want
FILING_TYPES = ["complaint", "motion", "brief", "order", "memorandum"]


def search_recap_documents(query: str, count: int = 20) -> list[dict]:
    """Search RECAP archive for documents with available text."""
    results = []
    with httpx.Client(headers=HEADERS, timeout=30) as client:
        resp = client.get(
            f"{API_BASE}/search/",
            params={
                "q": query,
                "type": "r",  # RECAP documents
                "order_by": "score desc",
                "page_size": min(count, 20),
            },
        )
        if resp.status_code != 200:
            print(f"Search failed: {resp.status_code} {resp.text[:200]}")
            return []

        data = resp.json()
        for result in data.get("results", []):
            results.append({
                "id": result.get("id"),
                "case_name": result.get("caseName", ""),
                "court": result.get("court", ""),
                "date_filed": result.get("dateFiled", ""),
                "docket_number": result.get("docketNumber", ""),
                "description": result.get("description", ""),
                "snippet": result.get("snippet", ""),
            })

    return results


def download_opinion_text(opinion_id: int) -> str | None:
    """Download the plain text of a court opinion."""
    with httpx.Client(headers=HEADERS, timeout=30) as client:
        resp = client.get(f"{API_BASE}/opinions/{opinion_id}/")
        if resp.status_code != 200:
            return None
        data = resp.json()
        # Try different text fields
        for field in ["plain_text", "html_with_citations", "html"]:
            text = data.get(field, "")
            if text and len(text) > 100:
                return text
    return None


def main():
    if not TOKEN:
        print("Set COURTLISTENER_TOKEN env var (get one at https://www.courtlistener.com/profile/)")
        print("Free account, no PACER credentials needed.")
        sys.exit(1)

    print("Searching for court filings in RECAP archive...")

    queries = [
        "breach of contract",
        "motion to dismiss",
        "motion for summary judgment",
        "preliminary injunction",
        "class action complaint",
        "patent infringement",
        "employment discrimination",
        "securities fraud",
    ]

    for query in queries:
        print(f"\nSearching: {query}")
        results = search_recap_documents(query, count=15)
        print(f"  Found {len(results)} results")

        for r in results[:3]:
            print(f"  - {r['case_name'][:60]} ({r['court']}, {r['date_filed']})")

        time.sleep(1)  # Rate limit courtesy


if __name__ == "__main__":
    main()
