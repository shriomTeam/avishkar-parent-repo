"""Split text into passages of about CHUNK_TOKENS, keeping the section heading with each."""

import re
from dataclasses import dataclass

from clinic_knowledge.constants import CHUNK_TOKENS, OVERLAP_TOKENS
from clinic_knowledge.extract import Block

CHARS_PER_TOKEN = 4  # a rough, language-neutral estimate; exact counts do not matter here


@dataclass(frozen=True)
class Passage:
    heading: str | None
    text: str

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _sentences(paragraph: str, limit: int) -> list[str]:
    """Sentences, with any sentence still longer than the limit cut at word boundaries."""
    pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        sentence = sentence.strip()
        if not sentence:
            continue
        while estimate_tokens(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit * CHARS_PER_TOKEN)
            cut = cut if cut > 0 else limit * CHARS_PER_TOKEN
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            pieces.append(sentence)
    return pieces


def split(blocks: list[Block], *, target: int = CHUNK_TOKENS, overlap: int = OVERLAP_TOKENS) -> list[Passage]:
    """Passages of about ``target`` tokens. Each starts at a paragraph or sentence edge and never crosses a heading."""
    passages: list[Passage] = []
    for block in blocks:
        units: list[str] = []
        for paragraph in re.split(r"\n\s*\n", block.text):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            units.extend([paragraph] if estimate_tokens(paragraph) <= target else _sentences(paragraph, target))
        current: list[str] = []
        size = 0
        for unit in units:
            unit_size = estimate_tokens(unit)
            if current and size + unit_size > target:
                passages.append(Passage(block.heading, "\n\n".join(current)))
                tail: list[str] = []
                carried = 0
                for previous in reversed(current):  # repeat the end of this passage at the start of the next
                    if carried + estimate_tokens(previous) > overlap:
                        break
                    tail.insert(0, previous)
                    carried += estimate_tokens(previous)
                current, size = tail, carried
            current.append(unit)
            size += unit_size
        if current:
            text = "\n\n".join(current)
            # A trailing piece that only repeats the overlap of the passage before it adds nothing.
            if not passages or passages[-1].heading != block.heading or text not in passages[-1].text:
                passages.append(Passage(block.heading, text))
    return passages
