"""Scientific memory (Phase 3B): durable documents, concepts, claims, evidence,
citations, lightweight graph relations, and deterministic retrieval.

Memory is NOT truth and retrieval is NOT verification: a source asserting a claim is
not a verified fact. Outputs are evidence records and ranked, citable passages — never
a generated conversational answer (deferred). PostgreSQL is the production store;
SQLite is used for fast local tests with a clearly-labelled deterministic retrieval
fallback (ADR-0018/0021/0023).
"""
