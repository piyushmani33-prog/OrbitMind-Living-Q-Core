# Security Policy

OrbitMind is a local/API-first research project in **Solo Alpha / reviewer-ready**
state. This document describes how to report a concern privately. It makes **no
production-readiness or security-certification claim**.

## Reporting a suspected secret or vulnerability

Please report privately — **do not open a public issue and do not post secrets,
tokens, credentials, or raw logs publicly**.

- Preferred: use GitHub's private vulnerability reporting for this repository
  (**Security → Report a vulnerability**), if enabled.
- Or email the maintainer: **Piyush Mani** — piyush.mani3399@gmail.com.

When reporting, include a sanitized description (the affected file/endpoint and a
redacted summary) rather than the raw sensitive value.

## Secret-scanning status

- The **current tracked source has been scanned and is clean** of real secrets.
- **Old Git-history scanner findings may still appear.** These originate from
  **deterministic test fixtures** (for example, fixed signing/known-answer keys used
  only to exercise signing code paths). **They are not credentials**, carry no access,
  and reveal nothing sensitive.
- Because no real secret was ever committed, **Git history is intentionally not
  rewritten.** History would be rewritten only if a genuine secret were found.

## Scope and non-claims

- This project validates a deterministic, offline, bundled sample/test-only mission
  workflow. It is **not production-ready, not a public alpha, not live tracking, not
  live-provider validation, and not a quantum-advantage claim**.
- Nothing here constitutes command readiness, approval, certification, or a security
  certification.
