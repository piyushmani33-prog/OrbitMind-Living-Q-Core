# Safety Requirements — OrbitMind Living Q-Core

Status: Living document · Binding for all phases.

These requirements are safety-critical. Violating one is a release blocker.

## 1. Scientific integrity
- SR-01 Deterministic tools (SGP4) perform calculations. An LLM MUST NEVER be
  asked to calculate orbital positions or numeric scientific results.
- SR-02 Use explicit SI / documented aerospace units everywhere.
- SR-03 Preserve raw input separately from normalized input.
- SR-04 Never label a generated explanation as verified evidence.
- SR-05 Never claim live satellite status from bundled sample TLE data.
- SR-06 Every major output carries exactly one epistemic status:
  `verified-fact | deterministic-calculation | model-estimate | hypothesis |
  assumption | unknown | rejected`.
- SR-07 Do not attach confidence percentages to deterministic calculations.
  Confidence is used only where a defensible scoring method exists.
- SR-08 Propagation failures are reported explicitly; invalid samples are never
  silently discarded.

## 2. Code & execution safety
- SR-09 Generated code is untrusted. No automatic promotion or self-deployment.
  Future lifecycle: lab → quarantine → testing → risk review → human approval → live.
- SR-10 No arbitrary command execution, arbitrary Python execution, or execution
  of user-provided files.
- SR-11 No unsafe deserialization (no `pickle`/`eval` on untrusted input).
- SR-12 No hidden network calls. Phase 0/1 makes no outbound network requests.

## 3. Filesystem safety
- SR-13 Artifacts are written ONLY under the configured artifacts directory.
  Any resolved path escaping that directory MUST be rejected (path-traversal guard).
- SR-14 Mission identifiers used in paths MUST be validated UUIDs, never raw
  user strings.

## 4. Data, secrets & rights
- SR-15 No credentials/secrets in code, logs, or version control. `.env` is
  gitignored; only `.env.example` (no secret values) is tracked.
- SR-16 Source fixtures record origin, date, license/use note, checksum, and a
  `test_only` flag. Data-use terms MUST be respected (Phase 2 connectors).
- SR-17 Error messages returned to clients MUST be safe: no stack traces, no
  internal paths, no environment values.

## 5. Approval boundaries (human-in-the-loop)
- SR-18 Risky actions require human approval (modeled now via `ApprovalRecord`;
  enforced as features that need it arrive). Phase 1 missions are read-only
  compute and need no approval.
- SR-19 Destructive operations, credential use, paid services, and cloud resource
  creation are out of scope and require explicit owner approval.

## 6. Input hardening
- SR-20 Enforce input size/volume limits (max samples, max duration, max step) to
  prevent resource exhaustion.
- SR-21 Reject unsupported satellite identifiers and output types rather than
  guessing.
