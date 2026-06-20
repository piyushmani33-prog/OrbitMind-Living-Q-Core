# Registering Claims

Claims are registered **conservatively** — explicit, typed, provenance-complete. **No
open-ended LLM extraction** (Phase 3B). See
[CLAIMS_AND_EVIDENCE.md](../architecture/CLAIMS_AND_EVIDENCE.md).

## Register a claim
```bash
curl -X POST localhost:8000/api/v1/memory/claims \
  -H 'content-type: application/json' \
  -d '{
        "subject":   {"value": "SGP4"},
        "predicate": {"value": "is-not-used-for"},
        "object":    {"value": "asteroids"},
        "chunk_id":  "<a real chunk id from /documents/{id}/chunks>",
        "status":    "source-asserted"
      }'
```
A claim defaults to `status=source-asserted` and `epistemic_status=assumption` and is
**never** auto-labelled `verified-fact`. The service rejects:
- empty subject / predicate / object,
- a `chunk_id` that does not exist.

## Link evidence
```bash
curl -X POST localhost:8000/api/v1/memory/evidence \
  -H 'content-type: application/json' \
  -d '{
        "claim_id": "<claim id>",
        "chunk_id": "<chunk id>",
        "support_type": "supports",
        "source": "repo-docs",
        "explanation": "The cited passage asserts this."
      }'
```
Evidence must reference an existing claim and either a chunk or a structured record.

## Retrieve a claim + evidence
```bash
curl localhost:8000/api/v1/memory/claims/<claim id>
```
Returns the claim, its evidence links, and the memory disclaimer.
