# Contracts

Commercial contracts from public sources. Two main sources: SEC filings (where contracts appear as exhibits to 10-K/10-Q filings) and open-license contract templates.

## Sources

- **SEC EDGAR exhibits** — thousands of real contracts filed as attachments to quarterly and annual reports. Employment agreements, M&A contracts, licensing deals, lease agreements. Public domain.
- **Common Paper** — CC-licensed contract templates filled with real-world usage patterns
- **Docracy** — community-contributed contract templates (check individual licenses)
- **GitHub repos** — several open-source contract template repos with redistributable licenses

## Document types

- **Employment agreements**
- **Non-disclosure agreements**
- **Service agreements**
- **Licensing agreements**
- **Lease agreements**
- **M&A agreements**
- **Master service agreements (MSA)**

## Current schemas

- `contract_parties.yaml` — party names, addresses, roles, signing date
- `contract_term.yaml` — effective date, term length, termination clauses, renewal
- `contract_financial.yaml` — contract value, payment schedule, penalties, fees
- `contract_confidentiality.yaml` — NDA terms, duration, scope

## Challenges

Contracts are hard. They're long, they use legal language, and key information is often embedded in dense paragraphs rather than structured fields. This category is valuable precisely because it stress-tests the extraction pipeline.

## License

- SEC EDGAR exhibits: public domain
- Common Paper: CC BY
- Docracy: check each template
- GitHub repos: check each repo's license

All licenses are recorded per-document in manifests.
