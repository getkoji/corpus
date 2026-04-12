# IRS Forms

US Internal Revenue Service tax forms. All public domain — available directly from [irs.gov](https://www.irs.gov/forms-instructions).

## Document types

- **1040** — individual income tax return (various variants)
- **1099** — miscellaneous income (1099-MISC, 1099-NEC, 1099-INT, etc.)
- **W-2** — wage and tax statement
- **W-9** — request for taxpayer identification
- **941** — employer's quarterly federal tax return
- **Schedule C** — profit or loss from business
- **Form 4868** — extension request

## Sourcing

IRS publishes blank form PDFs on irs.gov. For populated examples we can:
1. Generate synthetic filled examples (no real PII) — highest quality, deterministic ground truth
2. Use publicly-released aggregated tax data
3. Use historical examples released under FOIA (redacted)

The `scripts/sources/irs.py` script (to be added) will fetch blank forms and generate synthetic filled versions.

## Current schemas

- `form_1040.yaml` — filer info, filing status, dependents, AGI, tax owed
- `form_1099.yaml` — payer, recipient, income type, amount
- `form_w2.yaml` — employer, employee, wages, withholdings

## Note on synthetic data

When we generate synthetic filled forms, we mark them as such in the manifest (`synthetic: true`). This distinguishes real historical documents from synthetic ones used purely for extraction validation.

## License

All IRS forms are public domain US government works.
