"""Tokenizer: NC source text -> a list of RawBlock (one per program block).

Phase 0 only supports plain NC statements. Macro syntax (``#``, ``=``,
``[``, ``]``, ``GOTO``/``IF``/``THEN``/``WHILE``/``DO``/``END`` and the
comparison/logical operator keywords) is out of scope until Phase 1/2 --
encountering it here fails loudly with UnsupportedFeatureError rather
than being silently misparsed as ordinary addresses.
"""

import re
from dataclasses import dataclass

from .errors import LexError, UnsupportedFeatureError

COMMENT_RE = re.compile(r"\([^)]*\)")
WORD_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+\.?\d*|\.\d+))")
MACRO_CHARS = set("#=[]")
MACRO_KEYWORDS = {
    "GOTO", "IF", "THEN", "WHILE", "DO", "END",
    "EQ", "NE", "GT", "GE", "LT", "LE", "AND", "OR", "XOR", "MOD",
}


@dataclass
class Word:
    address: str
    value: str

    def as_float(self) -> float:
        return float(self.value)


@dataclass
class RawBlock:
    seq_no: int | None
    skip: bool
    words: list[Word]
    raw_text: str
    line_no: int


def _check_no_macro_syntax(stmt: str, line_no: int) -> None:
    if any(ch in stmt for ch in MACRO_CHARS):
        raise UnsupportedFeatureError(
            f"line {line_no}: macro syntax not supported yet (Phase 1+): {stmt!r}"
        )
    upper = stmt.upper()
    for kw in MACRO_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            raise UnsupportedFeatureError(
                f"line {line_no}: macro keyword {kw!r} not supported yet (Phase 1+): {stmt!r}"
            )


def _tokenize_statement(stmt: str, line_no: int) -> list[Word]:
    words: list[Word] = []
    pos = 0
    for m in WORD_RE.finditer(stmt):
        gap = stmt[pos:m.start()].strip()
        if gap:
            raise LexError(f"line {line_no}: unrecognized token {gap!r} in {stmt!r}")
        words.append(Word(address=m.group(1).upper(), value=m.group(2)))
        pos = m.end()
    trailing = stmt[pos:].strip()
    if trailing:
        raise LexError(f"line {line_no}: unrecognized trailing token {trailing!r} in {stmt!r}")
    return words


def tokenize(source: str) -> list[RawBlock]:
    blocks: list[RawBlock] = []
    for line_no, raw_line in enumerate(source.splitlines(), start=1):
        line = COMMENT_RE.sub("", raw_line).strip()
        if not line:
            continue
        for stmt in line.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            skip = stmt.startswith("/")
            if skip:
                stmt = stmt[1:].strip()
            _check_no_macro_syntax(stmt, line_no)
            words = _tokenize_statement(stmt, line_no)
            seq_no = None
            if words and words[0].address == "N":
                seq_no = int(float(words[0].value))
                words = words[1:]
            blocks.append(
                RawBlock(seq_no=seq_no, skip=skip, words=words, raw_text=raw_line.strip(), line_no=line_no)
            )
    return blocks
