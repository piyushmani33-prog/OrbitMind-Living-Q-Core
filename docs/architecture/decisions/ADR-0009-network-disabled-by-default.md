# ADR-0009 — Network Disabled by Default

- **Status:** Accepted (2026-06-19)

## Context
Phase 2 adds the ability to make outbound HTTPS requests (CelesTrak). The platform
must remain safe-by-default: no hidden network calls, no network during startup or
tests, and no surprise egress. SR-12 forbids hidden network calls.

## Decision
- Outbound network is **disabled by default**. A live request requires **both**:
  `ORBITMIND_NETWORK_ENABLED=true` **and** the per-source switch
  `ORBITMIND_CELESTRAK_ENABLED=true`. The effective policy switch is the logical AND.
- The safe HTTP fetcher (`sources/http_client.py`) enforces: HTTPS only, hostname
  allowlist, **no redirects**, explicit connect/read timeouts, bounded retries with
  backoff (no infinite retry), a response-size cap (streamed), content-type
  validation, a descriptive `User-Agent`, GET only, and no arbitrary user URL.
- No network on startup, no network from `/health`, and **no network in tests** —
  enforced by an autouse guard that blocks the real httpx transport; connector tests
  inject a `MockTransport`.
- No credentials are used or required.

## Alternatives considered
1. **Network enabled by default with a kill-switch.** Higher risk of accidental/
   hidden egress; contradicts safe-by-default. Rejected.
2. **A single global switch.** Less granular; a per-source switch lets each source be
   enabled independently. Rejected in favor of the two-control AND.

## Consequences
- The default developer/CI experience is fully offline and reproducible.
- Enabling live data is explicit and auditable; a disabled request fails safely
  (`network_disabled`, HTTP 409) and is recorded (`source.network_rejected`).
- Slightly more configuration surface (two switches), documented in `.env.example`.

## Review trigger
Revisit if/when authentication, per-tenant network policy, or an egress proxy is
introduced (Phase 8), or when adding sources that require credentials.
