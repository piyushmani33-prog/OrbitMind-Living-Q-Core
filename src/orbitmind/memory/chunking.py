"""Deterministic, structure-aware Markdown chunking (no LLM).

Chunks are reproducible from the document version + position, char-range accurate,
and section-aware (headings/paragraphs). Over-long segments are windowed with a
controlled overlap.
"""

from __future__ import annotations

import re

from orbitmind.core.checksums import sha256_text
from orbitmind.memory.models import DocumentChunk, DocumentSection
from orbitmind.memory.normalization import search_normalize

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _segments(text: str) -> list[tuple[str, int, int]]:
    """Return (section_path, char_start, char_end) blocks (paragraphs + headings)."""
    lines = text.split("\n")
    starts: list[int] = []
    pos = 0
    for line in lines:
        starts.append(pos)
        pos += len(line) + 1

    heading_stack: list[tuple[int, str]] = []
    segments: list[tuple[str, int, int]] = []
    cur_start: int | None = None
    cur_end = 0

    def section_path() -> str:
        return " > ".join(title for _level, title in heading_stack)

    def flush() -> None:
        nonlocal cur_start
        if cur_start is not None:
            segments.append((section_path(), cur_start, cur_end))
            cur_start = None

    for i, line in enumerate(lines):
        start = starts[i]
        end = start + len(line)
        heading = _HEADING.match(line)
        if heading is not None:
            flush()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            segments.append((section_path(), start, end))
        elif line.strip() == "":
            flush()
        else:
            if cur_start is None:
                cur_start = start
            cur_end = end
    flush()
    return segments


def chunk_document(
    text: str,
    *,
    document_id: str,
    version_id: str,
    max_chars: int,
    overlap: int,
    language: str = "english",
) -> tuple[list[DocumentSection], list[DocumentChunk]]:
    """Chunk a (line-ending normalized) document deterministically."""
    segments = _segments(text)
    chunks: list[DocumentChunk] = []
    ordinal = 0

    def emit(section: str, start: int, end: int) -> None:
        nonlocal ordinal
        original = text[start:end]
        chunks.append(
            DocumentChunk(
                id=f"{version_id}-{ordinal:04d}",
                document_id=document_id,
                version_id=version_id,
                section_path=section,
                ordinal=ordinal,
                char_start=start,
                char_end=end,
                original_text=original,
                search_text=search_normalize(original),
                checksum=sha256_text(original),
                language=language,
            )
        )
        ordinal += 1

    i = 0
    while i < len(segments):
        section, start, end = segments[i]
        j = i + 1
        while (
            j < len(segments)
            and segments[j][0] == section
            and (segments[j][2] - start) <= max_chars
        ):
            end = segments[j][2]
            j += 1
        if (end - start) > max_chars:
            window_start = start
            while window_start < end:
                window_end = min(window_start + max_chars, end)
                emit(section, window_start, window_end)
                if window_end >= end:
                    break
                window_start = max(window_end - overlap, window_start + 1)
            i = j
        else:
            emit(section, start, end)
            i = j

    # Sections in first-appearance order.
    seen: dict[str, int] = {}
    sections: list[DocumentSection] = []
    for path, _s, _e in segments:
        if path and path not in seen:
            seen[path] = len(seen)
            sections.append(DocumentSection(section_path=path, ordinal=len(sections), title=path))
    return sections, chunks
