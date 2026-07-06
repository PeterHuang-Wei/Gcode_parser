"""AST node definitions.

Phase 0 has only NCStatement. Phase 1 adds expressions, conditions, and
the macro-statement family (assignment, GOTO/IF/WHILE/END). G65 macro
calls arrive in Phase 2 (docs/PLAN.md section 11).
"""

from dataclasses import dataclass

from .lexer import Word


@dataclass
class NCStatement:
    seq_no: int | None
    words: list[Word]
    skip: bool
    line_no: int


# ---------------------------------------------------------------- expressions

class Expr:
    """Base class for <expression> AST nodes (docs/PLAN.md section 4)."""


@dataclass
class Literal(Expr):
    value: float


@dataclass
class VarRef(Expr):
    index_expr: Expr  # evaluates to the variable number, e.g. #[#100]


@dataclass
class NamedVarRef(Expr):
    """A named macro-variable alias, e.g. #_OFST -- not documented in
    either manual excerpt read for this project, but a real convention
    some machines/post-processors use for named system-variable aliases
    (typically prefixed with an underscore). Not in variables.py's system
    variable table (we don't have the real alias-to-number mapping), so
    this always evaluates to <empty> (see expression.py's eval_expr),
    with a warning printed rather than aborting parsing of the whole
    program over one unrecognized reference."""

    name: str  # the text after '#', e.g. "_OFST"


@dataclass
class UnaryMinus(Expr):
    operand: Expr


@dataclass
class BinOp(Expr):
    op: str  # '+', '-', '*', '/', 'AND', 'OR', 'XOR', 'MOD'
    left: Expr
    right: Expr


@dataclass
class FuncCall1(Expr):
    name: str  # SIN, COS, TAN, ASIN, ACOS, ATAN, SQRT, ABS, ROUND, FIX, FUP, LN, EXP, BIN, BCD, ADP
    arg: Expr


@dataclass
class FuncCall2(Expr):
    name: str  # POW, ATAN2 (the 2-argument form of ATAN)
    arg1: Expr
    arg2: Expr


# ----------------------------------------------------------------- conditions

class Condition:
    """Base class for <condition expression> nodes (IF/WHILE only)."""


@dataclass
class SimpleCondition(Condition):
    left: Expr
    op: str  # EQ, NE, GT, GE, LT, LE
    right: Expr


@dataclass
class CompoundCondition(Condition):
    op: str  # AND, OR, XOR
    left: Condition
    right: Condition


# ------------------------------------------------------------ macro statements

class Stmt:
    """Base class for macro-language statements."""


@dataclass
class Assignment(Stmt):
    target: VarRef
    expr: Expr
    seq_no: int | None
    line_no: int


@dataclass
class Goto(Stmt):
    target: Expr
    seq_no: int | None
    line_no: int


@dataclass
class IfGoto(Stmt):
    cond: Condition
    target: Expr
    seq_no: int | None
    line_no: int


@dataclass
class IfThen(Stmt):
    cond: Condition
    then_stmt: Stmt
    seq_no: int | None
    line_no: int


@dataclass
class WhileDo(Stmt):
    cond: Condition | None  # None: WHILE omitted -> unconditional loop
    loop_id: int
    seq_no: int | None
    line_no: int


@dataclass
class EndDo(Stmt):
    loop_id: int
    seq_no: int | None
    line_no: int
