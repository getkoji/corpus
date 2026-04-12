# Contributing to the Koji Corpus

Thank you for wanting to contribute documents and ground-truth data. This corpus only works if it grows — every document added makes Koji's extraction pipeline more robust across real-world use cases.

## What we accept

We accept **public, redistributable documents** in the categories we're tracking:

- Invoices (commercial or research datasets)
- SEC filings
- IRS and other government forms
- Contracts (EDGAR exhibits, open-license templates)
- Insurance policies (state DOI filings)
- Academic papers (arXiv, CC-licensed)
- Court filings (CourtListener, public domain)
- Real estate records (public records)
- Medical records (de-identified, from public research datasets only)

We **do not accept** proprietary documents, confidential business documents, or documents with unclear licensing.

## Contribution checklist

Before opening a PR:

- [ ] Document is from a public source with clear redistribution rights
- [ ] Document is either in markdown form (small) or has an R2 URL (large)
- [ ] A manifest entry is added with source, license, and metadata
- [ ] An `.expected.json` file is provided with ground-truth extraction
- [ ] The expected output has been manually reviewed for correctness
- [ ] The schema used exists in the category's `schemas/` directory (or is added in the same PR)

## Process

### 1. Source the document

Find a document from a public source. Examples of acceptable sources:

- **Public domain:** US government documents, SEC filings, IRS forms, court records
- **Creative Commons:** CC0, CC BY, CC BY-SA (attribution preserved in manifest)
- **Research datasets:** SROIE, CORD, FUNSD, PubLayNet (cite the dataset in the manifest)
- **Open-license templates:** contract templates from Docracy, Common Paper, etc.

### 2. Add it to the corpus

Place the document in the appropriate category directory:

```
invoices/
├── documents/
│   └── your_doc.md              # Parsed markdown (or a small stub referencing R2)
├── expected/
│   └── your_doc.expected.json   # Your ground-truth extraction
└── manifests/
    └── your_doc.json            # Metadata about the source and license
```

### 3. Manifest format

Every document needs a manifest entry. Example:

```json
{
  "filename": "your_doc.md",
  "source_name": "SROIE Dataset",
  "source_url": "https://example.com/sroie",
  "license": "CC BY-SA 4.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
  "attribution": "Singapore University of Technology and Design",
  "original_format": "PDF",
  "r2_url": "https://r2.getkoji.dev/corpus/invoices/your_doc.pdf",
  "pages": 1,
  "added_date": "2026-04-15",
  "added_by": "your-github-handle",
  "schema": "invoices/schemas/invoice_basic.yaml",
  "notes": "Receipt from a Singaporean retailer, used in the SROIE task."
}
```

### 4. Generate and verify expected output

Run Koji with a capable model to generate the initial expected output:

```bash
koji extract ./invoices/documents/your_doc.md \
  --schema ./invoices/schemas/invoice_basic.yaml \
  --model openai/gpt-4o \
  --output ./invoices/expected/
```

Then **manually review** the output. Fix any incorrect values, add missing fields, remove hallucinations. The whole point of the corpus is that the expected outputs are trustworthy — if you can't verify them, don't submit them.

### 5. Open a PR

Open a PR with:

- Clear title: `Add N invoices from SROIE dataset`
- Description explaining the source, any caveats, and verification process
- All files in the right places

A maintainer will review the license, sample a few expected outputs to sanity-check, and merge.

## What makes a good addition

**Variety** — we want diverse examples per category, not 50 copies of the same form template.
**Difficulty** — documents that stress-test the extraction pipeline are more valuable than easy cases.
**Ground truth quality** — careful human review matters more than volume. One carefully-verified document is worth ten hastily-generated ones.

## Questions

Open an issue with the `contribution-question` label. We'll respond quickly.
