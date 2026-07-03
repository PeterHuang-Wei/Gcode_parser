"""Recursive-descent parser and evaluator for <expression> and
<condition> (docs/PLAN.md section 4; manual chapter 16.3/16.6).

Operator precedence, per the manual: function > (* / AND) > (+ - OR XOR).
Bracket nesting is capped at 5 levels (cf. PS0118).
"""

from __future__ import annotations

import math

from .ast_nodes import (
    BinOp,
    CompoundCondition,
    Condition,
    Expr,
    FuncCall1,
    FuncCall2,
    Literal,
    SimpleCondition,
    UnaryMinus,
    VarRef,
)
from .errors import MacroError, ParseError
from .lexer import Token, tokenize_macro_stmt
from .variables import EMPTY, VariableStore, arithmetic_value

MAX_BRACKET_DEPTH = 5

COMPARISON_OPS = {"EQ", "NE", "GT", "GE", "LT", "LE"}

# Full names plus the manual's documented 2-letter abbreviations/synonyms.
# POW is explicitly *not* abbreviable (docs/PLAN.md / manual note).
FUNCTIONS_1ARG = {
    "SIN": "SIN", "SI": "SIN",
    "COS": "COS", "CO": "COS",
    "TAN": "TAN", "TA": "TAN",
    "ASIN": "ASIN", "AS": "ASIN",
    "ACOS": "ACOS", "AC": "ACOS",
    "SQRT": "SQRT", "SQ": "SQRT", "SQR": "SQRT",
    "ABS": "ABS", "AB": "ABS",
    "BIN": "BIN",
    "BCD": "BCD",
    "ROUND": "ROUND", "RO": "ROUND", "RND": "ROUND",
    "FIX": "FIX", "FI": "FIX",
    "FUP": "FUP", "FU": "FUP",
    "LN": "LN",
    "EXP": "EXP", "EX": "EXP",
    "ADP": "ADP", "AD": "ADP",
}
ATAN_NAMES = {"ATAN", "AT", "ATN"}
POW_NAME = "POW"


class TokenStream:
    def __init__(self, tokens: list[Token], line_no: int):
        self.tokens = tokens
        self.pos = 0
        self.line_no = line_no
        self.bracket_depth = 0

    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> Token:
        if self.pos >= len(self.tokens):
            raise ParseError(f"line {self.line_no}: unexpected end of statement")
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.next()
        if tok.kind != kind:
            raise ParseError(f"line {self.line_no}: expected {kind}, got {tok.kind} {tok.text!r}")
        return tok

    def peek_is_name(self, *names: str) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == "NAME" and tok.text.upper() in names

    def enter_bracket(self) -> None:
        self.expect("LBRACKET")
        self.bracket_depth += 1
        if self.bracket_depth > MAX_BRACKET_DEPTH:
            raise ParseError(f"line {self.line_no}: bracket nesting exceeds {MAX_BRACKET_DEPTH} levels (cf. PS0118)")

    def exit_bracket(self) -> None:
        self.expect("RBRACKET")
        self.bracket_depth -= 1

    def at_end(self) -> bool:
        return self.pos >= len(self.tokens)


def from_text(stmt_text: str, line_no: int) -> TokenStream:
    return TokenStream(tokenize_macro_stmt(stmt_text, line_no), line_no)


# --------------------------------------------------------------- expressions

def parse_expression_tokens(ts: TokenStream) -> Expr:
    return _parse_add_sub(ts)


def _parse_add_sub(ts: TokenStream) -> Expr:
    left = _parse_mul_div(ts)
    while True:
        tok = ts.peek()
        if tok is None:
            return left
        if tok.kind == "PLUS":
            ts.next()
            left = BinOp("+", left, _parse_mul_div(ts))
        elif tok.kind == "MINUS":
            ts.next()
            left = BinOp("-", left, _parse_mul_div(ts))
        elif ts.peek_is_name("OR", "XOR"):
            op = tok.text.upper()
            ts.next()
            left = BinOp(op, left, _parse_mul_div(ts))
        else:
            return left


