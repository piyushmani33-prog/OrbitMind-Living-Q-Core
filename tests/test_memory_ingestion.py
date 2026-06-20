"""Ingestion: allowlist, secret rejection, traversal, dedup, versioning, Unicode."""

from __future__ import annotations

from pathlib import Path

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.memory.ingestion import IngestionRequest, IngestionService
from orbitmind.memory.repository import SqlAlchemyMemoryRepository
from orbitmind.persistence.database import Database


def _repo(db: Database) -> tuple[SqlAlchemyMemoryRepository, object]:
    session = db.session()
    return SqlAlchemyMemoryRepository(session), session


@pytest.fixture
def hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[IngestionService, Database]:
    """An ingestion service whose allowlisted root is a temp dir under a fake root."""
    root = tmp_path / "mem"
    root.mkdir()
    monkeypatch.setattr("orbitmind.memory.ingestion.PROJECT_ROOT", tmp_path)
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'm.db').as_posix()}",
        memory_ingestion_roots=(str(root),),
        memory_max_file_bytes=2000,
        env="test",
    )
    db = Database(settings.database_url)
    db.create_all()
    return IngestionService(settings), db


def test_happy_path_creates_document_versions_and_chunks(
    hermetic: tuple[IngestionService, Database],
) -> None:
    svc, db = hermetic
    root = Path(svc._roots[0])
    (root / "good.md").write_text("# Heading\n\nBody about orbits.\n", encoding="utf-8")
    repo, session = _repo(db)
    run, outcomes = svc.ingest(IngestionRequest(source_id="t", paths=["mem/good.md"]), repo)
    session.commit()
    assert run.documents == 1 and run.versions == 1 and run.chunks >= 1
    assert outcomes[0].status == "created"


def test_rejects_secret_like_extension_size_and_outside_root(
    hermetic: tuple[IngestionService, Database],
) -> None:
    svc, db = hermetic
    root = Path(svc._roots[0])
    (root / ".env").write_text("SECRET=1", encoding="utf-8")
    (root / "creds_token.md").write_text("x", encoding="utf-8")
    (root / "key.pem").write_text("x", encoding="utf-8")
    (root / "data.bin").write_text("x", encoding="utf-8")
    (root / "big.md").write_text("# Big\n\n" + ("z" * 5000), encoding="utf-8")
    repo, session = _repo(db)
    run, outcomes = svc.ingest(
        IngestionRequest(
            source_id="t",
            paths=[
                "mem/.env",
                "mem/creds_token.md",
                "mem/key.pem",
                "mem/data.bin",
                "mem/big.md",
                "../pyproject.toml",  # path traversal outside the root
            ],
        ),
        repo,
    )
    session.commit()
    assert run.documents == 0
    statuses = {o.label: o.status for o in outcomes}
    assert all(s == "rejected" for s in statuses.values())
    reasons = " ".join(run.errors)
    assert "secret-like" in reasons
    assert "unsupported extension" in reasons
    assert "maximum size" in reasons
    assert "allowlisted" in reasons


def test_path_traversal_to_dotenv_is_rejected(
    hermetic: tuple[IngestionService, Database],
) -> None:
    svc, db = hermetic
    repo, session = _repo(db)
    run, _ = svc.ingest(
        IngestionRequest(source_id="t", paths=["mem/../../.env", "mem/../../../etc/passwd"]),
        repo,
    )
    session.commit()
    assert run.accepted == 0 and run.rejected == 2


def test_malformed_utf8_is_rejected(hermetic: tuple[IngestionService, Database]) -> None:
    svc, db = hermetic
    root = Path(svc._roots[0])
    (root / "bad.md").write_bytes(b"# ok\n\n\xff\xfe not utf-8")
    repo, session = _repo(db)
    run, outcomes = svc.ingest(IngestionRequest(source_id="t", paths=["mem/bad.md"]), repo)
    session.commit()
    assert outcomes[0].status == "rejected"
    assert "malformed UTF-8" in " ".join(run.errors)


def test_unchanged_reingest_is_duplicate_changed_creates_new_version(
    hermetic: tuple[IngestionService, Database],
) -> None:
    svc, db = hermetic
    root = Path(svc._roots[0])
    doc = root / "v.md"
    doc.write_text("# V\n\nfirst content\n", encoding="utf-8")
    repo, session = _repo(db)
    svc.ingest(IngestionRequest(source_id="t", paths=["mem/v.md"]), repo)
    session.commit()

    # Re-ingest unchanged -> duplicate, no new version.
    repo2, session2 = _repo(db)
    run_dup, _ = svc.ingest(IngestionRequest(source_id="t", paths=["mem/v.md"]), repo2)
    session2.commit()
    assert run_dup.duplicates == 1 and run_dup.versions == 0

    # Change content -> new version.
    doc.write_text("# V\n\nsecond content changed\n", encoding="utf-8")
    repo3, session3 = _repo(db)
    run_upd, outcomes = svc.ingest(IngestionRequest(source_id="t", paths=["mem/v.md"]), repo3)
    session3.commit()
    assert run_upd.versions == 1 and outcomes[0].status == "updated"


def test_unicode_units_preserved_in_authoritative_text(
    hermetic: tuple[IngestionService, Database],
) -> None:
    svc, db = hermetic
    root = Path(svc._roots[0])
    (root / "u.md").write_text("# Δv\n\nΔv = 3.2 km/s — heliocentric.\n", encoding="utf-8")
    repo, session = _repo(db)
    svc.ingest(IngestionRequest(source_id="t", paths=["mem/u.md"]), repo)
    session.commit()
    repo2, _ = _repo(db)
    docs = repo2.list_documents(10, 0)
    chunks = repo2.get_chunks(docs[0].id)
    joined = "".join(c.original_text for c in chunks)
    assert "Δv = 3.2 km/s" in joined and "—" in joined


def test_real_repo_doc_ingestion_via_container(container: AppContainer) -> None:
    """Allowlisted real repo docs ingest through the wired service (happy path)."""
    run, outcomes = container.memory_service.ingest(
        IngestionRequest(
            source_id="repo-docs",
            paths=["docs/architecture/decisions/ADR-0005-quantum-boundary.md"],
        )
    )
    assert run.documents == 1 and run.chunks >= 1
    assert outcomes[0].status == "created"
    # An out-of-allowlist file is rejected even through the real service.
    run2, _ = container.memory_service.ingest(
        IngestionRequest(source_id="repo-docs", paths=["pyproject.toml", ".env"])
    )
    assert run2.documents == 0 and run2.rejected == 2
