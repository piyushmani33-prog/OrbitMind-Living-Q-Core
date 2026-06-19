# Reference Document Manifest

Authoritative product-vision / feasibility source material and its integrity metadata.

## Inspection record
- **Inspected (UTC):** 2026-06-19
- **Method:** SHA-256 over the exact bytes; read-only text extraction via
  `scripts/extract_docx.py`; DOCX metadata (`docProps/core.xml`, `app.xml`) and
  embedded media reviewed for sensitive content.
- **Result:** both expected documents are now **present and inspected** (they were
  delivered via the user's Downloads folder and copied byte-for-byte into
  `docs/reference/`; the originals in Downloads are untouched, and the copies'
  checksums match the originals exactly). Risk **R-001 is now resolved** — see
  `../architecture/RISK_REGISTER.md`.

## Documents

### 1. OrbitMind Living Q-Core.docx
| Field | Value |
|-------|-------|
| Exact filename | `OrbitMind Living Q-Core.docx` |
| File type | Microsoft Word (OOXML `.docx`), 155,934 bytes |
| SHA-256 | `743df017f700b7401591b19a9f8c27e147768be71b85cc9c7ab4aa45f6e47060` |
| Inspected (UTC) | 2026-06-19 |
| Purpose | Primary vision + reference architecture for OrbitMind Living Q-Core. |
| Classification | **Advisory / feasibility** (a synthesis citing official docs). Contains **aspirational** language ("living", "self-improving") that the document itself reframes as bounded engineering. **Not contractually normative.** |
| Major relevant sections | Executive summary; Core architecture & technology choices (FastAPI/Pydantic/Postgres/pgvector/Redis/Temporal/Celery, sandbox tiers); Knowledge, retrieval, reasoning & Research Autopilot (schema, hybrid retrieval); Quantum Organ, Tool Forge & orchestration; **Data sources & Visual Intelligence** (CelesTrak 2-hour guidance + source policy matrix); Security/operations/cost/evaluation/roadmap. |
| Tracked by Git | **No** (binary; gitignored via a narrow rule — see Repository decision). |
| Suitable for a public repo | Content has **no secrets/PII** (empty author/title; `DocSecurity=0`); sensitivity-wise it could be public, but publication is an **owner business decision**. Default: not tracked pending that decision. |
| Embedded media | 3 PNG diagrams (system spine, Research Autopilot workflow, roadmap) — not representable in the text derivative. |

### 2. OrbitMind Living Q-Core Feasibility Brief.docx
| Field | Value |
|-------|-------|
| Exact filename | `OrbitMind Living Q-Core Feasibility Brief.docx` |
| File type | Microsoft Word (OOXML `.docx`), 21,572 bytes |
| SHA-256 | `aa56ed0bdcf1d42b34ca5d356255e3fcdefa10b7bcd3750eabee950cb9ebbf26` |
| Inspected (UTC) | 2026-06-19 |
| Purpose | Feasibility assessment + first-release scope guidance. |
| Classification | **Advisory / feasibility**; explicitly **rejects** the literal "100% correct autonomous universe-brain" framing. Not contractually normative. |
| Major relevant sections | Executive assessment; What the product should actually be (five coupled planes; system-spine flow); Recommended reference architecture; Data/science/quantum foundations (CelesTrak 2-hour guidance; data-rights registry); Security/correctness/governance (correctness-in-layers); What to build first; Open questions & limitations. |
| Tracked by Git | **No** (binary; gitignored). |
| Suitable for a public repo | No secrets/PII; publication is an owner decision. |
| Embedded media | None. |

## Generated derivatives
Read-only text extracts (clearly labelled, non-authoritative) are under
`docs/reference/extracted/` and **are tracked by Git** so the content is
reviewable/diffable in-repo:
- `extracted/OrbitMind-Living-Q-Core.extracted.md`
- `extracted/OrbitMind-Living-Q-Core-Feasibility-Brief.extracted.md`

Extraction is paragraph-text only: **tables are flattened** (structure lost) and
**images/diagrams are omitted** (the main document's 3 PNG diagrams in particular).
The original DOCX remain authoritative.

## Repository decision (originals)
The binary DOCX are **kept locally and preserved, but not tracked** (gitignored via
the narrow rule `docs/reference/*.docx` in `.gitignore`). Rationale: there is no Git
remote and future visibility is unknown; the readable Markdown derivatives + these
checksums give reproducible, verifiable content in-repo without committing binary
vision documents that may not be intended for a public repository. The owner can
remove the ignore rule to track them. **The originals are never deleted.**
