"""Main execution engine.

Phase 0: modal state, G50, and G00/G01/G02/G03 motion.

Phase 1 added macro statements (Assignment/Goto/IfGoto/IfThen/WhileDo/
EndDo) and M98 subprogram calls, executed via a small instruction-pointer
loop (_execute_program) so GOTO/WHILE can jump within a program, with
Python's own call stack providing the (depth-limited) call/return nesting
for M98/M99/G65 -- see docs/PLAN.md sections 6, 11, 13.2.

Phase 2 adds G65 macro calls (argument passing, a *new* local-variable
frame per call -- unlike M98, see docs/variables.md) and generalizes NC
statements to accept variable/expression-valued addresses (manual 16.1
"變量的引用"), since a called macro is otherwise unable to actually move
anything with its arguments.

Canned cycles and tool compensation are not supported yet; encountering
their G-codes raises UnsupportedFeatureError rather than being silently
ignored or misinterpreted.
"""

from dataclasses import dataclass

from .ast_nodes import Assignment, EndDo, Goto, IfGoto, IfThen, NCStatement, WhileDo
from .errors import MacroError, ParseError, UnsupportedFeatureError
from .expression import eval_condition, eval_expr
from .lexer import Word
from .motion import arc_center_from_offset, arc_center_from_radius
from .tool_table import ToolTable
from .toolpath import Move, Point, Toolpath
from .units import to_internal_length
from .variables import (
    EMPTY,
    MAX_CALL_DEPTH_MACRO,
    MAX_CALL_DEPTH_SUBPROGRAM,
    MAX_CALL_DEPTH_TOTAL,
    VariableStore,
)

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

# G65 argument address -> local variable number, "type I" form (manual
# 16.7.1). G, L, N, O, P are never valid argument addresses.
TYPE1_ARG_MAP = {
    "A": 1, "B": 2, "C": 3, "D": 7, "E": 8, "F": 9, "H": 11,
    "I": 4, "J": 5, "K": 6, "M": 13, "Q": 17, "R": 18, "S": 19,
    "T": 20, "U": 21, "V": 22, "W": 23, "X": 24, "Y": 25, "Z": 26,
}
TYPE2_FIXED_ARG_MAP = {"A": 1, "B": 2, "C": 3}
TYPE2_MAX_GROUPS = 10


class _EndOfProgram(Exception):
    """Internal control-flow signal for M30/M02, unwinding all the way to
    the top-level run() call regardless of call-stack depth."""


