"""Main execution engine.

Phase 0: modal state, G50, and G00/G01/G02/G03 motion (see _execute,
mostly unchanged from Phase 0).

Phase 1 adds macro statements (Assignment/Goto/IfGoto/IfThen/WhileDo/
EndDo) and M98 subprogram calls, executed via a small instruction-pointer
loop (_execute_program) so GOTO/WHILE can jump within a program, with
Python's own call stack providing the (depth-limited) call/return nesting
for M98/M99 -- see docs/PLAN.md sections 6, 11, 13.2.

Canned cycles, G65 macro calls, and tool compensation are not supported
yet; encountering their G/M-codes raises UnsupportedFeatureError rather
than being silently ignored or misinterpreted.
"""

from dataclasses import dataclass

from .ast_nodes import Assignment, EndDo, Goto, IfGoto, IfThen, NCStatement, Stmt, WhileDo
from .errors import MacroError, ParseError, UnsupportedFeatureError
from .expression import eval_condition, eval_expr
from .lexer import Word
from .motion import arc_center_from_offset, arc_center_from_radius
from .tool_table import ToolTable
from .toolpath import Move, Point, Toolpath
from .units import to_internal_length
from .variables import MAX_CALL_DEPTH_SUBPROGRAM, MAX_CALL_DEPTH_TOTAL, VariableStore

# 01-group (motion) G-codes implemented in Phase 0. G32/G90/G92/G94/G70-76
# are recognized (see UNSUPPORTED_G) but arrive in Phase 3/4.
PHASE0_MOTION_G = {0.0, 1.0, 2.0, 3.0}

# G-codes that are parsed but have no effect on the toolpath in this
# simulator: plane selection (always ZX), tool-comp mode flag (real
# compensation is Phase 4.5), and spindle/feed mode (recorded nowhere --
# see docs/PLAN.md section 13.7, there is no consumer since path geometry
# and animation playback don't depend on them).
INERT_G = {17.0, 18.0, 19.0, 40.0, 41.0, 42.0, 96.0, 97.0, 98.0, 99.0}

# Recognized but not implemented until a later phase. Raising here (rather
# than silently no-op'ing) matters because ignoring these would silently
# produce a wrong path, not just missing metadata.
UNSUPPORTED_G = {
    28.0, 30.0,  # reference point return
    32.0,  # thread cutting
    54.0, 55.0, 56.0, 57.0, 58.0, 59.0,  # work coordinate systems
    70.0, 71.0, 72.0, 73.0, 74.0, 75.0, 76.0,  # compound canned cycles
    90.0, 92.0, 94.0,  # single-form canned cycles
}

END_PROGRAM_M = {2.0, 30.0}

KIND_FOR_MOTION_G = {0.0: "rapid", 1.0: "linear", 2.0: "arc", 3.0: "arc"}


class _EndOfProgram(Exception):
    """Internal control-flow signal for M30/M02, unwinding all the way to
    the top-level run() call regardless of call-stack depth."""


@dataclass
class ModalState:
    motion_g: float | None = None
    unit_scale: float = 1.0  # 1.0 = mm (G21, default), 25.4 = inch (G20)
    pos: Point = (0.0, 0.0)  # (z, x), x in radius units
    tool: str | None = None
    max_spindle_rpm: float | None = None


