"""Typed scientific-memory domain models (separate from persistence + API models)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.governance.epistemic import EpistemicStatus


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class DocumentType(StrEnum):
    REFERENCE_DERIVATIVE = "reference-derivative"
    ARCHITECTURE_DOC = "architecture-doc"
    ADR = "adr"
    FIXTURE = "fixture"
    DOMAIN_RECORD = "domain-record"


class ClaimStatus(StrEnum):
    EXTRACTED = "extracted"
    SOURCE_ASSERTED = "source-asserted"
    CALCULATED = "calculated"
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially-supported"
    DISPUTED = "disputed"
    CONTRADICTED = "contradicted"
    HYPOTHESIS = "hypothesis"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class EvidenceSupportType(StrEnum):
    SUPPORTS = "supports"
    PARTIALLY_SUPPORTS = "partially-supports"
    CONTRADICTS = "contradicts"
    CONTEXTUALIZES = "contextualizes"
    DERIVES_FROM = "derives-from"
    CALCULATES = "calculates"
    SUPERSEDES = "supersedes"
    DUPLICATES = "duplicates"


class ConceptDomain(StrEnum):
    SATELLITE = "satellite"
    ORBITAL_MECHANICS = "orbital-mechanics"
    SPACE_OBJECT = "space-object"
    ASTEROID = "asteroid"
    COMET = "comet"
    CLOSE_APPROACH = "close-approach"
    DATA_PROVENANCE = "data-provenance"
    SCIENTIFIC_VERIFICATION = "scientific-verification"
    QUANTUM_COMPUTING = "quantum-computing"
    VISUAL_INTELLIGENCE = "visual-intelligence"
    SCIENTIFIC_MEMORY = "scientific-memory"
    GENERAL = "general"


class ConceptKind(StrEnum):
    ENTITY = "entity"
    PROCESS = "process"
    PROPERTY = "property"
    METHOD = "method"
    ARTIFACT = "artifact"


class GraphEdgeKind(StrEnum):
    HAS_ORBIT = "has-orbit"
    SOURCED_FROM = "sourced-from"
    SUPPORTED_BY = "supported-by"
    CONTAINS = "contains"
    MENTIONS = "mentions"
    RELATED_TO = "related-to"
    CONTRADICTS = "contradicts"
    PRODUCED = "produced"
    DERIVES_FROM = "derives-from"
    CITES = "cites"
    SOLVED_BY = "solved-by"  # Phase 4A
    COMPARED_AGAINST = "compared-against"  # Phase 4A


class EntityKind(StrEnum):
    DOCUMENT = "document"
    CHUNK = "chunk"
    CONCEPT = "concept"
    CLAIM = "claim"
    EVIDENCE = "evidence"
    SPACE_OBJECT = "space-object"
    SATELLITE_MISSION = "satellite-mission"
    ORBITAL_ELEMENT_SOURCE = "orbital-element-source"
    SMALL_BODY = "small-body"
    CLOSE_APPROACH = "close-approach"
    SOURCE_POLICY = "source-policy"
    VERIFICATION_FINDING = "verification-finding"
    VISUAL_ARTIFACT = "visual-artifact"
    # Phase 4A — optimization
    OPTIMIZATION_PROBLEM = "optimization-problem"
    SOLVER_RUN = "solver-run"
    QUANTUM_EXPERIMENT = "quantum-experiment"
    BENCHMARK_COMPARISON = "benchmark-comparison"
    OPTIMIZATION_ARTIFACT = "optimization-artifact"
    SCHEDULE = "schedule"


class IngestionStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class RetrievalBackend(StrEnum):
    POSTGRES_FTS = "postgres-fts"
    DETERMINISTIC_LEXICAL = "deterministic-lexical"


# --------------------------------------------------------------------------
# Source / document / chunk
# --------------------------------------------------------------------------
class DocumentRights(BaseModel):
    model_config = ConfigDict(frozen=True)

    license_note: str = "internal repository document"
    attribution: str = ""
    requires_review: bool = False
    retention_note: str = "retained as ingested; superseded by newer versions on re-ingest"


class MemorySource(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=new_id)
    source_id: str  # stable slug, e.g. "repo-docs"
    name: str
    kind: str = "local-document"
    rights: DocumentRights = Field(default_factory=DocumentRights)


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    document_type: DocumentType
    language: str = "english"
    origin_label: str  # safe relative label, NEVER a full local path
    tags: list[str] = Field(default_factory=list)


class DocumentSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    section_path: str  # e.g. "Heading > Subheading"
    ordinal: int
    title: str


class DocumentChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    version_id: str
    section_path: str
    ordinal: int
    char_start: int
    char_end: int
    original_text: str
    search_text: str
    checksum: str
    language: str = "english"
    created_at: datetime = Field(default_factory=utcnow)


class DocumentVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=new_id)
    document_id: str
    version_no: int
    content_checksum: str
    normalized_checksum: str
    original_length: int
    created_at: datetime = Field(default_factory=utcnow)


class ScientificDocument(BaseModel):
    id: str = Field(default_factory=new_id)
    source_id: str
    metadata: DocumentMetadata
    rights: DocumentRights = Field(default_factory=DocumentRights)
    created_at: datetime = Field(default_factory=utcnow)


class IngestionRun(BaseModel):
    id: str = Field(default_factory=new_id)
    status: IngestionStatus = IngestionStatus.COMPLETED
    roots: list[str] = Field(default_factory=list)
    requested: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    documents: int = 0
    versions: int = 0
    chunks: int = 0
    errors: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


# --------------------------------------------------------------------------
# Concepts / terminology
# --------------------------------------------------------------------------
class ConceptTerm(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=new_id)
    term: str
    language: str = "english"
    is_canonical: bool = False


class ConceptSense(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=new_id)
    gloss: str
    sense_rank: int = 1


class ScientificConcept(BaseModel):
    id: str = Field(default_factory=new_id)
    canonical_name: str
    domain: ConceptDomain
    kind: ConceptKind = ConceptKind.ENTITY
    definition: str = ""
    source: str = "curated"
    language: str = "english"
    parent_concept_id: str | None = None
    terms: list[ConceptTerm] = Field(default_factory=list)
    senses: list[ConceptSense] = Field(default_factory=list)


class ConceptRelationship(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=new_id)
    from_concept_id: str
    to_concept_id: str
    relation: str = "related-to"
    provenance: str = "curated"


# --------------------------------------------------------------------------
# Claims / evidence / citations
# --------------------------------------------------------------------------
class ClaimSubject(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str
    concept_id: str | None = None


class ClaimPredicate(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str


class ClaimObject(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str
    units: str | None = None
    concept_id: str | None = None


class QuoteSpan(BaseModel):
    model_config = ConfigDict(frozen=True)

    char_start: int
    char_end: int
    quote: str = ""


class ScientificClaim(BaseModel):
    id: str = Field(default_factory=new_id)
    subject: ClaimSubject
    predicate: ClaimPredicate
    object: ClaimObject
    status: ClaimStatus = ClaimStatus.SOURCE_ASSERTED
    epistemic_status: EpistemicStatus = EpistemicStatus.ASSUMPTION
    document_id: str | None = None
    version_id: str | None = None
    chunk_id: str | None = None
    quote_span: QuoteSpan | None = None
    extractor_version: str = "manual-1"
    verification_status: str = "not-verified"
    limitations: str = "Source assertion; not independently verified by OrbitMind."
    created_at: datetime = Field(default_factory=utcnow)


class EvidenceLink(BaseModel):
    id: str = Field(default_factory=new_id)
    claim_id: str
    chunk_id: str | None = None
    record_ref: str | None = None  # for structured-record evidence (entity reference)
    support_type: EvidenceSupportType
    source: str
    explanation: str
    registrar_version: str = "manual-1"
    verification_state: str = "not-verified"
    created_at: datetime = Field(default_factory=utcnow)


class ContradictionRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    claim_id: str
    contradicting_claim_id: str
    explanation: str
    created_at: datetime = Field(default_factory=utcnow)


class CitationRecord(BaseModel):
    """A version-pinned citation to the exact stored chunk/version used in retrieval."""

    model_config = ConfigDict(frozen=True)

    source_title: str
    document_title: str
    section_path: str
    chunk_id: str
    document_id: str
    version_id: str
    version_no: int
    char_start: int
    char_end: int
    checksum: str
    origin_label: str  # safe relative label (no full local path)
    rights_note: str
    excerpt: str
    retrieved_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------
class RankingComponents(BaseModel):
    model_config = ConfigDict(frozen=True)

    lexical: float
    title_boost: float
    section_boost: float
    identifier_boost: float
    total: float


class RetrievalExplanation(BaseModel):
    model_config = ConfigDict(frozen=True)

    matched_terms: list[str]
    components: RankingComponents
    backend: RetrievalBackend
    reason: str


class RankedChunk(BaseModel):
    chunk_id: str
    document_id: str
    version_id: str
    title: str
    section_path: str
    rank_score: float
    explanation: RetrievalExplanation
    source_id: str
    document_type: str
    rights_note: str
    epistemic_status: str
    verification_status: str
    excerpt: str
    citation: CitationRecord


class RetrievalResult(BaseModel):
    query_text: str
    backend: RetrievalBackend
    total_candidates: int
    returned: int
    truncated: bool
    zero_result: bool
    results: list[RankedChunk]


class RetrievalMetric(BaseModel):
    name: str
    value: float


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------
class EntityReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: EntityKind
    entity_id: str
    label: str = ""


class GraphEdge(BaseModel):
    id: str = Field(default_factory=new_id)
    from_ref: EntityReference
    edge_kind: GraphEdgeKind
    to_ref: EntityReference
    source: str = "curated"
    weight: float | None = None
    # Benchmark that created this edge, when applicable (fifth review, High #3).
    benchmark_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class GraphNeighbor(BaseModel):
    edge_kind: GraphEdgeKind
    direction: str  # "out" | "in"
    entity: EntityReference
    source: str


class GraphNeighborsResult(BaseModel):
    entity_id: str
    depth: int
    neighbors: list[GraphNeighbor]
    truncated: bool
