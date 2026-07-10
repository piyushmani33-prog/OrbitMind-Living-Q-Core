# Governed Research Learning Loop

## Purpose

U4.0A establishes a small offline foundation for traceable research handling. It does
not implement Research Autopilot, autonomous agents, internet research, model training,
or durable research persistence.

The governing rule is:

> Every authorized research input is traceably handled. Missing or invalid information
> is recorded as a gap. Derived claims cite evidence. The user sees only the relevant
> result, while the detailed record remains available through an audited repository
> boundary.

The implementation lives in `src/orbitmind/research/`. It has no FastAPI route and is
not wired into `AppContainer` in this slice.

## Input Lifecycle

The bounded cycle is:

1. Receive one typed `ResearchRequest` and no more than 16 explicit normalized local
   documents.
2. Record the request and each document as a `ResearchInput` handling record.
3. Validate availability, content, declared checksum, capture time, provenance
   reference, and usage restrictions.
4. Accept valid unique documents as `ResearchEvidence` records.
5. Mark repeated source-and-checksum pairs as duplicates without inserting evidence
   twice.
6. Convert rejected, unavailable, missing, or conflicting information into explicit
   `ResearchGap` records.
7. Generate one deterministic fixture claim, then independently verify its evidence
   references and prerequisites.
8. Create one `ResearchLearningRecord` that links evidence, claim, and unresolved gaps.
9. Save the complete internal `ResearchCycleRecord` through an injected repository
   port.
10. Return only a bounded `UserResearchResult`.

Raw document text exists only in the transient `NormalizedResearchDocument`. It is not
copied into inputs, evidence, cycle records, learning records, or user results. Arbitrary
raw binary content is not accepted by these models.

## Evidence And Claims

Evidence and claims are different records:

- `ResearchEvidence` states what accepted source record was captured, when it was
  captured, its checksum, source identity, provenance reference, reliability status,
  and usage restrictions.
- `DerivedResearchClaim` is a conclusion produced from evidence. It carries an
  `EpistemicStatus`, qualitative confidence label, evidence IDs, gap IDs, verifier
  status, and limitations.
- A claim without evidence is rejected unless it is explicitly a `hypothesis`.
- A verifier status means that deterministic consistency checks passed. It does not
  turn generated text into `verified-fact` and is not human approval.
- Conflicting accepted evidence remains present as separate records. It is not silently
  overwritten or reduced to the first value.

This foundation complements, rather than replaces, the durable scientific-memory
claims/evidence model. A later persistence design must define how research-cycle records
link to version-pinned memory citations without duplicating or weakening them.

## Research Gaps

`ResearchGap` records make absence and rejection visible. Initial gap types include
source unavailable, invalid checksum, missing content, missing source metadata, missing
time range, conflicting identity/evidence, unsupported format, insufficient evidence,
and unconfirmed rights.

Each gap records its effect on the result and whether recovery is possible. Gaps are
never converted into positive evidence. A result may remain a hypothesis when a gap
blocks the bounded claim requirements.

## Structured Learning

Learning in U4.0A means writing a structured `ResearchLearningRecord` through a typed
repository port. It records:

- supporting and contradicted evidence IDs;
- resulting claim IDs;
- unresolved gap IDs;
- topic, cycle identity, timestamp, and status.

It does not modify model weights, source policy, scientific rules, permissions, runtime
configuration, or production code. There is no production repository implementation in
this slice. The only repository adapter is test-local and therefore not durable memory.

Durable research memory requires a separately reviewed persistence design and migration.
Until then, OrbitMind must not claim permanent research learning.

## User Projection

`UserResearchResult` contains only:

- request summary;
- concise answer;
- qualitative confidence label;
- important limitation;
- recommended next step;
- evidence and unresolved-gap counts;
- an opaque `research-cycle:<id>` method/evidence reference.

It does not expose raw source content, provider bodies, file paths, secrets, private
metadata, unrestricted evidence, or internal discussion. A future API projector must
preserve this allowlisted shape and resolve detailed records through authorization.

## Open Research Policy

`ORBITMIND_OPEN_RESEARCH_ENABLED` is an activation contract and defaults to `false`.
No production research source adapter exists or is wired in U4.0A. Setting the flag to
`true` alone cannot start a request.

Future adapter-backed research may run only when both conditions are true:

- the research system is explicitly active for a bounded cycle;
- open research is explicitly enabled.

A future source adapter must also be explicitly injected. It must not be discovered from
a global mutable registry. Every adapter must enforce:

- an approved source allowlist and HTTPS-only canonical URLs;
- source-specific rate limits, bounded requests, bounded response size, and timeouts;
- publisher/source identity, retrieval timestamp, attribution, and content checksum;
- license and usage status, duplicate detection, and failure/gap recording;
- no paywall bypass, credential scraping, private-data collection, or hidden source use;
- no unrestricted search or crawling, raw-content redistribution, or tight infinite loop;
- no automatic trust of retrieved content.

Research cycles must be scheduled and bounded in a later reviewed slice. This foundation
contains no scheduler, browser automation, HTTP client, or network call.

## Privacy And Consent

Every input carries consent scope, privacy class, and retention class. Future adapters
must reject collection outside their approved scope. Private or restricted metadata must
never enter the user projection without a separate authorization rule.

Retention is policy, not indefinite storage. A durable implementation must define:

- retention periods by class;
- owner-authorized deletion and legal-hold behavior;
- deletion of raw source payloads separately from checksum/provenance records;
- audit records for retention and deletion outcomes;
- treatment of evidence still referenced by claims or learning records.

U4.0A implements none of these storage operations because it has no durable repository.

## Restricted Self-Modification

Research output cannot modify OrbitMind code, prompts, permissions, configuration,
source allowlists, scientific constants, verifier rules, or deployment state. A future
improvement proposal may be recorded as untrusted evidence, but human-reviewed software
development remains the only route to a production change.

## Future Discussion

A future multi-agent discussion loop may propose, criticize, and compare claims only
after separate architecture and threat-model review. Every contribution must be logged,
bounded, attributable, evidence-linked, and non-authoritative. Agent consensus is not
verification. No agents or agent-creation behavior are implemented here.

## Future Quantum Use

Future quantum-assisted optimization may help select bounded experiments or compare
candidate research plans only behind the existing classical-baseline and simulator
boundaries. It may not determine scientific truth, override a verifier, promote a claim,
or control research permissions. U4.0A imports no quantum module and runs no quantum code.

## Authority

Deterministic scientific services, authenticated persisted evidence, explicit verifier
results, and human review remain authoritative within their stated scope. Research
claims and learning records are traceable interpretations, not replacement authority.
Retrieval is evidence, not verification; missing data remains a gap, not permission to
guess.

## Deferred Work

The following remain deferred: production persistence and migration, API routes,
authorization, source adapters, network research, scheduler, multi-agent discussion,
LLM claim generation, model training, automated code changes, Workbench integration,
live providers, deployment, and quantum-assisted research.
