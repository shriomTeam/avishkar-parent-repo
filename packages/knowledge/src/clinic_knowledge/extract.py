"""Turn an uploaded file into clean text with its section headings.

Nothing here logs file content: documents may contain patient information.
"""

import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass


class ExtractError(Exception):
    """The file cannot be read. The message is safe to show to staff."""


@dataclass(frozen=True)
class Block:
    heading: str | None
    text: str


def normalize(text: str) -> str:
    """The form used to compare texts: case and spacing do not matter."""
    return re.sub(r"\s+", " ", text).strip().lower()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _from_text(raw: bytes, markdown: bool) -> list[Block]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    blocks: list[Block] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        body = _clean("\n".join(buffer))
        if body:
            blocks.append(Block(heading, body))
        buffer.clear()

    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.*\S)\s*$", line) if markdown else None
        if match:
            flush()
            heading = match.group(1)[:300]
        else:
            buffer.append(line)
    flush()
    return blocks


def _from_docx(raw: bytes) -> list[Block]:
    from docx import Document

    try:
        document = Document(io.BytesIO(raw))
    except Exception:
        raise ExtractError("This Word file could not be opened.") from None
    blocks: list[Block] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        body = _clean("\n\n".join(buffer))
        if body:
            blocks.append(Block(heading, body))
        buffer.clear()

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        if (paragraph.style.name or "").lower().startswith("heading") or (paragraph.style.name or "") == "Title":
            flush()
            heading = text[:300]
        else:
            buffer.append(text)
    flush()
    for table in document.tables:  # prices and hours are often in tables
        rows = [" | ".join(cell.text.strip() for cell in row.cells if cell.text.strip()) for row in table.rows]
        body = _clean("\n".join(r for r in rows if r))
        if body:
            blocks.append(Block(heading, body))
    return blocks


_PAGE_NUMBER = re.compile(r"^(page\s*)?\d{1,4}(\s*(/|of)\s*\d{1,4})?$", re.IGNORECASE)


def _from_pdf(raw: bytes) -> list[Block]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ExtractError("This PDF is password protected.")
        pages = [(page.extract_text() or "") for page in reader.pages]
    except ExtractError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError):
        raise ExtractError("This PDF could not be read.") from None
    # Lines repeated on most pages (running headers and footers) and bare page numbers are not content.
    lines_per_page = [[line.strip() for line in page.splitlines() if line.strip()] for page in pages]
    counts = Counter(line for lines in lines_per_page for line in set(lines))
    repeated = {
        line for line, n in counts.items() if len(pages) >= 3 and n >= max(3, len(pages) // 2) and len(line) < 90
    }
    blocks: list[Block] = []
    for lines in lines_per_page:
        kept = [line for line in lines if line not in repeated and not _PAGE_NUMBER.match(line)]
        body = _clean("\n".join(kept))
        if body:
            blocks.append(Block(None, body))
    return blocks


def extract(raw: bytes, filename: str) -> list[Block]:
    """The text blocks of a file, or ExtractError with a reason staff can act on."""
    name = filename.lower()
    if name.endswith(".pdf"):
        blocks = _from_pdf(raw)
    elif name.endswith(".docx"):
        blocks = _from_docx(raw)
    elif name.endswith(".md"):
        blocks = _from_text(raw, markdown=True)
    elif name.endswith(".txt"):
        blocks = _from_text(raw, markdown=False)
    else:
        raise ExtractError("This type of file is not supported.")
    if not blocks:
        raise ExtractError("No readable text was found. A scanned document needs to be turned into text first.")
    return blocks