def _parse_mul_div(ts: TokenStream) -> Expr:
    left = _parse_unary(ts)
    while True:
        tok = ts.peek()
        if tok is None:
            return left
        if tok.kind == "STAR":
            ts.next()
            left = BinOp("*", left, _parse_unary(ts))
        elif tok.kind == "SLASH":
            ts.next()
            left = BinOp("/", left, _parse_unary(ts))
        elif ts.peek_is_name("AND", "MOD"):
            op = tok.text.upper()
            ts.next()
            left = BinOp(op, left, _parse_unary(ts))
        else:
            return left


def _parse_unary(ts: TokenStream) -> Expr:
    tok = ts.peek()
    if tok is not None and tok.kind == "MINUS":
        ts.next()
        return UnaryMinus(_parse_unary(ts))
    if tok is not None and tok.kind == "PLUS":
        ts.next()
        return _parse_unary(ts)
    return _parse_primary(ts)


def _parse_primary(ts: TokenStream) -> Expr:
    tok = ts.peek()
    if tok is None:
        raise ParseError(f"line {ts.line_no}: unexpected end of expression")

    if tok.kind == "NUMBER":
        ts.next()
        return Literal(float(tok.text))

    if tok.kind == "HASH":
        ts.next()
        return VarRef(_parse_var_index(ts))

    if tok.kind == "LBRACKET":
        ts.enter_bracket()
        expr = parse_expression_tokens(ts)
        ts.exit_bracket()
        return expr

    if tok.kind == "NAME":
        name_upper = tok.text.upper()
        if name_upper in ATAN_NAMES:
            return _parse_atan(ts)
        if name_upper == POW_NAME:
            ts.next()
            ts.enter_bracket()
            arg1 = parse_expression_tokens(ts)
            ts.expect("COMMA")
            arg2 = parse_expression_tokens(ts)
            ts.exit_bracket()
            return FuncCall2("POW", arg1, arg2)
        if name_upper in FUNCTIONS_1ARG:
            canonical = FUNCTIONS_1ARG[name_upper]
            ts.next()
            ts.enter_bracket()
            arg = parse_expression_tokens(ts)
            ts.exit_bracket()
            return FuncCall1(canonical, arg)
        raise ParseError(f"line {ts.line_no}: unexpected identifier {tok.text!r} in expression")

    raise ParseError(f"line {ts.line_no}: unexpected token {tok.kind} {tok.text!r} in expression")


def parse_var_index(ts: TokenStream) -> Expr:
    """Parses what follows a '#': either a plain number or a bracketed
    expression (#[<expr>])."""
    tok = ts.peek()
    if tok is not None and tok.kind == "NUMBER":
        ts.next()
        return Literal(float(tok.text))
    if tok is not None and tok.kind == "LBRACKET":
        ts.enter_bracket()
        expr = parse_expression_tokens(ts)
        ts.exit_bracket()
        return expr
    raise ParseError(f"line {ts.line_no}: expected a variable number after '#'")


_parse_var_index = parse_var_index  # internal alias used above


def _parse_atan(ts: TokenStream) -> Expr:
    ts.next()  # consume ATAN/AT/ATN
    ts.enter_bracket()
    arg1 = parse_expression_tokens(ts)
    tok = ts.peek()
    if tok is not None and tok.kind == "COMMA":
        ts.next()
        arg2 = parse_expression_tokens(ts)
        ts.exit_bracket()
        return FuncCall2("ATAN2", arg1, arg2)
    ts.exit_bracket()
    tok = ts.peek()
    if tok is not None and tok.kind == "SLASH":
        # ATAN[j]/[k]: the '/' here is *not* ordinary division -- it is
        # only legal when immediately followed by a bracketed second
        # argument. Per the manual, ATAN[1]/10 (unbracketed) is a syntax
        # error (PS1131), not a silent fallback to plain division.
        ts.next()
        ts.enter_bracket()
        arg2 = parse_expression_tokens(ts)
        ts.exit_bracket()
        return FuncCall2("ATAN2", arg1, arg2)
    return FuncCall1("ATAN", arg1)


