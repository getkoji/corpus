# Invoices

Commercial and research invoices. The easiest category to bootstrap — high-quality public datasets already exist.

## Sources

- **SROIE** — [Scanned Receipt OCR and Information Extraction](https://rrc.cvc.uab.es/?ch=13) challenge dataset. Singaporean receipts with ground-truth annotations. CC BY 4.0.
- **CORD** — [Consolidated Receipt Dataset](https://github.com/clovaai/cord). Indonesian receipts with structured JSON annotations. CC BY 4.0.
- **FUNSD** — [Form Understanding in Noisy Scanned Documents](https://guillaumejaume.github.io/FUNSD/). Form-based invoices. Research use.

## Current schemas

- `invoice_basic.yaml` — invoice number, date, vendor, total, line items
- `invoice_detailed.yaml` — above plus tax breakdown, payment terms, addresses

(Schemas will be added as the corpus grows. Keep schemas small and focused — a schema that extracts 6 fields accurately is more valuable than one that attempts 40 fields and fails.)

## What we're looking for

- **Variety of layouts** — single-column, multi-column, tabular
- **Variety of scripts** — English, Chinese, Arabic, etc.
- **Variety of quality** — clean PDFs, noisy scans, phone photos
- **Edge cases** — multi-page invoices, credit notes, proforma invoices

## Contribution

Follow the process in [CONTRIBUTING.md](../CONTRIBUTING.md). PRs should include the document, an expected JSON, and a manifest entry.
