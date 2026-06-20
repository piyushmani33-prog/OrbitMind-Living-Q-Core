"""Version-pinned citation construction (points to the exact stored chunk/version)."""

from __future__ import annotations

from orbitmind.core.timeutils import utcnow
from orbitmind.memory.models import CitationRecord
from orbitmind.memory.repository import ChunkContext

_EXCERPT_CHARS = 280


def build_citation(context: ChunkContext) -> CitationRecord:
    """Build a citation pinned to the exact chunk + document version used."""
    chunk = context.chunk
    doc = context.document
    excerpt = chunk.original_text.strip().replace("\n", " ")[:_EXCERPT_CHARS]
    rights = doc.rights or {}
    return CitationRecord(
        source_title=doc.source_id,
        document_title=doc.title,
        section_path=chunk.section_path,
        chunk_id=chunk.id,
        document_id=doc.id,
        version_id=chunk.version_id,
        version_no=context.version_no,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        checksum=chunk.checksum,
        origin_label=doc.origin_label,
        rights_note=str(rights.get("license_note", "internal repository document")),
        excerpt=excerpt,
        retrieved_at=utcnow(),
    )
