# ADR-0008 — CelesTrak General Perturbations Connector

- **Status:** Accepted (2026-06-19)

## Context
Phase 2 introduces the first real data connector. CelesTrak publishes orbital
elements (General Perturbations / OMM) in machine-readable formats. We must consume
it behind a generic interface, reuse the existing deterministic SGP4 path, and not
let source-specific structures leak into the application. The exact endpoint and
licensing terms are not confirmed by any reference document available offline
(R-012).

## Decision
- Implement `CelestrakConnector` behind a generic `OrbitalSource` interface
  (`sources/interface.py`). The orchestrator depends on a `SourceResolver`, never on
  the connector directly.
- Consume the **structured GP/OMM JSON** format (`gp.php?CATNR=<norad>&FORMAT=json`).
  **No HTML scraping.**
- Validate each response into a source-specific `CelestrakGpRecord`, then normalize
  to OMM fields and build **canonical TLE lines** via `sgp4.omm.initialize` +
  `exporter.export_tle` (`space/elements.py`). The rest of the system consumes the
  unchanged TLE→SGP4 path (verified to round-trip to < 1e-5 km).
- The endpoint base URL is **configurable** (`ORBITMIND_CELESTRAK_BASE_URL`), not
  hard-coded, and its hostname is allowlisted from the configured URL.
- CelesTrak satellite identifiers are restricted to **NORAD catalog numbers**
  (digits), never arbitrary input.
- All tests use **offline mocked HTTP**; no live calls in the test suite.

## Alternatives considered
1. **`FORMAT=tle` text.** Simpler to map, but the prompt prefers a structured GP
   format; JSON also enables schema validation. Rejected as the primary format.
2. **HTML scraping of CelesTrak pages.** Fragile and explicitly forbidden. Rejected.
3. **A heavy third-party SDK / Skyfield's loaders.** Unnecessary for a simple HTTPS
   JSON GET; violates the minimal-dependency policy. Rejected (added only `httpx`).
4. **Changing the propagation signature to accept OMM directly.** Would break the
   Phase 1 tests; the TLE-export approach reuses the verified path unchanged.

## Consequences
- A clean connector boundary; CelesTrak structures stay inside `sources/celestrak/`.
- The OMM→TLE export adds a tiny, deterministic normalization step (well under the
  TLE rounding precision).
- The endpoint/licensing remain "to verify" (R-012); mitigated by configurability,
  offline fixtures, and explicit "requires review" rights labeling (ADR-0009/0010,
  DATA_RIGHTS_AND_SOURCE_POLICY.md).

## Review trigger
Revisit when adding a second connector (Phase 2+ pattern), when the official
endpoint/licensing is confirmed, or if CelesTrak changes its GP JSON schema.
