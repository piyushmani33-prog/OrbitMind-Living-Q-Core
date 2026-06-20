# ADR-0020 — Claims, Evidence, and Version-Pinned Citations

- **Status:** Accepted (2026-06-20)

## Context
The platform must capture *who asserted what* without conflating assertion with truth.
A source stating a claim is **not** a verified fact, and retrieval is **not**
verification (SR-01/epistemic invariants).

## Decision
- **Typed claims** (`ScientificClaim`): subject / predicate / object(+units), with an
  explicit `ClaimStatus` (e.g. `source-asserted`, `calculated`, `supported`,
  `contradicted`) **and** an `EpistemicStatus`. Claims default to `source-asserted` /
  `assumption` and carry a `limitations` note. Generated/source text is never labelled
  `verified-fact`. Incomplete claims (missing subject/predicate/object) are rejected.
- **Provenance is mandatory**: claims reference the originating `document_id`,
  `version_id`, `chunk_id`, and an optional `QuoteSpan` (char range + quote).
- **Evidence links** (`EvidenceLink`) connect a claim to a chunk or a structured
  record with a typed `EvidenceSupportType` (`supports`, `contradicts`, …). Evidence
  may not reference a nonexistent claim/chunk.
- **Citations are version-pinned** (`CitationRecord`): every retrieval result and
  claim cites the exact stored `version_id`, `chunk_id`, char range, and checksum, plus
  a safe `origin_label` (relative path, never a full local path) and a rights note.
- **Contradictions** are recorded explicitly (`ContradictionRecord`) rather than
  silently resolved.

## Alternatives considered
1. **Free-text claims/citations.** Not queryable, not reproducible, easy to
   misrepresent as fact. Rejected.
2. **Cite the live document instead of a pinned version.** Breaks reproducibility when
   the document changes. Rejected.

## Consequences
- Every assertion is traceable to an exact, checksummed source passage.
- Claims/evidence are auditable and never imply verification.

## Review trigger
Revisit when adding automated claim extraction or a verification workflow over claims.
