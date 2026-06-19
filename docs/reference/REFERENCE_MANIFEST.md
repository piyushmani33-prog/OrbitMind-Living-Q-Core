# Reference Document Manifest

This manifest records the authoritative product-vision / feasibility reference
documents and their integrity metadata.

## Inspection record

- **Date inspected:** 2026-06-19
- **Inspected by:** principal architect (automated build)
- **Method:** recursive search of `E:\quantum-project` (excluding `.venv`, `.git`)
  for `*.docx, *.pdf, *.doc, *.rtf, *.odt`, plus a direct listing of
  `docs/reference/`.

## Result: reference documents NOT PRESENT

The expected documents were **not found** in the repository at inspection time —
this is the **second** confirmed absence (the first was during Phase 0/1).

| Expected filename (any of) | SHA-256 | Status | Normativity | Relevant sections |
|---|---|---|---|---|
| `OrbitMind Living Q-Core.docx` (vision) | _n/a — file absent_ | **NOT PRESENT** | unknown until provided | unknown |
| `OrbitMind Living Q-Core Feasibility Brief.docx` | _n/a — file absent_ | **NOT PRESENT** | unknown until provided | unknown |

No SHA-256 checksums can be computed because the files do not exist. **No checksums
were invented.**

## What was used as the authoritative specification instead

Because the DOCX references are absent, the **owner build prompts** (Phase 0/1 and
this Phase 2 prompt) are treated as the approved, authoritative specification, as
the owner explicitly authorized in the Phase 0 instructions:

> "If the documents are absent … do not stop the entire build. Continue using this
> prompt as the approved project specification and record the missing documents as
> a risk."

## Action required by the owner

Place the original documents under `docs/reference/`, e.g.:

```
docs/reference/OrbitMind-Living-Q-Core.docx
docs/reference/OrbitMind-Living-Q-Core-Feasibility-Brief.docx
```

When added:

1. Re-run this inspection; compute and record SHA-256 for each file here.
2. Optionally extract text with the read-only `scripts/extract_docx.py` into
   `docs/reference/extracted/` (clearly labelled generated derivatives; originals
   preserved, never modified).
3. Re-open and complete `docs/architecture/REFERENCE_RECONCILIATION.md` against the
   *actual* document content.
4. Close/revise risk **R-001** in `docs/architecture/RISK_REGISTER.md`.

## Related

- Risk: [`RISK_REGISTER.md`](../architecture/RISK_REGISTER.md) → **R-001** (open).
- Reconciliation: [`REFERENCE_RECONCILIATION.md`](../architecture/REFERENCE_RECONCILIATION.md)
  (currently reconciled against the build prompt, pending the real documents).
