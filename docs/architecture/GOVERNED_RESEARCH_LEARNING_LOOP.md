# Governed Research Learning Loop

## Purpose

U4.0A establishes a small offline foundation for traceable research handling. U4.0B
adds durable, owner-scoped storage for its bounded structured records. Neither slice
implements Research Autopilot, autonomous agents, internet research, model training,
or a raw evidence-content vault.

The governing rule is:

> Every authorized research input is traceably handled. Missing or invalid information
> is recorded as a gap. Derived claims cite evidence. The user sees only the relevant
> result, while the detailed record remains available through an audited repository
> boundary.

The domain and application service live in `src/orbitmind/research/`. The U4.0B rows
and repository adapter live in `src/orbitmind/persistence/`. They have no FastAPI route
and are not wired into `AppContainer` in this slice.

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

This foundation complements, rather than replaces, the scientific-memory claims and
evidence model. A later integration design must define how research-cycle records link
to version-pinned memory citations without duplicating or weakening them.

## Research Gaps

`ResearchGap` records make absence and rejection visible. Initial gap types include
source unavailable, invalid checksum, missing content, missing source metadata, missing
time range, conflicting identity/evidence, unsupported format, insufficient evidence,
and unconfirmed rights.

Each gap records its effect on the result and whether recovery is possible. Gaps are
never converted into positive evidence. A result may remain a hypothesis when a gap
blocks the bounded claim requirements.

## Structured Learning

Learning means writing a structured `ResearchLearningRecord` through a typed repository
port. It records:

- supporting and contradicted evidence IDs;
- resulting claim IDs;
- unresolved gap IDs;
- topic, cycle identity, timestamp, and status.

It does not modify model weights, source policy, scientific rules, permissions, runtime
configuration, or production code. U4.0B supplies a SQLAlchemy repository for durable
structured memory; it does not make the resulting interpretation authoritative.

## Durable Structured Memory

U4.0B persists one complete `ResearchCycleRecord` graph in a single database
transaction. The cycle, inputs, accepted evidence metadata, gaps, claim, learning
record, and their ordered associations either all commit or all roll back. Lower-level
repository helpers flush but never commit independently. A failure after partial
flushes therefore leaves no durable partial cycle.

Every row and association is owner-scoped. Composite foreign keys include `owner_id`,
and reads require both owner and record identity. Evidence deduplication uses exactly:

`owner_id + source_identifier + content checksum`

The same identity for the same owner reuses one durable evidence row through a
cycle-to-evidence association. Changed content from the same source, the same content
from a different source, and all evidence belonging to different owners remain
separate. Conflicting evidence is preserved as distinct evidence and linked to the
learning record; it is never overwritten by a later value.

The following survive process restart:

- cycle lifecycle, opaque request/result references, and status;
- input handling outcomes and duplicate-evidence references;
- bounded evidence metadata, checksums, provenance references, and usage restrictions;
- gaps, claims, verifier outcomes, limitations, and structured learning links.

This is durable structured research memory, not a raw evidence vault. The database has
no column for `NormalizedResearchDocument.content` or raw provider bodies. A shared
domain policy rejects high-confidence credentials, secret material, credential-bearing
URLs, and absolute filesystem paths from every persisted structured text channel; the
repository repeats the complete aggregate audit before opening its transaction. Original
source bytes and text therefore remain unavailable after the transient input is gone. A
checksum can authenticate a recovered copy, but cannot reconstruct missing source
content. Provenance authentication likewise does not imply that OrbitMind retained the
source itself or can replay it without an authorized recovered copy. A future evidence
vault requires separate retention, encryption, access-control, deletion, and rights
review.

Durability does not activate research. `ORBITMIND_OPEN_RESEARCH_ENABLED` remains false
by default and inert; there is still no scheduler, source adapter wiring, agent, LLM,
or self-modification behavior.

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

U4.0B stores retention classifications but does not implement retention execution,
deletion, legal hold, or raw-content storage. Those operations require a separately
reviewed policy and implementation.

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

The following remain deferred: raw evidence vault, retention/deletion operations, API
routes, authentication and authorization integration, source adapters, network research,
scheduler, multi-agent discussion, LLM claim generation, model training, automated code
changes, Workbench integration, live providers, deployment, and quantum-assisted research.
