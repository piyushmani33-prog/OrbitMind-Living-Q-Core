"""Deterministic, allowlisted document ingestion (no execution, no network).

Only files under approved roots, with approved extensions and sizes, that are not
secret-like, are ingested. Duplicates (unchanged content) are detected; changed
content creates a new version. Document contents are never executed.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from orbitmind.core.config import PROJECT_ROOT, Settings
from orbitmind.core.timeutils import utcnow
from orbitmind.memory.chunking import chunk_document
from orbitmind.memory.models import (
    DocumentMetadata,
    DocumentType,
    DocumentVersion,
    IngestionRun,
    IngestionStatus,
    MemorySource,
    ScientificDocument,
)
from orbitmind.memory.normalization import content_checksum, normalize_line_endings
from orbitmind.memory.repository import SqlAlchemyMemoryRepository

_SECRET_HINTS = ("secret", "token", "credential", "password", "apikey", "api_key")
_SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".crt", ".cer")


class IngestionRequest(BaseModel):
    """Request to ingest approved documents (relative paths and/or an approved root)."""

    source_id: str = Field(default="repo-docs", min_length=1, max_length=64)
    paths: list[str] = Field(default_factory=list)
    root: str | None = None
    max_files: int = Field(default=200, ge=1, le=1000)


class FileOutcome(BaseModel):
    """Per-file ingestion outcome."""

    label: str
    status: str  # created | updated | duplicate | rejected
    reason: str = ""
    chunks: int = 0


def _is_secret_like(name: str) -> bool:
    low = name.lower()
    if low == ".env" or low.startswith(".env"):
        return True
    if low.endswith(_SECRET_SUFFIXES):
        return True
    return any(hint in low for hint in _SECRET_HINTS)


def _document_type(rel_label: str) -> DocumentType:
    low = rel_label.replace("\\", "/").lower()
    if "/decisions/adr" in low or "/adr-" in low:
        return DocumentType.ADR
    if low.startswith("docs/reference/extracted"):
        return DocumentType.REFERENCE_DERIVATIVE
    if low.startswith("docs/"):
        return DocumentType.ARCHITECTURE_DOC
    return DocumentType.FIXTURE


def _title_from(text: str, fallback: str) -> str:
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


class IngestionService:
    """Ingests approved documents into scientific memory."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._roots = settings.resolved_ingestion_roots()

    def _resolve_safe(self, rel_path: str) -> tuple[Path | None, str]:
        candidate = (PROJECT_ROOT / rel_path).resolve()
        if not any(candidate == root or root in candidate.parents for root in self._roots):
            return None, "outside the allowlisted ingestion roots"
        if not candidate.is_file():
            return None, "not a file"
        if _is_secret_like(candidate.name):
            return None, "secret-like filename"
        if candidate.suffix.lower() not in self._settings.memory_allowed_extensions:
            return None, f"unsupported extension '{candidate.suffix}'"
        if candidate.stat().st_size > self._settings.memory_max_file_bytes:
            return None, "file exceeds maximum size"
        return candidate, ""

    def _expand_root(self, root_rel: str, max_files: int) -> list[str]:
        root = (PROJECT_ROOT / root_rel).resolve()
        if not any(root == r or r in root.parents or root in r.parents for r in self._roots):
            return []
        files: list[str] = []
        for ext in self._settings.memory_allowed_extensions:
            for path in sorted(root.rglob(f"*{ext}")):
                if path.is_file() and not _is_secret_like(path.name):
                    files.append(path.relative_to(PROJECT_ROOT).as_posix())
        return sorted(set(files))[:max_files]

    def ingest(
        self, request: IngestionRequest, repo: SqlAlchemyMemoryRepository
    ) -> tuple[IngestionRun, list[FileOutcome]]:
        """Ingest documents; return the run + per-file outcomes."""
        repo.upsert_source(
            MemorySource(source_id=request.source_id, name=request.source_id, kind="local-document")
        )
        rel_paths = list(request.paths)
        if request.root:
            rel_paths.extend(self._expand_root(request.root, request.max_files))
        rel_paths = list(dict.fromkeys(rel_paths))[: request.max_files]

        run = IngestionRun(roots=[request.root] if request.root else ["explicit-paths"])
        run.requested = len(rel_paths)
        outcomes: list[FileOutcome] = []

        for rel in rel_paths:
            path, reason = self._resolve_safe(rel)
            label = Path(rel).as_posix()
            if path is None:
                run.rejected += 1
                run.errors.append(f"{label}: {reason}")
                outcomes.append(FileOutcome(label=label, status="rejected", reason=reason))
                continue
            try:
                raw = path.read_bytes().decode("utf-8")  # strict: malformed UTF-8 -> reject
            except UnicodeDecodeError:
                run.rejected += 1
                run.errors.append(f"{label}: malformed UTF-8")
                outcomes.append(
                    FileOutcome(label=label, status="rejected", reason="malformed UTF-8")
                )
                continue

            origin_label = path.relative_to(PROJECT_ROOT).as_posix()
            text = normalize_line_endings(raw)
            status, chunk_count = self._ingest_one(
                repo, request.source_id, origin_label, text, content_checksum(text)
            )
            run.accepted += 1
            if status == "duplicate":
                run.duplicates += 1
            else:
                if status == "created":
                    run.documents += 1
                run.versions += 1
                run.chunks += chunk_count
            outcomes.append(FileOutcome(label=origin_label, status=status, chunks=chunk_count))

        if run.rejected and not run.accepted:
            run.status = IngestionStatus.FAILED
        elif run.rejected:
            run.status = IngestionStatus.PARTIAL
        else:
            run.status = IngestionStatus.COMPLETED
        run.finished_at = utcnow()
        repo.add_ingestion_run(run)
        return run, outcomes

    def _ingest_one(
        self,
        repo: SqlAlchemyMemoryRepository,
        source_id: str,
        origin_label: str,
        text: str,
        checksum: str,
    ) -> tuple[str, int]:
        existing = repo.find_document(source_id, origin_label)
        if existing is not None:
            latest = repo.latest_version(existing.id)
            if latest is not None and latest.content_checksum == checksum:
                return "duplicate", 0  # unchanged content -> no new version
            document_id = existing.id
            version_no = (latest.version_no + 1) if latest else 1
            status = "updated"
        else:
            document = ScientificDocument(
                source_id=source_id,
                metadata=DocumentMetadata(
                    title=_title_from(text, Path(origin_label).stem),
                    document_type=_document_type(origin_label),
                    origin_label=origin_label,
                ),
            )
            repo.add_document(document)
            document_id = document.id
            version_no = 1
            status = "created"

        version = DocumentVersion(
            document_id=document_id,
            version_no=version_no,
            content_checksum=checksum,
            normalized_checksum=checksum,
            original_length=len(text),
        )
        repo.add_version(version)
        sections, chunks = chunk_document(
            text,
            document_id=document_id,
            version_id=version.id,
            max_chars=self._settings.memory_chunk_max_chars,
            overlap=self._settings.memory_chunk_overlap_chars,
            language=self._settings.memory_fts_language,
        )
        repo.add_sections(version.id, sections)
        repo.add_chunks(chunks)
        return status, len(chunks)
