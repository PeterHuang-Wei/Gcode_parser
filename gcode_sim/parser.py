"""token -> AST.

Blocks are classified per docs/PLAN.md section 3.2: a statement is a
macro statement if it contains ``#``/``=``/``[``/``]`` or a control
keyword (GOTO/IF/WHILE/DO/END); otherwise it's a plain NC statement.
G65 macro calls arrive in Phase 2.
"""

from .ast_nodes import (
    Assignment,
    EndDo,
    Goto,
    IfGoto,
    IfThen,
    NCStatement,
    Stmt,
    VarRef,
    WhileDo,
)
from .errors import ParseError
from .expression import TokenStream, parse_condition_tokens, parse_expression_tokens, parse_var_index
from .lexer import RawStatement, looks_like_macro_statement, split_into_statements, tokenize_macro_stmt, tokenize_nc_words


def parse(source: str) -> list[Stmt | NCStatement]:
    statements: list[Stmt | NCStatement] = []
    for raw in split_into_statements(source):
        if looks_like_macro_statement(raw.text):
            statements.append(_parse_macro_statement(raw))
        else:
            words = tokenize_nc_words(raw.text, raw.line_no)
            statements.append(NCStatement(seq_no=raw.seq_no, words=words, skip=raw.skip, line_no=raw.line_no))
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


def _parse_macro_statement(raw: RawStatement) -> Stmt:
    ts = _ts_for(raw)
    tok = ts.peek()
    if tok is None:
        raise ParseError(f"line {raw.line_no}: empty macro statement")

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

    if tok.kind == "HASH":
        target = _parse_assignment_target(ts)
        ts.expect("EQUALS")
        expr = parse_expression_tokens(ts)
        _expect_end(ts, raw)
        return Assignment(target=target, expr=expr, seq_no=raw.seq_no, line_no=raw.line_no)

    raise ParseError(f"line {raw.line_no}: cannot parse macro statement: {raw.text!r}")


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
