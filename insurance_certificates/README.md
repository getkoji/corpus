# Insurance Certificates

Certificate of liability insurance documents. This category targets a
well-known hard case in document extraction: standardized insurance
forms with grid-based coverage tables, multiple parties (producer,
insured, certificate holder), and dozens of labeled fields per
document.

## Why this category is valuable

Insurance certificates stress-test the extraction pipeline in ways
simpler documents don't:

- **Many fields per document** — 25-40 labeled fields in a typical
  certificate, vs 5-10 for a simple invoice
- **Grid-based coverage tables** — each coverage line has its own
  policy number, dates, and multiple limits (each limit, aggregate,
  per-occurrence, etc.)
- **Mixed layouts** — labeled boxes, free-text remarks sections,
  checkboxes, signature lines
- **Multiple parties** — producer (broker), insured (policyholder),
  certificate holder (requesting party), plus up to 6 insurers
- **Dates everywhere** — policy effective/expiration dates for each
  coverage, certificate date, cancellation notice periods

Getting 95%+ accuracy on this category is a meaningful proof point
for Koji's extraction pipeline.

## About ACORD forms

The insurance industry's standard certificate layout is **ACORD 25**
(Certificate of Liability Insurance). ACORD 25 is copyrighted by
ACORD Corporation — blank forms and their exact layout cannot be
freely redistributed.

**What we do NOT do:** We do not redistribute ACORD's copyrighted
blank forms in this corpus. We do not reproduce ACORD's trademarked
name, logo, or exact header wording.

**What we do:** We generate **synthetic certificate-of-insurance
documents** that follow the same structural pattern (producer section,
insured section, certificate holder section, coverage grid with policy
numbers and limits, cancellation clause, authorized representative)
without reproducing ACORD's copyrighted layout verbatim. These
synthetic samples exercise the same extraction difficulty as real
ACORD certificates without any licensing concerns.

Users who want to test extraction against real ACORD certificates can
source them from their own records or from public court filings where
certificates were attached as exhibits.

## Current schemas

- `certificate_of_liability.yaml` — producer, insured, certificate
  holder, and a grid of coverage lines (general liability, auto,
  workers comp, umbrella, etc.) each with policy number, effective
  date, expiration date, and limits

## Phases

- **Phase 1 (this commit):** 5-10 synthetic samples to validate the
  extraction pipeline against complex insurance certificates
- **Phase 2:** Source real public-record completed certificates from
  court filings where the document entered public record as a filed
  exhibit (CourtListener RECAP Archive is one option)
- **Phase 3:** Expand schema coverage to include property certificates,
  commercial applications, and related document types

## License note per manifest

Every document in this category has a manifest entry with explicit
licensing. Synthetic samples are Apache-2.0 (our work). Real
court-sourced documents cite the case name, court, and docket number
and rely on the public-record nature of the court filing.
