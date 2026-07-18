# U6.1B Laboratory Contract Hardening Review

## Scope

U6.1B hardens Laboratory metadata only: explicit schema policy, strict framework
compatibility, registry rejection, and deterministic catalog identity. It does not
add an Agent Runtime, permission grant, approval record, tool, adapter, plugin,
installation, activation, execution, route, dependency, lock, or migration.

## Contract review

- `schema_version` remains a string and is centrally fail-closed. There is no
  automatic upgrade, coercion, or multiple-translator mechanism.
- The independent `1.0.0` framework contract version has a bounded ASCII parser
  with deterministic ordering. It is not the package version or schema version.
- `framework_compatibility` is a strict frozen structured inclusive/exclusive range;
  the old descriptive `compatibility` field is retained intact.
- Registry validation occurs before its only mutation, so unsupported schemas and
  incompatible ranges leave the instance unchanged and produce typed safe errors.

## Catalog identity review

The catalog digest uses `sha256` of the exact domain separator
`orbitmind.laboratory.catalog.v1\0` plus sorted-key compact UTF-8 JSON. It includes
the catalog/schema/framework identities and all registered manifest semantics,
including compatibility ranges. It intentionally excludes mutable process state,
timestamps, paths, credentials, and registration order. It is a checksum identity,
not a signature, approval, trust statement, readiness signal, or authority.

## API and authority review

The existing API is an envelope, so the frozen `catalog_digest` object is one
backward-compatible additive field of the existing read-only projection. The
Workbench consumes that projection unchanged, no new route exists, and no frontend
maintains a second digest. Capability declaration, compatibility, registration, and
digest calculation remain non-executing metadata operations.

## Validation and residual risk

Focused contract, registry, API, architecture, and Workbench tests cover strict
grammar, range bounds, atomic rejection, canonicalization, golden vectors, and
projection behavior. Static checks, Alembic integrity, and the complete source suite
are recorded in external U6.1B evidence. Future schema support, protocol use beyond
identity, and any execution/permission design require new reviewed decisions.
