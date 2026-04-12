# Koji Validation Corpus

A public, versioned corpus of real-world documents with ground-truth extraction outputs. Used to validate [Koji](https://github.com/getkoji/koji) extraction accuracy, benchmark model performance, and seed the community schema ecosystem.

**Goal:** 1000+ documents across invoices, SEC filings, contracts, insurance policies, government forms, academic papers, and more.

## Why this exists

Document extraction tools make accuracy claims that are impossible to verify. This corpus makes them verifiable:

- **Benchmarking** — run any extraction pipeline against the corpus and get an honest accuracy score
- **Regression testing** — every Koji release is automatically tested against 1000+ documents before shipping
- **Model comparison** — see how gpt-4o-mini compares to llama3 compares to mistral across document types
- **Schema validation** — schemas in [getkoji/schemas](https://github.com/getkoji/schemas) are tested against real documents, not theoretical ones

## Structure

```
corpus/
├── invoices/
│   ├── documents/          # The source documents (markdown-parsed or links to PDFs in R2)
│   ├── schemas/            # Extraction schemas used for this category
│   ├── expected/           # Ground-truth JSON outputs, one per document
│   ├── manifests/          # Metadata: source, license, page count, etc.
│   └── README.md
├── sec_filings/
├── irs_forms/
├── contracts/
├── scripts/
│   ├── bench.py            # Run a benchmark against a category
│   ├── score.py            # Compare actual vs expected, compute accuracy
│   └── sources/            # Scrapers/importers for each source
└── .github/workflows/
    └── nightly-bench.yml   # Scheduled benchmark runs against main
```

Each category is self-contained. You can run `koji bench --corpus ./corpus/invoices` to benchmark just one category.

## Document storage

Small text-based documents (markdown, plain text) live directly in the repo under `documents/`. Large binary documents (PDFs over 1MB) live in Cloudflare R2 and are referenced by URL in the manifest files. This keeps the repo cloneable while preserving the originals for anyone who needs to reprocess them.

## Ground truth format

Each document has a corresponding `.expected.json` file in `expected/`. The JSON matches Koji's extraction output format — same field names as the schema, same types, same structure. Generated initially via `koji extract` with `openai/gpt-4o`, then manually reviewed and corrected.

Example: `invoices/documents/sroie_001.md` has ground truth at `invoices/expected/sroie_001.expected.json`.

## Running benchmarks

Once you have Koji installed and a cluster running:

```bash
# Full corpus, all categories
koji bench --corpus ./corpus --model openai/gpt-4o-mini

# One category
koji bench --corpus ./corpus/invoices --model openai/gpt-4o-mini

# Compare models
koji bench --corpus ./corpus --model openai/gpt-4o
koji bench --corpus ./corpus --model openai/gpt-4o-mini
koji bench --corpus ./corpus --model ollama/llama3.2
```

The `koji bench` command doesn't exist yet — it's on the Koji roadmap. Until then, you can use `koji test --schema` on individual categories (it runs against the `fixtures/` convention).

## Contributing

We welcome new documents, schemas, and expected outputs. To contribute:

1. Source a document from a public, redistributable source (public domain, CC-licensed, or explicit permission)
2. Add it to the appropriate category under `documents/`
3. Add or use an existing schema in `schemas/`
4. Generate expected output with `koji extract` and manually verify it
5. Add a manifest entry documenting the source and license
6. Open a PR

See `CONTRIBUTING.md` for detailed guidelines.

## License

- **Code** (scripts, schemas, CI): Apache 2.0
- **Documents**: various — each document's license is recorded in its manifest entry. Many are public domain (US government filings, SEC filings, IRS forms). Others are CC-licensed research datasets. No proprietary documents.

If you want to use a document for your own project, check its manifest first.

## Sources we use

| Category | Primary sources |
|----------|----------------|
| Invoices | SROIE, CORD, FUNSD research datasets |
| SEC filings | EDGAR (public API) |
| IRS forms | irs.gov (public domain) |
| Contracts | EDGAR exhibits (10-K attachments) |
| Insurance policies | State DOI filings (NAIC SERFF) |
| Academic papers | arXiv bulk download |

## Current coverage

This corpus is actively being built. Current document counts:

| Category | Documents | Status |
|----------|-----------|--------|
| invoices | 0 | Scaffolded, not yet populated |
| sec_filings | 0 | Scaffolded, not yet populated |
| irs_forms | 0 | Scaffolded, not yet populated |
| contracts | 0 | Scaffolded, not yet populated |

Accuracy dashboard coming soon at `accuracy.getkoji.dev`.