def parse_expression(stmt_text: str, line_no: int) -> Expr:
    ts = from_text(stmt_text, line_no)
    expr = parse_expression_tokens(ts)
    if not ts.at_end():
        raise ParseError(f"line {line_no}: unexpected trailing tokens in expression: {stmt_text!r}")
    return expr


# ---------------------------------------------------------------- conditions

def parse_condition_tokens(ts: TokenStream) -> Condition:
    return _parse_cond_or_xor(ts)


def _parse_cond_or_xor(ts: TokenStream) -> Condition:
    left = _parse_cond_and(ts)
    while ts.peek_is_name("OR", "XOR"):
        op = ts.next().text.upper()
        left = CompoundCondition(op, left, _parse_cond_and(ts))
    return left


def _parse_cond_and(ts: TokenStream) -> Condition:
    left = _parse_cond_term(ts)
    while ts.peek_is_name("AND"):
        ts.next()
        left = CompoundCondition("AND", left, _parse_cond_term(ts))
    return left


def _parse_cond_term(ts: TokenStream) -> Condition:
    tok = ts.peek()
    if tok is not None and tok.kind == "LBRACKET":
        ts.enter_bracket()
        cond = parse_condition_tokens(ts)
        ts.exit_bracket()
        return cond
    return _parse_simple_condition(ts)


def _parse_simple_condition(ts: TokenStream) -> Condition:
    left = parse_expression_tokens(ts)
    tok = ts.next()
    if not (tok.kind == "NAME" and tok.text.upper() in COMPARISON_OPS):
        raise ParseError(
            f"line {ts.line_no}: expected a comparison operator (EQ/NE/GT/GE/LT/LE), got {tok.text!r}"
        )
    op = tok.text.upper()
    right = parse_expression_tokens(ts)
    return SimpleCondition(left, op, right)


# ----------------------------------------------------------------- evaluation

def eval_expr(expr: Expr, store: VariableStore):
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, VarRef):
        index = int(round(arithmetic_value(eval_expr(expr.index_expr, store))))
        return store.get(index)
    if isinstance(expr, UnaryMinus):
        return -arithmetic_value(eval_expr(expr.operand, store))
    if isinstance(expr, BinOp):
        return _eval_binop(expr, store)
    if isinstance(expr, FuncCall1):
        return _eval_func1(expr, store)
    if isinstance(expr, FuncCall2):
        return _eval_func2(expr, store)
    raise TypeError(f"unknown expression node: {expr!r}")


def _eval_binop(expr: BinOp, store: VariableStore) -> float:
    left = arithmetic_value(eval_expr(expr.left, store))
    right = arithmetic_value(eval_expr(expr.right, store))

    if expr.op == "+":
        return left + right
    if expr.op == "-":
        return left - right
    if expr.op == "*":
        return left * right
    if expr.op == "/":
        if right == 0:
            raise MacroError("division by zero (cf. PS0112)")
        return left / right
    if expr.op == "AND":
        return float(int(left) & int(right))
    if expr.op == "OR":
        return float(int(left) | int(right))
    if expr.op == "XOR":
        return float(int(left) ^ int(right))
    if expr.op == "MOD":
        li, ri = int(left), int(right)
        if ri == 0:
            raise MacroError("MOD by zero (cf. PS0112)")
        magnitude = abs(li) % abs(ri)
        return float(-magnitude if li < 0 else magnitude)
    raise ValueError(f"unknown operator {expr.op}")