@dataclass
class ResolvedWord:
    value: float  # never EMPTY -- callers that would see EMPTY never get
                   # a ResolvedWord for that address at all (see _group_by_address)
    raw_text: str | None  # original literal text, if this word was a plain
                            # number (not an expression) -- used for T-codes
                            # etc. where the exact digit string matters


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
        self._macro_depth = 0
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
            call = self._get_call(stmt)
            if call is not None:
                kind, program_no, repeat, args = call
                if kind == "M98":
                    self._call_subprogram(program_no, repeat)
                else:
                    self._call_macro(program_no, repeat, args)
                return None
            if self._get_m99(stmt):
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
        target = int(round(_as_float(eval_expr(target_expr, self.variables))))
        if target not in seq_index:
            raise MacroError(f"line {line_no}: GOTO target N{target} not found (cf. PS0128)")
        return seq_index[target]

    def _exec_assignment(self, stmt: Assignment) -> None:
        index = int(round(_as_float(eval_expr(stmt.target.index_expr, self.variables))))
        value = eval_expr(stmt.expr, self.variables)
        self.variables.set(index, value)

    # ------------------------------------------------------------- calls

    def _get_call(self, stmt: NCStatement) -> tuple[str, int, int, dict[int, float]] | None:
        """Detects G65 (macro call) or M98 (subprogram call). Both are
        plain NC-shaped statements (address-value pairs), not part of the
        control-flow/assignment grammar."""
        is_g65 = any(w.address == "G" and self._resolve_word_raw(w) == 65.0 for w in stmt.words)
        is_m98 = any(w.address == "M" and self._resolve_word_raw(w) == 98.0 for w in stmt.words)
        if not is_g65 and not is_m98:
            return None
        if is_g65 and is_m98:
            raise ParseError(f"line {stmt.line_no}: a block cannot be both G65 and M98")

        program_no = self._require_address_value(stmt, "P")
        repeat = self._optional_address_value(stmt, "L", default=1.0)

        if is_m98:
            return "M98", int(program_no), int(repeat), {}

        args = self._extract_g65_args(stmt)
        return "G65", int(program_no), int(repeat), args

    def _require_address_value(self, stmt: NCStatement, address: str) -> float:
        w = next((w for w in stmt.words if w.address == address), None)
        if w is None:
            raise ParseError(f"line {stmt.line_no}: G65/M98 requires a {address} address")
        value = self._resolve_word_raw(w)
        if value is EMPTY:
            raise MacroError(f"line {stmt.line_no}: {address} address evaluated to <empty>")
        return value

    def _optional_address_value(self, stmt: NCStatement, address: str, default: float) -> float:
        w = next((w for w in stmt.words if w.address == address), None)
        if w is None:
            return default
        value = self._resolve_word_raw(w)
        return default if value is EMPTY else value

    def _extract_g65_args(self, stmt: NCStatement) -> dict[int, float]:
        arg_words = [w for w in stmt.words if w.address not in ("G", "P", "L", "N")]
        resolved = [(w.address, self._resolve_word_raw(w)) for w in arg_words]
        resolved = [(addr, val) for addr, val in resolved if val is not EMPTY]

        ijk_counts: dict[str, int] = {"I": 0, "J": 0, "K": 0}
        for addr, _ in resolved:
            if addr in ijk_counts:
                ijk_counts[addr] += 1
        is_type2 = any(c > 1 for c in ijk_counts.values())

        args: dict[int, float] = {}
        if is_type2:
            i_list = [v for a, v in resolved if a == "I"]
            j_list = [v for a, v in resolved if a == "J"]
            k_list = [v for a, v in resolved if a == "K"]
            n_groups = max(len(i_list), len(j_list), len(k_list))
            if n_groups > TYPE2_MAX_GROUPS:
                raise ParseError(f"line {stmt.line_no}: G65 type II supports at most {TYPE2_MAX_GROUPS} I/J/K groups")
            for idx in range(n_groups):
                base = 4 + idx * 3
                if idx < len(i_list):
                    args[base] = i_list[idx]
                if idx < len(j_list):
                    args[base + 1] = j_list[idx]
                if idx < len(k_list):
                    args[base + 2] = k_list[idx]
            for addr, val in resolved:
                if addr in TYPE2_FIXED_ARG_MAP:
                    args[TYPE2_FIXED_ARG_MAP[addr]] = val
                elif addr not in ("I", "J", "K"):
                    raise ParseError(
                        f"line {stmt.line_no}: {addr} is not valid alongside repeated I/J/K "
                        "(G65 type II only allows A/B/C plus I/J/K groups)"
                    )
        else:
            for addr, val in resolved:
                if addr not in TYPE1_ARG_MAP:
                    raise ParseError(f"line {stmt.line_no}: {addr} is not a valid G65 type I argument address")
                args[TYPE1_ARG_MAP[addr]] = val
        return args

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

    def _call_macro(self, program_no: int, repeat: int, args: dict[int, float]) -> None:
        if self.registry is None:
            raise MacroError("G65 requires a program registry")
        if self._macro_depth >= MAX_CALL_DEPTH_MACRO:
            raise MacroError(f"macro call nesting exceeds {MAX_CALL_DEPTH_MACRO} levels")
        if self._call_depth >= MAX_CALL_DEPTH_TOTAL:
            raise MacroError(f"combined macro/subprogram call nesting exceeds {MAX_CALL_DEPTH_TOTAL} levels")
        statements = self.registry.get(program_no)
        self._macro_depth += 1
        self._call_depth += 1
        try:
            for _ in range(repeat):
                # Each G65 invocation gets its own fresh local-variable
                # frame (unlike M98) -- see docs/variables.md.
                self.variables.locals.push_frame(args)
                try:
                    self._execute_program(statements)
                finally:
                    self.variables.locals.pop_frame()
        finally:
            self._macro_depth -= 1
            self._call_depth -= 1

    # ------------------------------------------------------ NC statements

    def _resolve_word_raw(self, w: Word):
        """Returns the word's value (float) or EMPTY -- never raises for
        an undefined variable, per manual 16.1's "the address itself is
        ignored" rule (handled by the caller, not here)."""
        if w.expr is not None:
            return eval_expr(w.expr, self.variables)
        return float(w.value)

    def _ends_program(self, stmt: NCStatement) -> bool:
        return any(
            w.address == "M" and self._resolve_word_raw(w) in END_PROGRAM_M for w in stmt.words
        )

    def _group_by_address(self, stmt: NCStatement) -> dict[str, list[ResolvedWord]]:
        """Groups words by address, resolving each through self.variables.
        An address whose value resolves to EMPTY is dropped entirely (not
        treated as 0) -- manual 16.1: referencing an undefined variable
        causes the whole address to be ignored, as if never specified."""
        by_addr: dict[str, list[ResolvedWord]] = {}
        for w in stmt.words:
            value = self._resolve_word_raw(w)
            if value is EMPTY:
                continue
            by_addr.setdefault(w.address, []).append(ResolvedWord(value=value, raw_text=w.value))
        return by_addr

    def _execute(self, stmt: NCStatement) -> None:
        by_addr = self._group_by_address(stmt)

        g_words = by_addr.get("G", [])
        is_g50 = any(rw.value == 50.0 for rw in g_words)
        motion_group_words = [rw for rw in g_words if rw.value != 50.0]
        self._apply_g_codes(motion_group_words)

        if "T" in by_addr:
            rw = by_addr["T"][0]
            self.state.tool = rw.raw_text if rw.raw_text is not None else str(int(rw.value))

        if is_g50:
            self._apply_g50(by_addr)
            return  # X/Z in a G50 block declare a coordinate, they don't move the tool

        self._apply_motion(stmt, by_addr)

    def _apply_g_codes(self, g_words: list[ResolvedWord]) -> None:
        for rw in g_words:
            code = rw.value
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

    def _apply_g50(self, by_addr: dict[str, list[ResolvedWord]]) -> None:
        z, x = self.state.pos
        if "Z" in by_addr:
            z = to_internal_length("Z", by_addr["Z"][0].value, unit_scale=self.state.unit_scale)
        if "X" in by_addr:
            x = to_internal_length("X", by_addr["X"][0].value, unit_scale=self.state.unit_scale)
        self.state.pos = (z, x)
        if "S" in by_addr:
            self.state.max_spindle_rpm = by_addr["S"][0].value

    def _apply_motion(self, stmt: NCStatement, by_addr: dict[str, list[ResolvedWord]]) -> None:
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
            feed=by_addr["F"][0].value if "F" in by_addr else None,
            spindle=by_addr["S"][0].value if "S" in by_addr else None,
            source_line=stmt.line_no,
            tool=self.state.tool,
        )
        if kind == "arc":
            clockwise = self.state.motion_g == 2.0
            move.arc_center = self._resolve_arc_center(stmt, by_addr, start, end, clockwise)
            move.arc_ccw = not clockwise

        self.toolpath.append(move)
        self.state.pos = end

    def _resolve_end_point(
        self, stmt: NCStatement, by_addr: dict[str, list[ResolvedWord]], start: Point
    ) -> Point:
        if "Z" in by_addr and "W" in by_addr:
            raise ParseError(f"line {stmt.line_no}: both Z and W specified in the same block")
        if "X" in by_addr and "U" in by_addr:
            raise ParseError(f"line {stmt.line_no}: both X and U specified in the same block")

        sz, sx = start
        z, x = sz, sx
        if "Z" in by_addr:
            z = to_internal_length("Z", by_addr["Z"][0].value, unit_scale=self.state.unit_scale)
        elif "W" in by_addr:
            z = sz + to_internal_length("W", by_addr["W"][0].value, unit_scale=self.state.unit_scale)
        if "X" in by_addr:
            x = to_internal_length("X", by_addr["X"][0].value, unit_scale=self.state.unit_scale)
        elif "U" in by_addr:
            x = sx + to_internal_length("U", by_addr["U"][0].value, unit_scale=self.state.unit_scale)
        return (z, x)

    def _resolve_arc_center(
        self,
        stmt: NCStatement,
        by_addr: dict[str, list[ResolvedWord]],
        start: Point,
        end: Point,
        clockwise: bool,
    ) -> Point:
        if "I" in by_addr or "K" in by_addr:
            i = to_internal_length("I", by_addr["I"][0].value, unit_scale=self.state.unit_scale) if "I" in by_addr else 0.0
            k = to_internal_length("K", by_addr["K"][0].value, unit_scale=self.state.unit_scale) if "K" in by_addr else 0.0
            return arc_center_from_offset(start, k=k, i=i)
        if "R" in by_addr:
            r = to_internal_length("R", by_addr["R"][0].value, unit_scale=self.state.unit_scale)
            return arc_center_from_radius(start, end, r, clockwise)
        raise ParseError(f"line {stmt.line_no}: arc (G02/G03) requires I/K or R")

    def _get_m99(self, stmt: NCStatement) -> bool:
        return any(w.address == "M" and self._resolve_word_raw(w) == 99.0 for w in stmt.words)


# ------------------------------------------------------------ free helpers

def _as_float(value) -> float:
    if value is EMPTY:
        raise MacroError("expected a value but got <empty>")
    return value


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
