# Reference Documents

This directory holds the authoritative product/vision source material.

## Status: PRESENT and reconciled (2026-06-19)

The two reference documents have been delivered, inspected, hashed, and reconciled:

- `OrbitMind Living Q-Core.docx` — primary vision + reference architecture
- `OrbitMind Living Q-Core Feasibility Brief.docx` — feasibility + first-release scope

Integrity metadata (SHA-256, classification, sections) is in
[`REFERENCE_MANIFEST.md`](REFERENCE_MANIFEST.md). The reconciliation of record is
[`../architecture/REFERENCE_RECONCILIATION.md`](../architecture/REFERENCE_RECONCILIATION.md).
Risk **R-001** ("reference documents absent") is **closed**.

## Layout
- `*.docx` — the **authoritative originals** (binary). They are **preserved locally
  but gitignored** (narrow rule `docs/reference/*.docx`) pending an owner decision on
  publishing; their checksums are recorded in the manifest. **Never modify, rename,
  re-save, or delete them.**
- `extracted/` — generated, read-only **text derivatives** (tracked by Git) for
  in-repo review/diffing. Derivatives are NOT authoritative and omit images/tables.

## Extraction tool
A safe, read-only, standard-library-only extractor is at `scripts/extract_docx.py`
(unzips the DOCX and pulls text from `word/document.xml`; no office suite; never
modifies the source). Re-run it if the originals are updated, then refresh the
manifest checksums and the reconciliation.
