# Retrieval Evaluation

Offline, deterministic evaluation of memory retrieval against a curated gold dataset.
**No LLM is used as the evaluator** (`memory/evaluation.py`).

## Gold dataset
`data/samples/memory/eval/gold.json` — each item maps a `query` to `relevant_markers`
(content substrings expected in a relevant chunk) and optional `distractors`. Relevance
is judged deterministically by marker presence in the retrieved chunk's title / section /
text.

## Metrics
- **recall@k** — fraction of queries with a relevant chunk in the top-k.
- **mean reciprocal rank (MRR)** — mean of `1/rank` of the first relevant result.
- **nDCG@k** — binary-relevance discounted gain.
- **citation completeness** — fraction of results carrying a complete (chunk + checksum)
  citation.
- **duplicate-result rate** — repeated chunk ids within a result set.
- **zero-result rate** — fraction of queries returning nothing.
- **reproducibility** — identical orderings across two runs (asserted `True`).

## Run it
Offline, via the API or service against an ingested corpus:
```bash
curl -X POST localhost:8000/api/v1/memory/evaluations \
  -H 'content-type: application/json' \
  -d '{"k":5,"gold":[{"query":"why is SGP4 not used for asteroids","relevant_markers":["heliocentric"]}]}'
```
In tests, `tests/test_memory_evaluation.py` ingests the bundled glossary + Phase 3 docs
and asserts `recall@5 ≥ 0.8`, `citation_completeness == 1.0`, `zero_result_rate == 0.0`,
and `reproducible == True`.

## Dialect note
Evaluation runs on the active dialect. On SQLite it exercises the deterministic lexical
backend; on PostgreSQL it exercises full-text candidate selection. The ranking formula is
identical; only candidate selection differs (see
[../architecture/DETERMINISTIC_RETRIEVAL.md](../architecture/DETERMINISTIC_RETRIEVAL.md)).
