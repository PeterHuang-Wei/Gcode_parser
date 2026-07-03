"""Main execution loop for Phase 0: modal state, G50, and G00/G01/G02/G03
motion. Macro statements, canned cycles, and tool compensation are not
supported yet (see docs/PLAN.md sections 6, 7, 11) -- encountering them
raises UnsupportedFeatureError rather than being silently ignored or
misinterpreted.
"""

from dataclasses import dataclass

from .ast_nodes import NCStatement
from .errors import ParseError, UnsupportedFeatureError
from .lexer import Word
from .motion import arc_center_from_offset, arc_center_from_radius
from .tool_table import ToolTable
from .toolpath import Move, Point, Toolpath
from .units import to_internal_length

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
UNSUPPORTED_M = {98.0, 99.0}  # subprogram call/return -- Phase 1

KIND_FOR_MOTION_G = {0.0: "rapid", 1.0: "linear", 2.0: "arc", 3.0: "arc"}


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

    def run(self, statements: list[NCStatement]) -> Toolpath:
        for stmt in statements:
            if self._ends_program(stmt):
                break
            self._execute(stmt)
        self.toolpath.max_spindle_rpm = self.state.max_spindle_rpm
        return self.toolpath

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
        self._apply_m_codes(by_addr.get("M", []), stmt)

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

    def _apply_m_codes(self, m_words: list[Word], stmt: NCStatement) -> None:
        for w in m_words:
            code = w.as_float()
            if code in UNSUPPORTED_M:
                raise UnsupportedFeatureError(
                    f"line {stmt.line_no}: M{code:g} (subprogram call/return) "
                    "is not implemented until Phase 1"
                )
            # spindle on/off, coolant, etc: no effect on the toolpath (see
            # docs/PLAN.md section 13.5), intentionally ignored.

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