class Interpreter:
    def __init__(self, tool_table: ToolTable | None = None):
        self.state = ModalState()
        self.tool_table = tool_table if tool_table is not None else ToolTable()
        self.toolpath = Toolpath()
        self.variables = VariableStore()
        self.variables.bind_position_provider(lambda: self.state.pos)
        self.registry = None
        self._subprogram_depth = 0
        self._call_depth = 0

    def run(self, statements: list, registry=None) -> Toolpath:
        self.registry = registry
        try:
            self._execute_program(statements)
        except _EndOfProgram:
            pass
        self.toolpath.max_spindle_rpm = self.state.max_spindle_rpm
        return self.toolpath

    # ------------------------------------------------- program-level loop

    def _execute_program(self, statements: list) -> None:
        seq_index, do_to_end, end_to_do = _build_indices(statements)
        ip = 0
        n = len(statements)
        while ip < n:
            stmt = statements[ip]
            outcome = self._execute_one(stmt, ip, seq_index, do_to_end, end_to_do)
            if outcome is None:
                ip += 1
            elif outcome == "RETURN":
                return
            else:
                ip = outcome  # absolute jump target

    def _execute_one(self, stmt, index: int, seq_index, do_to_end, end_to_do):
        if isinstance(stmt, NCStatement):
            if self._ends_program(stmt):
                raise _EndOfProgram()
            m98 = _get_m98_call(stmt)
            if m98 is not None:
                program_no, repeat = m98
                self._call_subprogram(program_no, repeat)
                return None
            if _get_m99(stmt):
                return "RETURN"
            self._execute(stmt)
            return None

        if isinstance(stmt, Assignment):
            self._exec_assignment(stmt)
            return None

        if isinstance(stmt, Goto):
            return self._resolve_jump(stmt.target, seq_index, stmt.line_no)

        if isinstance(stmt, IfGoto):
            if eval_condition(stmt.cond, self.variables):
                return self._resolve_jump(stmt.target, seq_index, stmt.line_no)
            return None

        if isinstance(stmt, IfThen):
            if eval_condition(stmt.cond, self.variables):
                return self._execute_one(stmt.then_stmt, index, seq_index, do_to_end, end_to_do)
            return None

        if isinstance(stmt, WhileDo):
            if stmt.cond is None or eval_condition(stmt.cond, self.variables):
                return None  # fall through into the loop body
            return do_to_end[index] + 1  # condition false: jump past END

        if isinstance(stmt, EndDo):
            return end_to_do[index]  # always jump back to re-check WHILE

        raise TypeError(f"unknown statement type: {stmt!r}")

    def _resolve_jump(self, target_expr, seq_index: dict[int, int], line_no: int) -> int:
        target = int(round(eval_expr(target_expr, self.variables)))
        if target not in seq_index:
            raise MacroError(f"line {line_no}: GOTO target N{target} not found (cf. PS0128)")
        return seq_index[target]

    def _exec_assignment(self, stmt: Assignment) -> None:
        index = int(round(eval_expr(stmt.target.index_expr, self.variables)))
        value = eval_expr(stmt.expr, self.variables)
        self.variables.set(index, value)

    def _call_subprogram(self, program_no: int, repeat: int) -> None:
        if self.registry is None:
            raise MacroError("M98 requires a program registry")
        if self._subprogram_depth >= MAX_CALL_DEPTH_SUBPROGRAM:
            raise MacroError(f"subprogram call nesting exceeds {MAX_CALL_DEPTH_SUBPROGRAM} levels")
        if self._call_depth >= MAX_CALL_DEPTH_TOTAL:
            raise MacroError(f"combined macro/subprogram call nesting exceeds {MAX_CALL_DEPTH_TOTAL} levels")
        statements = self.registry.get(program_no)
        self._subprogram_depth += 1
        self._call_depth += 1
        try:
            for _ in range(repeat):
                self._execute_program(statements)
        finally:
            self._subprogram_depth -= 1
            self._call_depth -= 1

    # ------------------------------------------------------ NC statements
    # (Phase 0, unchanged: motion, G50, unit/tool bookkeeping)

    def _ends_program(self, stmt: NCStatement) -> bool:
        return any(w.address == "M" and w.as_float() in END_PROGRAM_M for w in stmt.words)

    def _group_by_address(self, stmt: NCStatement) -> dict[str, list[Word]]:
        by_addr: dict[str, list[Word]] = {}
        for w in stmt.words:
            by_addr.setdefault(w.address, []).append(w)
        return by_addr

    def _execute(self, stmt: NCStatement) -> None:
        by_addr = self._group_by_address(stmt)

        g_words = by_addr.get("G", [])
        is_g50 = any(w.as_float() == 50.0 for w in g_words)
        motion_group_words = [w for w in g_words if w.as_float() != 50.0]
        self._apply_g_codes(motion_group_words)
        self._apply_m_codes(by_addr.get("M", []))

        if "T" in by_addr:
            self.state.tool = by_addr["T"][0].value

        if is_g50:
            self._apply_g50(by_addr)
            return  # X/Z in a G50 block declare a coordinate, they don't move the tool

        self._apply_motion(stmt, by_addr)

    def _apply_g_codes(self, g_words: list[Word]) -> None:
        for w in g_words:
            code = w.as_float()
            if code == 20.0:
                self.state.unit_scale = 25.4
            elif code == 21.0:
                self.state.unit_scale = 1.0
            elif code in PHASE0_MOTION_G:
                self.state.motion_g = code
            elif code in INERT_G:
                continue
            elif code in UNSUPPORTED_G:
                raise UnsupportedFeatureError(
                    f"G{code:g} is recognized but not implemented until a later phase"
                )
            else:
                raise UnsupportedFeatureError(f"unrecognized G-code: G{code:g}")

    def _apply_m_codes(self, m_words: list[Word]) -> None:
        # M98/M99 are handled by _execute_one before _execute is reached;
        # anything else (spindle on/off, coolant, ...) has no effect on
        # the toolpath (see docs/PLAN.md section 13.5) and is ignored.
        return

    def _apply_g50(self, by_addr: dict[str, list[Word]]) -> None:
        z, x = self.state.pos
        if "Z" in by_addr:
            z = to_internal_length("Z", by_addr["Z"][0].as_float(), unit_scale=self.state.unit_scale)
        if "X" in by_addr:
            x = to_internal_length("X", by_addr["X"][0].as_float(), unit_scale=self.state.unit_scale)
        self.state.pos = (z, x)
        if "S" in by_addr:
            self.state.max_spindle_rpm = by_addr["S"][0].as_float()

    def _apply_motion(self, stmt: NCStatement, by_addr: dict[str, list[Word]]) -> None:
        if not any(a in by_addr for a in ("X", "Z", "U", "W")):
            return
        if self.state.motion_g is None:
            raise ParseError(
                f"line {stmt.line_no}: motion word given before any motion G-code was specified"
            )
        if self.state.motion_g not in PHASE0_MOTION_G:
            raise UnsupportedFeatureError(
                f"line {stmt.line_no}: modal G-code G{self.state.motion_g:g} is not "
                "a Phase 0 motion code"
            )

        start = self.state.pos
        end = self._resolve_end_point(stmt, by_addr, start)
        kind = KIND_FOR_MOTION_G[self.state.motion_g]

        move = Move(
            kind=kind,
            start=start,
            end=end,
            feed=by_addr["F"][0].as_float() if "F" in by_addr else None,
            spindle=by_addr["S"][0].as_float() if "S" in by_addr else None,
            source_line=stmt.line_no,
            tool=self.state.tool,
        )
        if kind == "arc":
            clockwise = self.state.motion_g == 2.0
            move.arc_center = self._resolve_arc_center(stmt, by_addr, start, end, clockwise)
            move.arc_ccw = not clockwise

        self.toolpath.append(move)
        self.state.pos = end

    def _resolve_end_point(self, stmt: NCStatement, by_addr: dict[str, list[Word]], start: Point) -> Point:
        if "Z" in by_addr and "W" in by_addr:
            raise ParseError(f"line {stmt.line_no}: both Z and W specified in the same block")
        if "X" in by_addr and "U" in by_addr:
            raise ParseError(f"line {stmt.line_no}: both X and U specified in the same block")

        sz, sx = start
        z, x = sz, sx
        if "Z" in by_addr:
            z = to_internal_length("Z", by_addr["Z"][0].as_float(), unit_scale=self.state.unit_scale)
        elif "W" in by_addr:
            z = sz + to_internal_length("W", by_addr["W"][0].as_float(), unit_scale=self.state.unit_scale)
        if "X" in by_addr:
            x = to_internal_length("X", by_addr["X"][0].as_float(), unit_scale=self.state.unit_scale)
        elif "U" in by_addr:
            x = sx + to_internal_length("U", by_addr["U"][0].as_float(), unit_scale=self.state.unit_scale)
        return (z, x)

    def _resolve_arc_center(
        self, stmt: NCStatement, by_addr: dict[str, list[Word]], start: Point, end: Point, clockwise: bool
    ) -> Point:
        if "I" in by_addr or "K" in by_addr:
            i = to_internal_length("I", by_addr["I"][0].as_float(), unit_scale=self.state.unit_scale) if "I" in by_addr else 0.0
            k = to_internal_length("K", by_addr["K"][0].as_float(), unit_scale=self.state.unit_scale) if "K" in by_addr else 0.0
            return arc_center_from_offset(start, k=k, i=i)
        if "R" in by_addr:
            r = to_internal_length("R", by_addr["R"][0].as_float(), unit_scale=self.state.unit_scale)
            return arc_center_from_radius(start, end, r, clockwise)
        raise ParseError(f"line {stmt.line_no}: arc (G02/G03) requires I/K or R")


