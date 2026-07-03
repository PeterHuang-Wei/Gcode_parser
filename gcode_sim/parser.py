"""token -> AST.

Classification (docs/PLAN.md section 3.2), refined from Phase 1: a
statement is classified by what it *starts* with, not by whether it
merely *contains* a macro character anywhere -- because NC statements
can legitimately contain '#'/'['/']' too, in variable-valued addresses
like ``G00 X#1 Z[#2+3];`` (manual 16.1 "變量的引用"). Only a statement
that starts with a control keyword is control-flow, and only one that
starts with '#' is an assignment; everything else is an NC statement,
whose individual address values may themselves be expressions.
"""

import re

from .ast_nodes import (
    Assignment,
    EndDo,
    Goto,
    IfGoto,
    IfThen,
    NCStatement,
    Stmt,
    UnaryMinus,
    VarRef,
    WhileDo,
)
from .errors import ParseError
from .expression import TokenStream, parse_condition_tokens, parse_expression_tokens, parse_var_index
from .lexer import RawStatement, Word, split_into_statements, tokenize_macro_stmt

_CONTROL_KEYWORDS_RE = re.compile(r"^(GOTO|IF|WHILE|DO|END)", re.IGNORECASE)


def parse(source: str) -> list[Stmt | NCStatement]:
    statements: list[Stmt | NCStatement] = []
    for raw in split_into_statements(source):
        if _CONTROL_KEYWORDS_RE.match(raw.text):
            statements.append(_parse_control_statement(raw))
        elif raw.text.startswith("#"):
            statements.append(_parse_assignment_statement(raw))
        else:
            statements.append(_parse_nc_statement(raw))
    return statements


def _ts_for(raw: RawStatement) -> TokenStream:
    return TokenStream(tokenize_macro_stmt(raw.text, raw.line_no), raw.line_no)


def _expect_end(ts: TokenStream, raw: RawStatement) -> None:
    if not ts.at_end():
        tok = ts.peek()
        raise ParseError(f"line {raw.line_no}: unexpected trailing tokens starting at {tok.text!r}")


def _parse_loop_id(ts: TokenStream, raw: RawStatement) -> int:
    loop_id = int(ts.expect("NUMBER").text)
    if loop_id not in (1, 2, 3):
        raise ParseError(f"line {raw.line_no}: DO/END identifier must be 1, 2, or 3 (cf. PS0126), got {loop_id}")
    return loop_id


def _parse_assignment_target(ts: TokenStream) -> VarRef:
    ts.expect("HASH")
    return VarRef(parse_var_index(ts))


def _parse_assignment_statement(raw: RawStatement) -> Assignment:
    ts = _ts_for(raw)
    target = _parse_assignment_target(ts)
    ts.expect("EQUALS")
    expr = parse_expression_tokens(ts)
    _expect_end(ts, raw)
    return Assignment(target=target, expr=expr, seq_no=raw.seq_no, line_no=raw.line_no)


