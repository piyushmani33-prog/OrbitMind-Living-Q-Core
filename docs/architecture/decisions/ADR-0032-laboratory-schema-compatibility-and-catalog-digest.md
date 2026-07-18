# ADR-0032 — Laboratory Schema Compatibility and Catalog Digest

- **Status:** Accepted (2026-07-18)

## Context

The U6 Laboratory Foundation has strict immutable manifests and a deterministic
in-process registry, but its schema string was only a model literal, its existing
`compatibility` object was descriptive rather than enforced, and the catalog had no
stable identity. Future modules need a narrow way to reject incompatible metadata
without making manifests executable, introducing plugin discovery, or conflating
identity with trust.

## Decision

- Keep the existing public string field `schema_version` and centrally support only
  `laboratory-manifest-v1` in this slice. Parsing and registration fail closed. No
  automatic schema upgrade or translator is introduced.
- Treat additive schema changes as an explicitly supported new minor schema, and
  breaking changes as a new major schema. Each requires code, tests, compatibility
  review, and approved migration or translation rules when applicable.
- Define the independent Laboratory Framework contract version as strict,
  dependency-free `1.0.0`. Its canonical bounded ASCII grammar is
  `MAJOR.MINOR.PATCH` with no expression, sign, whitespace, prerelease, or build
  metadata.
- Add immutable structured `framework_compatibility` bounds to every manifest:
  `minimum_inclusive <= framework_version < maximum_exclusive`. The existing
  `compatibility` object remains a descriptive package/Mission statement.
- Reject unsupported schemas and ranges that exclude the current framework before
  registry mutation. The errors are typed, stable, and safe.
- Define catalog identity as SHA-256 over domain-separated canonical UTF-8 JSON:
  `b"orbitmind.laboratory.catalog.v1\0" + canonical_payload`. The payload contains
  digest-format identity, catalog-schema identity, supported manifest-schema
  identities, framework contract version, and all registered manifests sorted by id.
- Expose the frozen typed digest as the additive `catalog_digest` field of the
  existing catalog projection. No new route is necessary.

## Alternatives considered

- **Use the package version as framework compatibility**: rejected because package
  release cadence and Laboratory contract semantics are different concerns.
- **Parse rich package-version expressions**: rejected because a structured bounded
  range is clearer, dependency-free, and has no implicit expansion.
- **Keep compatibility descriptive only**: rejected because future manifests could
  silently register against an unsupported contract.
- **Expose a digest endpoint or make it a signature**: rejected because this slice
  needs identity only, not a verification service, trust claim, or authority.

## Consequences

- New manifest authors must state compatibility explicitly.
- Incompatible or unknown schema data is rejected locally and atomically.
- Equal catalog semantics have the same digest regardless of registration order;
  semantic changes yield a different digest.
- The digest does not authorize a laboratory, prove installation safety, or make
  anything executable. The Mission remains the governed work primitive.

## Golden vector

The empty registry canonical payload is exactly:

```json
{"catalog_digest_format_version":"laboratory-catalog-digest-v1","catalog_schema_version":"laboratory-catalog-v1","framework_contract_version":"1.0.0","laboratories":[],"supported_manifest_schema_versions":["laboratory-manifest-v1"]}
```

The UTF-8 preimage is the exact domain separator
`orbitmind.laboratory.catalog.v1\0` followed by those bytes. Its SHA-256 digest is
`76d0070395bb1b1e5a6a4fdea9b1b7fcc18743ac991e936de5179406cd1396ad`.

## Review trigger

Revisit before supporting another manifest schema, changing the framework contract
major version, adding a manifest translator, or using a digest for any protocol
outside local catalog identity.
