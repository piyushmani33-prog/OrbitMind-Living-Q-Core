# ADR-0001 — Modular Monolith Architecture

- **Status:** Accepted (2026-06-19)
- **Owner decision:** Pre-approved in the build specification.

## Context
OrbitMind must eventually span many scientific domains and heavy compute
(simulation, quantum). Early over-distribution (microservices, a fixed swarm of
108 agents) would add network failure modes, distributed-tracing burden, and cost
with no current load to justify it. The first deliverable is a single offline
vertical slice.

## Decision
Build a **modular monolith**: one deployable FastAPI process with strongly
bounded internal modules and typed in-process interfaces. A single Prime
Orchestrator dynamically invokes domain modules. High-load modules (`quantum`,
future `simulation`) are designed as adapter seams that can be extracted to
services later *only when measured load justifies it*.

## Alternatives considered
1. **Service-oriented (few services).** Independent scaling but premature contracts
   and ops overhead. Rejected for current stage.
2. **Microservice/agent-swarm.** Matches "living swarm" branding but explicitly
   forbidden by the spec; severe over-engineering and cost. Rejected.
3. **Single unstructured script.** Fast but no boundaries; unmaintainable. Rejected.

## Consequences
- Fast local development, simple testing, one process to run.
- Requires discipline: a documented dependency rule
  (`api → orchestration → domain → persistence → core`) enforced in review.
- Extraction to services remains possible via the adapter seams.

## Review trigger
Revisit if (a) measured throughput/latency requires independent scaling of a
module, (b) team size makes a single codebase a bottleneck, or (c) the reference
documents mandate a different topology.
