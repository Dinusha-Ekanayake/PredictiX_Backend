"""Split extracted blocks into passages sized for the embedding model.

Rules, in order of importance:

1. Never exceed the model's input limit. all-MiniLM-L6-v2 truncates after
   256 word pieces without warning, so a passage that is too long is
   embedded from its first part only and the rest can never be found.
2. Never mix sections. A passage stays inside one heading, so its citation
   is exact and its topic is coherent.
3. Split on sentence boundaries, carrying a short overlap of whole sentences
   into the next passage so an idea cut at a boundary is still findable.
4. Prefix each passage with "<source> - <section>" before embedding. The
   heading gives the vector context the passage text alone may lack.

Counting uses the model's own tokenizer (passed in), not characters.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from app.kb.pipeline.config import (
    MAX_EMBED_TOKENS,
    MAX_HEADER_TOKENS,
    MIN_CHUNK_TOKENS,
    OVERLAP_TOKENS,
    TARGET_CHUNK_TOKENS,
)
from app.kb.pipeline.extract import Block

TokenCounter = Callable[[str], int]

_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "No.", "no.", "Sec.", "sec.", "Fig.", "U.S.", "approx.", "vol.", "Vol.", "p.", "pp.", "St.")
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9(\"'“‘])")


@dataclass(frozen=True)
class Chunk:
    index: int
    section: Optional[str]
    page_start: Optional[int]
    page_end: Optional[int]
    content: str
    content_hash: str
    token_count: int        # of embed_text, i.e. what the model actually reads
    embed_text: str
    warehouse_id: Optional[str] = None


def split_sentences(text: str) -> list[str]:
    """Sentence split that does not break after common abbreviations."""
    protected = text
    for i, abbr in enumerate(_ABBREVIATIONS):
        protected = protected.replace(abbr, abbr.replace(".", f"\x00{i}\x00"))
    parts = [p.strip() for p in _SENTENCE_END.split(protected) if p.strip()]
    restored = []
    for part in parts:
        for i, abbr in enumerate(_ABBREVIATIONS):
            part = part.replace(abbr.replace(".", f"\x00{i}\x00"), abbr)
        restored.append(part)
    return restored


def _split_long(sentence: str, budget: int, count: TokenCounter) -> list[str]:
    """Break a sentence (or table row run) longer than `budget` at word boundaries."""
    pieces, current = [], []
    for word in sentence.split():
        candidate = " ".join(current + [word])
        if current and count(candidate) > budget:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _header(title: str, section: Optional[str], count: TokenCounter) -> str:
    header = f"{title} - {section}" if section else title
    while count(header) > MAX_HEADER_TOKENS and len(header) > 20:
        header = header[: int(len(header) * 0.85)].rstrip() + "..."
    return header


def _units(blocks: Iterable[Block]) -> list[tuple[tuple[Optional[str], Optional[str]], Optional[int], str]]:
    """((section, warehouse), page, sentence) triples in document order."""
    units = []
    for block in blocks:
        lines = block.text.split("\n") if "\n" in block.text else [block.text]
        for line in lines:
            for sentence in split_sentences(line):
                units.append(((block.section, block.warehouse_id), block.page, sentence))
    return units


def chunk_blocks(blocks: list[Block], title: str, count: TokenCounter) -> list[Chunk]:
    """Passages for one source, deterministic for the same input."""
    chunks: list[Chunk] = []
    units = _units(blocks)
    i = 0
    while i < len(units):
        key = units[i][0]
        section, warehouse_id = key
        header = _header(title, section, count)
        budget = min(TARGET_CHUNK_TOKENS, MAX_EMBED_TOKENS - count(header) - 2)

        # Collect this section's sentences, splitting any that alone exceed the budget.
        section_units: list[tuple[Optional[int], str]] = []
        # A passage never spans two sections or two warehouses.
        while i < len(units) and units[i][0] == key:
            _, page, sentence = units[i]
            if count(sentence) > budget:
                section_units.extend((page, piece) for piece in _split_long(sentence, budget, count))
            else:
                section_units.append((page, sentence))
            i += 1

        start = 0
        section_chunks: list[list[tuple[Optional[int], str]]] = []
        while start < len(section_units):
            end, used = start, 0
            while end < len(section_units):
                need = count(section_units[end][1]) + (1 if end > start else 0)
                if end > start and used + need > budget:
                    break
                used += need
                end += 1
            section_chunks.append(section_units[start:end])
            if end >= len(section_units):
                break
            # Overlap: carry whole trailing sentences worth up to OVERLAP_TOKENS.
            back, carried = end, 0
            while back - 1 > start and carried + count(section_units[back - 1][1]) <= OVERLAP_TOKENS:
                back -= 1
                carried += count(section_units[back][1])
            start = back if back > start else end

        # A tiny last passage is merged into the previous one when it fits.
        if len(section_chunks) > 1:
            tail = " ".join(s for _, s in section_chunks[-1])
            joined = " ".join(s for _, s in section_chunks[-2]) + " " + tail
            if count(tail) < MIN_CHUNK_TOKENS and count(joined) <= budget:
                merged = section_chunks[-2] + [u for u in section_chunks[-1] if u not in section_chunks[-2]]
                section_chunks = section_chunks[:-2] + [merged]

        for group in section_chunks:
            content = " ".join(s for _, s in group).strip()
            pages = [p for p, _ in group if p is not None]
            embed_text = f"{header}\n{content}"
            chunks.append(Chunk(
                index=len(chunks),
                section=section,
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                content=content,
                content_hash=hashlib.sha256(" ".join(content.lower().split()).encode()).hexdigest(),
                token_count=count(embed_text),
                embed_text=embed_text,
                warehouse_id=warehouse_id,
            ))
    return chunks


def drop_duplicates(chunks: list[Chunk]) -> tuple[list[Chunk], int]:
    """Remove passages whose text repeats an earlier one; renumber the rest."""
    seen: set[str] = set()
    kept: list[Chunk] = []
    for chunk in chunks:
        if chunk.content_hash in seen:
            continue
        seen.add(chunk.content_hash)
        kept.append(Chunk(len(kept), chunk.section, chunk.page_start, chunk.page_end,
                          chunk.content, chunk.content_hash, chunk.token_count, chunk.embed_text,
                          chunk.warehouse_id))
    return kept, len(chunks) - len(kept)