def _eval_func1(expr: FuncCall1, store: VariableStore) -> float:
    x = arithmetic_value(eval_expr(expr.arg, store))
    name = expr.name
    if name == "SIN":
        return math.sin(math.radians(x))
    if name == "COS":
        return math.cos(math.radians(x))
    if name == "TAN":
        return math.tan(math.radians(x))
    if name == "ASIN":
        if not (-1.0 <= x <= 1.0):
            raise MacroError(f"ASIN argument {x} out of range [-1,1] (cf. PS0119)")
        return math.degrees(math.asin(x))
    if name == "ACOS":
        if not (-1.0 <= x <= 1.0):
            raise MacroError(f"ACOS argument {x} out of range [-1,1] (cf. PS0119)")
        return math.degrees(math.acos(x))
    if name == "ATAN":
        return math.degrees(math.atan(x))
    if name == "SQRT":
        if x < 0:
            raise MacroError(f"SQRT argument {x} is negative (cf. PS0119)")
        return math.sqrt(x)
    if name == "ABS":
        return abs(x)
    if name == "ROUND":
        return float(math.floor(x + 0.5)) if x >= 0 else float(math.ceil(x - 0.5))
    if name == "FIX":
        return float(math.floor(x)) if x >= 0 else float(math.ceil(x))
    if name == "FUP":
        return float(math.ceil(x)) if x >= 0 else float(math.floor(x))
    if name == "LN":
        if x <= 0:
            raise MacroError(f"LN argument {x} must be positive (cf. PS0119)")
        return math.log(x)
    if name == "EXP":
        return math.exp(x)
    if name == "BIN":
        return _bcd_to_bin(x)
    if name == "BCD":
        return _bin_to_bcd(x)
    if name == "ADP":
        return x  # add-decimal-point: a no-op in this simulator's numeric model
    raise ValueError(f"unknown 1-arg function {name}")


def _eval_func2(expr: FuncCall2, store: VariableStore) -> float:
    a = arithmetic_value(eval_expr(expr.arg1, store))
    b = arithmetic_value(eval_expr(expr.arg2, store))
    if expr.name == "POW":
        return math.pow(a, b)
    if expr.name == "ATAN2":
        if a == 0 and b == 0:
            raise MacroError("ATAN with both arguments zero is undefined")
        degrees = math.degrees(math.atan2(a, b))
        if degrees < 0:
            degrees += 360.0
        return degrees
    raise ValueError(f"unknown 2-arg function {expr.name}")


def _bcd_to_bin(x: float) -> float:
    digits = str(int(abs(x)))
    value = 0
    for d in digits:
        value = value * 16 + int(d)
    return float(-value if x < 0 else value)


def _bin_to_bcd(x: float) -> float:
    n = int(abs(x))
    value = 0
    for ch in format(n, "x"):
        value = value * 10 + int(ch, 16)
    return float(-value if x < 0 else value)


def eval_condition(cond: Condition, store: VariableStore) -> bool:
    if isinstance(cond, SimpleCondition):
        left = eval_expr(cond.left, store)
        right = eval_expr(cond.right, store)
        return _compare(left, right, cond.op)
    if isinstance(cond, CompoundCondition):
        left = eval_condition(cond.left, store)
        right = eval_condition(cond.right, store)
        li, ri = int(left), int(right)
        if cond.op == "AND":
            return bool(li & ri)
        if cond.op == "OR":
            return bool(li | ri)
        if cond.op == "XOR":
            return bool(li ^ ri)
        raise ValueError(f"unknown logical operator {cond.op}")
    raise TypeError(f"unknown condition node: {cond!r}")


def _compare(left, right, op: str) -> bool:
    if op in ("EQ", "NE"):
        # EMPTY and 0 are *different* values for EQ/NE (manual 16.1).
        is_equal = (left is EMPTY and right is EMPTY) or (
            left is not EMPTY and right is not EMPTY and left == right
        )
        return is_equal if op == "EQ" else not is_equal
    # GE/GT/LE/LT: EMPTY behaves as 0 (manual 16.1).
    l = 0.0 if left is EMPTY else left
    r = 0.0 if right is EMPTY else right
    if op == "GE":
        return l >= r
    if op == "GT":
        return l > r
    if op == "LE":
        return l <= r
    if op == "LT":
        return l < r
    raise ValueError(f"unknown comparison operator {op}")
