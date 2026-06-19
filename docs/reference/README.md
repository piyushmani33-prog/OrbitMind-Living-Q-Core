# Reference Documents

This directory is the home for the authoritative product/vision source material.

## Expected documents (currently MISSING)

The following documents are expected here but were **not present** when the
repository was first built:

- `OrbitMind Living Q-Core` (vision / product document)
- `OrbitMind Living Q-Core Feasibility Brief`

## Action required by the owner

Place the original documents in this folder, for example:

```
docs/reference/OrbitMind-Living-Q-Core.docx
docs/reference/OrbitMind-Living-Q-Core-Feasibility-Brief.docx
```

`.docx`, `.pdf`, or `.md` are all acceptable. Do **not** rename or delete the
originals once added.

If `.docx` files are added and need to be inspected, a safe, read-only,
standard-library-only text extractor is provided at:

```
scripts/extract_docx.py
```

It unzips the DOCX (a ZIP container) and pulls text from `word/document.xml`
using only the Python standard library. It does not install any office suite and
does not modify the source file.

## Current status

Because the reference documents are absent, the build proceeded using the
**owner's build prompt as the approved project specification**. The missing
documents are tracked as a risk in
[`docs/architecture/RISK_REGISTER.md`](../architecture/RISK_REGISTER.md)
(risk **R-001**).

When the real documents arrive, review them against:

- `docs/requirements/PRODUCT_REQUIREMENTS.md`
- `docs/architecture/decisions/` (all ADRs)

and record any material conflicts as new ADRs or risk-register entries.