def _parse_control_statement(raw: RawStatement) -> Stmt:
    ts = _ts_for(raw)

    if ts.peek_is_name("GOTO"):
        ts.next()
        target = parse_expression_tokens(ts)
        _expect_end(ts, raw)
        return Goto(target=target, seq_no=raw.seq_no, line_no=raw.line_no)

    if ts.peek_is_name("IF"):
        ts.next()
        ts.enter_bracket()
        cond = parse_condition_tokens(ts)
        ts.exit_bracket()
        if ts.peek_is_name("GOTO"):
            ts.next()
            target = parse_expression_tokens(ts)
            _expect_end(ts, raw)
            return IfGoto(cond=cond, target=target, seq_no=raw.seq_no, line_no=raw.line_no)
        if ts.peek_is_name("THEN"):
            ts.next()
            then_stmt = _parse_then_body(ts, raw)
            _expect_end(ts, raw)
            return IfThen(cond=cond, then_stmt=then_stmt, seq_no=raw.seq_no, line_no=raw.line_no)
        raise ParseError(f"line {raw.line_no}: expected GOTO or THEN after IF[...]")

    if ts.peek_is_name("WHILE"):
        ts.next()
        ts.enter_bracket()
        cond = parse_condition_tokens(ts)
        ts.exit_bracket()
        if not ts.peek_is_name("DO"):
            raise ParseError(f"line {raw.line_no}: expected DO after WHILE[...]")
        ts.next()
        loop_id = _parse_loop_id(ts, raw)
        _expect_end(ts, raw)
        return WhileDo(cond=cond, loop_id=loop_id, seq_no=raw.seq_no, line_no=raw.line_no)

    if ts.peek_is_name("DO"):
        ts.next()
        loop_id = _parse_loop_id(ts, raw)
        _expect_end(ts, raw)
        return WhileDo(cond=None, loop_id=loop_id, seq_no=raw.seq_no, line_no=raw.line_no)

    if ts.peek_is_name("END"):
        ts.next()
        loop_id = _parse_loop_id(ts, raw)
        _expect_end(ts, raw)
        return EndDo(loop_id=loop_id, seq_no=raw.seq_no, line_no=raw.line_no)

    raise ParseError(f"line {raw.line_no}: cannot parse control statement: {raw.text!r}")


def _parse_then_body(ts: TokenStream, raw: RawStatement) -> Stmt:
    """THEN executes exactly one macro statement. In practice this is
    almost always an assignment; a bare GOTO is also supported."""
    tok = ts.peek()
    if tok is not None and tok.kind == "HASH":
        target = _parse_assignment_target(ts)
        ts.expect("EQUALS")
        expr = parse_expression_tokens(ts)
        return Assignment(target=target, expr=expr, seq_no=None, line_no=raw.line_no)
    if ts.peek_is_name("GOTO"):
        ts.next()
        target = parse_expression_tokens(ts)
        return Goto(target=target, seq_no=None, line_no=raw.line_no)
    raise ParseError(f"line {raw.line_no}: unsupported THEN body (only assignment/GOTO supported)")


# ------------------------------------------------------------- NC statements

def _parse_nc_statement(raw: RawStatement) -> NCStatement:
    ts = _ts_for(raw)
    words: list[Word] = []
    while not ts.at_end():
        tok = ts.next()
        if tok.kind != "NAME" or len(tok.text) != 1:
            raise ParseError(
                f"line {raw.line_no}: expected a single-letter address, got {tok.kind} {tok.text!r} "
                f"in {raw.text!r}"
            )
        words.append(_parse_nc_word_value(ts, tok.text.upper(), raw))
    return NCStatement(seq_no=raw.seq_no, words=words, skip=raw.skip, line_no=raw.line_no)


def _parse_nc_word_value(ts: TokenStream, address: str, raw: RawStatement) -> Word:
    negative = False
    tok = ts.peek()
    if tok is not None and tok.kind == "MINUS":
        negative = True
        ts.next()
        tok = ts.peek()
    elif tok is not None and tok.kind == "PLUS":
        ts.next()
        tok = ts.peek()

    if tok is not None and tok.kind == "NUMBER":
        ts.next()
        text = ("-" if negative else "") + tok.text
        return Word(address=address, value=text)

    if tok is not None and tok.kind == "HASH":
        ts.next()
        expr = VarRef(parse_var_index(ts))
        if negative:
            expr = UnaryMinus(expr)
        return Word(address=address, expr=expr)

    if tok is not None and tok.kind == "LBRACKET":
        ts.enter_bracket()
        expr = parse_expression_tokens(ts)
        ts.exit_bracket()
        if negative:
            expr = UnaryMinus(expr)
        return Word(address=address, expr=expr)

    raise ParseError(f"line {raw.line_no}: expected a value after address {address!r} in {raw.text!r}")
