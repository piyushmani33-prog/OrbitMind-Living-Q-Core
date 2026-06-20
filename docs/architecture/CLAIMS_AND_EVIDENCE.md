# Claims & Evidence

See [ADR-0020](decisions/ADR-0020-claims-evidence-citations.md). **Memory is not truth;
retrieval is not verification; a source assertion is not automatically a verified fact.**

## The five distinct states
1. **The source states a claim** — `ClaimStatus.SOURCE_ASSERTED` (default).
2. **Evidence supports a claim** — an `EvidenceLink` with `support_type=supports`.
3. **OrbitMind calculates a result** — `ClaimStatus.CALCULATED` (deterministic tools).
4. **A verifier accepts a consistency check** — recorded in `verification_status`.
5. **A human reviewer approves** — a later phase; never implied by ingestion.

## ScientificClaim
Subject / predicate / object(+units), plus:
- `status: ClaimStatus` (extracted, source-asserted, calculated, supported,
  partially-supported, disputed, contradicted, hypothesis, rejected, unknown)
- `epistemic_status: EpistemicStatus` — **never `verified-fact`** for source/generated text
- provenance: `document_id`, `version_id`, `chunk_id`, optional `QuoteSpan` (char range)
- `extractor_version`, `created_at`, `verification_status`, `limitations`

Claims are created only by explicit structured fixtures, deterministic import of
existing verified domain records, or manually registered assertions from approved local
documents. **No open-ended LLM extraction.** `ClaimService` rejects incomplete claims
(missing subject/predicate/object) and claims referencing a nonexistent chunk. No
arbitrary confidence percentages are produced.

## EvidenceLink
`claim_id` + (`chunk_id` or `record_ref`) + `support_type` (supports,
partially-supports, contradicts, contextualizes, derives-from, calculates, supersedes,
duplicates) + `source` + `explanation` + `registrar_version` + `verification_state`.
`EvidenceService` rejects links to nonexistent claims/chunks and links with no target.

## Citations (version-pinned)
Every retrieval result and claim cites the exact stored `version_id`/`chunk_id`, char
range, and checksum (`CitationRecord`). A citation never silently points to a newer
version. `origin_label` is a safe relative path — never a full local path.

## Contradictions
Recorded explicitly (`ContradictionRecord`) rather than silently resolved.