# ------------------------------------------------------------ free helpers

def _get_m98_call(stmt: NCStatement) -> tuple[int, int] | None:
    m_word = next((w for w in stmt.words if w.address == "M" and w.as_float() == 98.0), None)
    if m_word is None:
        return None
    p_word = next((w for w in stmt.words if w.address == "P"), None)
    if p_word is None:
        raise ParseError(f"line {stmt.line_no}: M98 requires a P address (program number)")
    program_no = int(p_word.as_float())
    l_word = next((w for w in stmt.words if w.address == "L"), None)
    repeat = int(l_word.as_float()) if l_word is not None else 1
    return program_no, repeat


def _get_m99(stmt: NCStatement) -> bool:
    return any(w.address == "M" and w.as_float() == 99.0 for w in stmt.words)


def _build_indices(statements: list) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
    """Sequence-number -> index map (for GOTO), plus the matching
    WhileDo<->EndDo index maps, enforcing the manual's WHILE/DO nesting
    rules (max 3 deep, ranges must not overlap -- section 16.6.4)."""
    seq_index: dict[int, int] = {}
    do_stack: list[tuple[int, int]] = []
    do_to_end: dict[int, int] = {}
    end_to_do: dict[int, int] = {}

    for i, stmt in enumerate(statements):
        seq_no = getattr(stmt, "seq_no", None)
        if seq_no is not None and seq_no not in seq_index:
            seq_index[seq_no] = i

        if isinstance(stmt, WhileDo):
            if any(existing_id == stmt.loop_id for existing_id, _ in do_stack):
                raise MacroError(
                    f"line {stmt.line_no}: DO{stmt.loop_id} nested inside an already-open "
                    f"DO{stmt.loop_id} (cf. PS0124)"
                )
            if len(do_stack) >= 3:
                raise MacroError(f"line {stmt.line_no}: WHILE/DO nesting exceeds 3 levels")
            do_stack.append((stmt.loop_id, i))
        elif isinstance(stmt, EndDo):
            if not do_stack or do_stack[-1][0] != stmt.loop_id:
                raise MacroError(
                    f"line {stmt.line_no}: END{stmt.loop_id} does not match the innermost "
                    "open DO (cf. PS0124)"
                )
            _, do_index = do_stack.pop()
            do_to_end[do_index] = i
            end_to_do[i] = do_index

    if do_stack:
        loop_id, do_index = do_stack[-1]
        raise MacroError(f"DO{loop_id} (statement index {do_index}) is never closed with a matching END")

    return seq_index, do_to_end, end_to_do
