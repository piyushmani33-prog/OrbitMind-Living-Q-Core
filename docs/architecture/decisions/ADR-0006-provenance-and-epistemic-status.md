# ADR-0006 — Provenance and Epistemic Status

- **Status:** Accepted (2026-06-19)

## Context
A scientific platform must never blur calculation, assumption, and verified fact.
Outputs need machine-readable epistemic labels and claim-level provenance so
reviewers can judge trust, and so the system never overclaims.

## Decision
- Define a single `EpistemicStatus` enum applied to every major output:
  `verified-fact | deterministic-calculation | model-estimate | hypothesis |
  assumption | unknown | rejected`.
- Orbital positions from SGP4 are labeled **`deterministic-calculation`** (a
  reproducible computation that is also a *model* of reality). The input TLE is
  labeled **`assumption`/`model-estimate`** because it is bundled sample data, not
  live truth.
- **Confidence percentages are NOT attached to deterministic calculations.**
  Confidence is used only where a defensible scoring method exists.
- Every result carries a `ProvenanceRecord` (subject, source ref, method,
  inputs hash, generated_at) and an `OrbitalSourceRecord` for the fixture
  (origin, date, license note, checksum, `test_only`).
- A generated natural-language explanation is **never** labeled `verified-fact`.

## Alternatives considered
1. **Single confidence score per output.** Misleading for deterministic math;
   conflates very different epistemic kinds. Rejected.
2. **No labels (prose only).** Unauditable; risks overclaiming. Rejected.

## Consequences
- Domain models and API responses include explicit status + provenance fields.
- Verification can assert that labels are valid and that deterministic results are
  not mislabeled as verified fact.

## Review trigger
Revisit when adding retrieved evidence (Phase 3) or model-vs-model hypotheses,
which may need a defensible confidence-scoring method.
