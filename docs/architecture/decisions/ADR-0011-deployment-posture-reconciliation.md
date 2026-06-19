# ADR-0011 — Deployment Posture (Cloud-First Target, Local-First Now)

- **Status:** Accepted (2026-06-19)
- **Relates to:** ADR-0001 (modular monolith), ADR-0003 (storage), ADR-0004 (workflow);
  does **not** supersede them.

## Context
The now-inspected reference documents (`OrbitMind Living Q-Core.docx`, Feasibility
Brief) are explicit that the **production posture is cloud-first** — "Linux
containers from day one," deploy first on a managed container platform (Azure
Container Apps recommended), with PostgreSQL + pgvector, Redis, Temporal,
S3/MinIO object storage, a secrets manager, and OpenTelemetry. The current
implementation (Phases 0–2) is **local-first**: SQLite, in-process workflow, no
cloud resources, network disabled by default.

This ADR records the (apparent) divergence and the reconciliation, so the accepted
decisions are not silently changed.

## Decision
- **Affirm the cloud-first target** as the production direction of record, per the
  references: managed Linux containers, PostgreSQL+pgvector (ADR-0003), Temporal
  (ADR-0004), object storage, managed identity + secrets manager, OpenTelemetry —
  scheduled in **Phase 8 (cloud hardening)**.
- **Keep local-first for now** (Phases 0–2): the references' own roadmap begins with
  a "Foundations" phase, and the repository is already **cloud-portable** (Dockerfile,
  compose, repository interfaces, config via env, network-disabled-by-default). This
  is a **sequencing** choice, not a rejection of cloud-first.
- **No scope expansion here:** no cloud resource is provisioned; cloud deployment
  continues to require explicit owner approval.

## Conflict analysis
- *Apparent conflict:* references say "cloud-first, not local-first"; current build
  runs locally.
- *Resolution:* the conflict is one of **phase/sequencing**, not architecture. The
  end-state (cloud-first managed platform) is unchanged and now explicitly recorded;
  the path there is staged so each phase is testable offline first. The references
  themselves stage delivery (Foundations → … → Hardening and scale).

## Consequences
- The cloud-first target is now documented of record (previously only implied in
  `DEPLOYMENT_ARCHITECTURE.md`/ROADMAP).
- Migration requirements when Phase 8 begins: swap SQLite→PostgreSQL via the
  existing repository interfaces (ADR-0003), substitute the Temporal-backed workflow
  behind the existing interface (ADR-0004), add object storage for artifacts/cache,
  move secrets to a managed vault, and add OpenTelemetry exporters. None require
  domain-logic rewrites.
- History preserved: ADR-0001/0003/0004 remain as accepted; this ADR only adds the
  explicit cloud-first target + sequencing rationale.

## Review trigger
Revisit at the start of Phase 8 (cloud hardening), or if the owner chooses a cloud
provider / requires earlier cloud deployment.
