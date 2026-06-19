"""Safe, read-only DOCX text extractor (Python standard library only).

A .docx file is a ZIP container; the body text lives in ``word/document.xml``.
This utility extracts visible paragraph text without installing any office
suite or third-party dependency, and it never modifies the source file.

Usage:
    python scripts/extract_docx.py docs/reference/SomeDocument.docx

It prints extracted text to stdout. Intended for inspecting reference material
that arrives as .docx. It is deliberately conservative: it only reads.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

_PARA_RE = re.compile(r"<w:p[ >].*?</w:p>", re.DOTALL)
_TEXT_RE = re.compile(r"<w:t[^>]*>(.*?)</w:t>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def extract_text(docx_path: Path) -> str:
    """Return the concatenated paragraph text of a .docx file (read-only)."""
    if not docx_path.is_file():
        raise FileNotFoundError(f"Not a file: {docx_path}")
    with zipfile.ZipFile(docx_path) as zf:
        if "word/document.xml" not in zf.namelist():
            raise ValueError("Not a Word document (missing word/document.xml)")
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")

    lines: list[str] = []
    for para in _PARA_RE.findall(xml):
        runs = _TEXT_RE.findall(para)
        text = "".join(_TAG_RE.sub("", r) for r in runs)
        lines.append(text.strip())
    return "\n".join(lines).strip()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/extract_docx.py <path-to.docx>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        print(extract_text(path))
    except (FileNotFoundError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
