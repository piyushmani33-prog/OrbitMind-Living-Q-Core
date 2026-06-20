# Adding a Concept

The concept registry is **curated and deterministic** — no automatic universal ontology
creation (Phase 3B). See [ADR-0019](../architecture/decisions/ADR-0019-scientific-memory-model.md).

## Model
`ScientificConcept`: `canonical_name`, `domain` (`ConceptDomain`), `kind`
(`ConceptKind`), `definition`, `source`, `language`, optional `parent_concept_id`, plus
`terms` (`ConceptTerm` — aliases, one canonical) and `senses` (`ConceptSense` — sense
distinction with a rank).

`ConceptDomain` values: satellite, orbital-mechanics, space-object, asteroid, comet,
close-approach, data-provenance, scientific-verification, quantum-computing,
visual-intelligence, scientific-memory, general.

## Register a concept
```bash
curl -X POST localhost:8000/api/v1/memory/concepts \
  -H 'content-type: application/json' \
  -d '{
        "canonical_name": "Two-Line Element set",
        "domain": "orbital-mechanics",
        "definition": "Encodes orbital elements at an epoch.",
        "terms": [
          {"term": "TLE", "is_canonical": true},
          {"term": "Two-Line Element"}
        ],
        "senses": [{"gloss": "A standard satellite element set.", "sense_rank": 1}]
      }'
```
Each term is stored with a normalized form so it is matchable by
`find_concept_ids_by_term`. List/filter by domain:
```bash
curl "localhost:8000/api/v1/memory/concepts?domain=orbital-mechanics"
```

## How concepts help retrieval
Supplying `concept_ids` (or `domains`) in a `MemorySearchRequest` expands the query with
the concept's terms as a soft matching signal — concept-term matching contributes to the
rank but does not bypass metadata filters.
