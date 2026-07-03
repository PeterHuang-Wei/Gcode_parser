"""Tokenizers: NC source text -> statements -> tokens.

Two token styles coexist because NC statements and macro statements have
different shapes:

- NC statements (``G01 X10.0 Z-5.0;``) are address-value pairs -- see
  ``tokenize_nc_words``.
- Macro statements (``#1=#2+100;``, ``IF[#1 GT 10]GOTO2;``) are proper
  expressions -- see ``tokenize_macro_stmt``.

``split_into_statements`` does the shared work (comment stripping,
block-skip, sequence-number extraction, splitting a physical line into
one or more ``;``-terminated statements) and hands each statement's raw
text to whichever tokenizer the parser decides is appropriate.

``tokenize()`` is kept as a Phase-0-compatible wrapper: it still raises
UnsupportedFeatureError if the source contains anything that isn't a
plain NC statement.
"""

import re
from dataclasses import dataclass

from .errors import LexError, UnsupportedFeatureError

COMMENT_RE = re.compile(r"\([^)]*\)")
NC_WORD_RE = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+\.?\d*|\.\d+))")
SEQ_NO_RE = re.compile(r"^[Nn](\d+)\s*(.*)$", re.DOTALL)

MACRO_CHARS = set("#=[]")
MACRO_KEYWORDS = ("GOTO", "IF", "WHILE", "DO", "END")

MACRO_TOKEN_RE = re.compile(
    r"\s*(?:"
    r"(?P<NUMBER>\d+\.\d*|\.\d+|\d+)"
    r"|(?P<HASH>#)"
    r"|(?P<LBRACKET>\[)"
    r"|(?P<RBRACKET>\])"
    r"|(?P<EQUALS>=)"
    r"|(?P<PLUS>\+)"
    r"|(?P<MINUS>-)"
    r"|(?P<STAR>\*)"
    r"|(?P<SLASH>/)"
    r"|(?P<COMMA>,)"
    r"|(?P<NAME>[A-Za-z_]+)"
    r")"
)


@dataclass
class Word:
    address: str
    value: str | None = None  # literal text, e.g. "10.0" -- set when expr is None
    expr: object | None = None  # an ast_nodes.Expr, for #-/bracket-valued addresses
    # (typed as `object` to avoid a lexer<->ast_nodes<->expression import
    # cycle -- ast_nodes.py already imports Word from here)

    def as_float(self) -> float:
        if self.expr is not None:
            raise TypeError(
                "as_float() cannot resolve an expression-valued Word without a "
                "VariableStore -- use Interpreter._resolve_word() instead"
            )
        return float(self.value)


@dataclass
class RawBlock:
    seq_no: int | None
    skip: bool
    words: list[Word]
    raw_text: str
    line_no: int


@dataclass
class RawStatement:
    seq_no: int | None
    skip: bool
    text: str
    line_no: int


@dataclass
class Token:
    kind: str
    text: str


def split_into_statements(source: str) -> list[RawStatement]:
    statements: list[RawStatement] = []
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
            seq_no = None
            m = SEQ_NO_RE.match(stmt)
            if m:
                seq_no = int(m.group(1))
                stmt = m.group(2).strip()
            if not stmt:
                continue
            statements.append(RawStatement(seq_no=seq_no, skip=skip, text=stmt, line_no=line_no))
    return statements


def looks_like_macro_statement(text: str) -> bool:
    if any(ch in text for ch in MACRO_CHARS):
        return True
    upper = text.upper()
    # A trailing \b is not enough: "GOTO1"/"END1" (no space before the
    # digit) have no word-boundary between the keyword and the digit,
    # since both are \w characters. Only the *leading* boundary matters
    # here (the keyword must not be a suffix of some other identifier).
    return any(re.search(rf"(?<![A-Za-z0-9_]){kw}", upper) for kw in MACRO_KEYWORDS)


def tokenize_nc_words(stmt: str, line_no: int) -> list[Word]:
    words: list[Word] = []
    pos = 0
    for m in NC_WORD_RE.finditer(stmt):
        gap = stmt[pos:m.start()].strip()
        if gap:
            raise LexError(f"line {line_no}: unrecognized token {gap!r} in {stmt!r}")
        words.append(Word(address=m.group(1).upper(), value=m.group(2)))
        pos = m.end()
    trailing = stmt[pos:].strip()
    if trailing:
        raise LexError(f"line {line_no}: unrecognized trailing token {trailing!r} in {stmt!r}")
    return words


def tokenize_macro_stmt(stmt: str, line_no: int) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    n = len(stmt)
    while pos < n:
        m = MACRO_TOKEN_RE.match(stmt, pos)
        if not m:
            remainder = stmt[pos:].strip()
            if not remainder:
                break
            raise LexError(f"line {line_no}: unrecognized token near {stmt[pos:pos + 10]!r}")
        kind = m.lastgroup
        assert kind is not None
        tokens.append(Token(kind=kind, text=m.group(kind)))
        pos = m.end()
    return tokens


def tokenize(source: str) -> list[RawBlock]:
    """Phase-0-compatible entry point: every statement must be a plain NC
    statement. Kept so Phase 0 code/tests keep working unchanged; Phase 1+
    code should use split_into_statements()/tokenize_macro_stmt() directly
    via parser.parse()."""
    blocks: list[RawBlock] = []
    for raw in split_into_statements(source):
        if looks_like_macro_statement(raw.text):
            raise UnsupportedFeatureError(
                f"line {raw.line_no}: macro syntax not supported by tokenize() "
                f"(use gcode_sim.parser.parse instead): {raw.text!r}"
            )
        words = tokenize_nc_words(raw.text, raw.line_no)
        blocks.append(
            RawBlock(seq_no=raw.seq_no, skip=raw.skip, words=words, raw_text=raw.text, line_no=raw.line_no)
        )
    return blocks
