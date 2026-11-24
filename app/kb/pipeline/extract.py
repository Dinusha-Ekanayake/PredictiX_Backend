"""Turn an original file into clean text blocks that keep their provenance.

Each Block carries the section heading and page it came from, so every chunk
built from it can be cited precisely ("S07, 1910.178(g), p. -" or
"S08, Regulation 4, p. 17").

PDF cleaning removes what would pollute retrieval: running headers and
footers repeated on most pages, web-print stamps (URL + timestamp), page
numbers and hyphenation at line ends.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from pypdf import PdfReader

from app.kb.pipeline.registry import parse_pages


@dataclass(frozen=True)
class Block:
    text: str
    section: Optional[str]
    page: Optional[int]
    # Set only for passages about one warehouse (derived operational data);
    # None means the passage follows its source's scope.
    warehouse_id: Optional[str] = None


class ExtractionError(RuntimeError):
    """The file could not be read as the declared format."""


# ── PDF ──────────────────────────────────────────────────────────────────────

_WEB_PRINT_STAMP = re.compile(r"https?://\S+\[[^\]]{0,40}\]")
_PAGE_NUMBER_LINE = re.compile(r"^(page\s+)?\d{1,4}(\s+of\s+\d{1,4})?$", re.I)
_NUMBERED_HEADING = re.compile(r"^(\d{1,2}(\.\d{1,2}){0,5}\.?)\s+([A-Z\"'][^\n]{2,100})$")
_MULTILEVEL_HEADING = re.compile(r"^\d{1,2}(\.\d{1,2}){1,5}\.?\s+[A-Z\"'][^\n]{2,100}$")
_LEGAL_SECTION = re.compile(r"^(\d{1,3})\.\s+\(1\)\s")
_DATE_LINE = re.compile(
    r"^\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}$")
_CUT_OFF_WORDS = {"a", "an", "and", "any", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with", "which"}
_SPACES = re.compile(r"[ \t ]+")


def _normalise_line(line: str) -> str:
    line = _WEB_PRINT_STAMP.sub(" ", line)
    line = line.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("­", "")
    return _SPACES.sub(" ", line).strip()


def _signature(line: str) -> str:
    """A line with digits masked and spacing removed, so 'Page 3 of 44' matches
    'Page 4 of 44' and 'NAVAIR 17-15 -50.1' matches 'NAVAIR 17-15-50.1'."""
    return re.sub(r"\d+", "#", re.sub(r"\s+", "", line.lower()))


def _repeated_lines(pages: list[list[str]]) -> set[str]:
    """Signatures of lines that appear on at least 40% of pages (headers, footers)."""
    if len(pages) < 3:
        return set()
    counts = Counter(sig for lines in pages for sig in {_signature(l) for l in lines if l})
    threshold = max(2, int(0.4 * len(pages)))
    return {sig for sig, n in counts.items() if n >= threshold and len(sig) < 160}


def _looks_cut_off(line: str) -> bool:
    """A line that stops mid-sentence ('...in which any') or mid-word ('... . W')."""
    last = line.rstrip(" .").split()[-1] if line.strip(" .") else ""
    return last.lower() in _CUT_OFF_WORDS or len(last) == 1


def _is_heading(line: str, mode: str = "auto") -> bool:
    """A short numbered title ('8.1.6.2. Weibull') or, in auto mode, a short
    capitalised title ('OIL ANALYSIS THEORY AND BENEFITS')."""
    if mode == "none" or len(line) > 110 or _DATE_LINE.match(line) or _looks_cut_off(line):
        return False
    if mode == "multilevel":
        return bool(_MULTILEVEL_HEADING.match(line)) and len(line.split()) <= 16
    if _NUMBERED_HEADING.match(line):
        if line.endswith((",", ";")) or len(line.split()) > 12:
            return False
        number, _, title = line.partition(" ")
        if "." in number.rstrip("."):
            return True                     # 8.1.6.2. style: always a heading
        # "3. Title Case Heading" rather than "3. Whenever directed by the unit ..."
        words = [w for w in title.split() if w.isalpha() and w.lower() not in _CUT_OFF_WORDS | {"versus", "per"}]
        capitalised = sum(w[0].isupper() for w in words)
        return ". " not in title and len(title.split()) <= 8 and bool(words) and capitalised / len(words) >= 0.6
    if line.endswith((".", ",", ";", ":")):
        return False
    words = line.split()
    letters = [c for c in line if c.isalpha()]
    mostly_capitals = len(letters) >= 6 and sum(c.isupper() for c in letters) / len(letters) > 0.85
    return mostly_capitals and 2 <= len(words) <= 12


def _join_lines(lines: list[str]) -> str:
    text = ""
    for line in lines:
        if text.endswith("-") and line[:1].islower():
            text = text[:-1] + line          # re-join a hyphenated word
        elif text:
            text += " " + line
        else:
            text = line
    return text


def extract_pdf(content: bytes, pages: Optional[str] = None, headings: str = "auto") -> list[Block]:
    """Blocks from a PDF, optionally limited to a 1-based page selection.

    `headings` chooses how section titles are recognised (see FetchSpec).
    A provision of legislation opening '27. (1) ...' starts 'Section 27'.
    """
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise ExtractionError(f"not a readable PDF: {exc}") from exc
    total = len(reader.pages)
    selected = parse_pages(pages) if pages else list(range(1, total + 1))
    if selected and selected[-1] > total:
        raise ExtractionError(f"page selection goes to {selected[-1]} but the PDF has {total} pages")

    page_lines: list[list[str]] = []
    for number in selected:
        raw = reader.pages[number - 1].extract_text() or ""
        page_lines.append([_normalise_line(l) for l in raw.splitlines()])

    boilerplate = _repeated_lines(page_lines)
    blocks: list[Block] = []
    section: Optional[str] = None
    for number, lines in zip(selected, page_lines):
        buffer: list[str] = []
        for line in lines:
            if not line or _PAGE_NUMBER_LINE.match(line) or _signature(line) in boilerplate:
                continue
            legal = _LEGAL_SECTION.match(line) if headings == "auto" else None
            if legal:
                if buffer:
                    blocks.append(Block(_join_lines(buffer), section, number))
                    buffer = []
                section = f"Section {legal.group(1)}"
                buffer.append(line)
                continue
            if _is_heading(line, headings):
                if buffer:
                    blocks.append(Block(_join_lines(buffer), section, number))
                    buffer = []
                section = line.rstrip(":")
                continue
            buffer.append(line)
        if buffer:
            blocks.append(Block(_join_lines(buffer), section, number))
    return [b for b in blocks if b.text.strip()]


# ── eCFR XML ─────────────────────────────────────────────────────────────────

_SKIP_TAGS = {"CITA", "AUTH", "SOURCE", "EDNOTE", "FTNT", "SECAUTH"}
_PARAGRAPH_HEADING = re.compile(r"^\(([a-z])\)\s+(.{3,90}?)\.(\s|$)")


def _text(el: ET.Element) -> str:
    return _SPACES.sub(" ", "".join(el.itertext())).strip()


def _table_rows(table: ET.Element) -> list[str]:
    rows = []
    for tr in table.iter("TR"):
        cells = [_text(cell) for cell in tr if cell.tag in ("TD", "TH")]
        if any(cells):
            rows.append(" | ".join(cells))
    return rows


def _section_blocks(div: ET.Element) -> list[Block]:
    head = div.find("HEAD")
    base = _text(head) if head is not None else div.get("N") or ""
    citation = div.get("N")
    blocks: list[Block] = []
    section = base
    for child in div:
        if child.tag in _SKIP_TAGS or child.tag == "HEAD":
            continue
        if child.tag in ("TABLE", "GPOTABLE") or child.find(".//TABLE") is not None:
            rows = _table_rows(child)
            if rows:
                blocks.append(Block("\n".join(rows), section, None))
            continue
        text = _text(child)
        if not text:
            continue
        # A top-level lettered paragraph with an italic title starts a
        # sub-section, e.g. "(g) Changing and charging storage batteries."
        match = _PARAGRAPH_HEADING.match(text)
        if match and child.find("I") is not None and citation and citation[0].isdigit():
            section = f"{base.split(' ', 2)[0]} {citation}({match.group(1)}) {match.group(2)}"
        blocks.append(Block(text, section, None))
    return blocks


def extract_ecfr_xml(content: bytes) -> list[Block]:
    """Blocks from an eCFR versioner XML document, one section per heading."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ExtractionError(f"not valid XML: {exc}") from exc
    divisions = [
        el for el in root.iter()
        if el.tag.startswith("DIV") and el.get("TYPE") in ("SECTION", "APPENDIX")
    ]
    if not divisions:
        raise ExtractionError("no sections or appendices found in the eCFR document")
    blocks: list[Block] = []
    for div in divisions:
        blocks.extend(_section_blocks(div))
    return blocks


_MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
_MD_MARKUP = re.compile(r"(\*\*|__|`|^\s*[-*+]\s+|^\s*\d+\.\s+)")


def extract_markdown(content: bytes) -> list[Block]:
    """Blocks from a Markdown document: each '#' heading starts a section,
    and each paragraph or list becomes a block. Emphasis marks are removed."""
    blocks: list[Block] = []
    section: Optional[str] = None
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            blocks.append(Block(" ".join(buffer), section, None))
            buffer.clear()

    for raw in content.decode("utf-8").splitlines():
        heading = _MD_HEADING.match(raw.strip())
        if heading:
            flush()
            section = heading.group(1).strip()
            continue
        line = _SPACES.sub(" ", _MD_MARKUP.sub("", raw)).strip()
        if not line:
            flush()
            continue
        # A list item is its own sentence, so the chunker can split between items.
        if _MD_MARKUP.match(raw) and buffer and not buffer[-1].endswith((".", "!", "?", ":")):
            buffer[-1] += "."
        buffer.append(line)
    flush()
    return blocks


def extract(fmt: str, content: bytes, pages: Optional[str] = None, headings: str = "auto") -> list[Block]:
    if fmt == "pdf":
        return extract_pdf(content, pages, headings)
    if fmt == "markdown":
        return extract_markdown(content)
    if fmt == "ecfr_xml":
        if pages:
            raise ExtractionError("page selection does not apply to eCFR XML")
        return extract_ecfr_xml(content)
    from app.kb.pipeline.internal import INTERNAL_FORMATS

    if fmt in INTERNAL_FORMATS:
        return INTERNAL_FORMATS[fmt][1](content)
    raise ExtractionError(f"unsupported format {fmt!r}")
