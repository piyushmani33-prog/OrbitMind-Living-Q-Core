"""Unit tests for deterministic normalization, chunking, and ranking."""

from __future__ import annotations

from orbitmind.memory.chunking import chunk_document
from orbitmind.memory.normalization import (
    content_checksum,
    normalize_line_endings,
    search_normalize,
    tokenize,
)
from orbitmind.memory.ranking import is_identifier, score

_DOC = (
    "# Title One\n\n"
    "First paragraph mentions SGP4 and asteroid 25544.\n\n"
    "## Section Two\n\n"
    "Second paragraph discusses heliocentric orbits and 1P/Halley.\n"
)


def test_normalize_line_endings_only_touches_eol() -> None:
    assert normalize_line_endings("a\r\nb\rc") == "a\nb\nc"
    # Authoritative text keeps case, punctuation, unicode, units.
    text = "Δv = 3.2 km/s — NOT lowercased!"
    assert normalize_line_endings(text) == text


def test_search_normalize_lowercases_and_collapses_but_keeps_unicode() -> None:
    assert search_normalize("  Hello   WORLD  ") == "hello world"
    assert "δv" in search_normalize("Δv budget")


def test_content_checksum_is_stable_and_sensitive() -> None:
    assert content_checksum("abc") == content_checksum("abc")
    assert content_checksum("abc") != content_checksum("abd")


def test_tokenize_preserves_identifiers() -> None:
    toks = tokenize("SGP4 object 25544 and 1P/Halley v_rel")
    assert "25544" in toks
    assert "1p/halley" in toks
    assert "v_rel" in toks


def test_is_identifier() -> None:
    assert is_identifier("25544")
    assert is_identifier("1p/halley")
    assert not is_identifier("asteroid")


def test_chunking_is_deterministic_and_char_accurate() -> None:
    text = normalize_line_endings(_DOC)
    secs1, chunks1 = chunk_document(
        text, document_id="d", version_id="v", max_chars=200, overlap=20
    )
    _secs2, chunks2 = chunk_document(
        text, document_id="d", version_id="v", max_chars=200, overlap=20
    )
    assert [c.checksum for c in chunks1] == [c.checksum for c in chunks2]
    assert [c.id for c in chunks1] == [c.id for c in chunks2]
    # Char ranges reconstruct the exact original slice.
    assert all(text[c.char_start : c.char_end] == c.original_text for c in chunks1)
    # Sections captured from headings.
    assert any("Title One" in s.section_path for s in secs1)
    assert any("Section Two" in s.section_path for s in secs1)


def test_chunk_section_paths_track_headings() -> None:
    text = normalize_line_endings(_DOC)
    _secs, chunks = chunk_document(text, document_id="d", version_id="v", max_chars=200, overlap=20)
    body = [c for c in chunks if "heliocentric" in c.search_text]
    assert body and "Section Two" in body[0].section_path


def test_long_segment_is_windowed_with_overlap() -> None:
    long = "# H\n\n" + ("word " * 400)
    text = normalize_line_endings(long)
    _secs, chunks = chunk_document(text, document_id="d", version_id="v", max_chars=120, overlap=30)
    body = [c for c in chunks if c.original_text.strip().startswith("word")]
    assert len(body) >= 2  # the long paragraph was split into multiple windows
    assert all((c.char_end - c.char_start) <= 120 for c in body)


def test_ranking_rewards_more_matches_and_identifier_boost() -> None:
    query = {"sgp4", "asteroid", "25544"}
    rich, matched_rich = score(query, tokenize("sgp4 asteroid 25544 sgp4"), set(), set())
    poor, matched_poor = score(query, tokenize("asteroid only here"), set(), set())
    assert rich.total > poor.total
    assert rich.identifier_boost > 0.0  # 25544 is an identifier
    assert "25544" in matched_rich and "25544" not in matched_poor


def test_ranking_title_and_section_boosts() -> None:
    query = {"orbit"}
    base, _ = score(query, tokenize("the orbit is stable"), set(), set())
    titled, _ = score(query, tokenize("the orbit is stable"), {"orbit"}, set())
    sectioned, _ = score(query, tokenize("the orbit is stable"), set(), {"orbit"})
    assert titled.total > base.total
    assert sectioned.total > base.total
