# SEC Filings

Public filings from the US Securities and Exchange Commission. All public domain — these are government records. Available via [EDGAR](https://www.sec.gov/edgar.shtml).

## Document types

- **10-K** — annual report
- **10-Q** — quarterly report
- **8-K** — current report (material events)
- **S-1** — IPO registration
- **DEF 14A** — proxy statement
- **Form 3/4/5** — insider trading reports

## Sourcing

EDGAR provides a [full-text search API](https://efts.sec.gov/LATEST/search-index?q=&dateRange=custom&forms=10-K) and bulk download. The `scripts/sources/edgar.py` script (to be added) will automate fetching random samples across document types and years.

## Current schemas

- `filing_metadata.yaml` — filer name, CIK, filing type, filing date, period of report
- `10k_highlights.yaml` — revenue, net income, total assets, risk factors count
- `insider_trading.yaml` — reporter name, transaction type, shares, price

## What we're looking for

- **Recent filings (past 5 years)** — current business context
- **Variety of issuers** — different industries, company sizes
- **Edge cases** — restatements, amendments, withdrawn filings
- **Mid-cap and small-cap** — Fortune 500 filings are easy but less representative

## License

All SEC filings are public domain US government records. No attribution required, no redistribution restrictions.
