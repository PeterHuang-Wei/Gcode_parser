"""G73 (pattern repeating / closed-loop roughing, manual 4.2.3) --
compound canned cycle.

Unlike G71/G72 (which step through Δd-deep layers and cut down to where
each layer intersects the finishing contour), G73 has no intersection
math at all: it retraces the *entire* traced shape program d times,
each time as a plain parallel translation of the whole contour, offset
by a progressively decreasing amount -- from a total retreat of
(Δi, Δk) plus the finishing allowance on the first (roughest) pass, down
to just the finishing allowance (Δu, Δw) alone on the d-th (last, closest
to the real finished shape) pass. This works for any shape (not just a
Type-I monotonic contour), since there's no per-level lookup requiring
monotonicity -- G73 is meant for pre-formed/cast blanks whose rough shape
already loosely resembles the finished part (e.g. a forging), which is
exactly the case a plain parallel offset suits.

Algorithm (independently derived from the manual's structural
description, like G71/G72's roughing.py -- not cross-checked against a
worked numeric example; flagged for extra scrutiny if a real program's
expected path disagrees):

1. Trace the shape program (ns..nf) from the current position S once
   (contour.py, shared with G70/G71/G72).
2. For pass n = 1..d: offset the *whole* traced Move list by
   (Δw + Δk*(d-n)/d, Δu + Δi*(d-n)/d) -- a straight parallel shift, not
   just the two endpoints -- then rapid from wherever the previous pass
   ended to this pass's own (shifted) start point, and feed along the
   whole shifted shape.
3. No 45-degree retreat between passes (that's specific to G71/G72's
   per-layer cutting geometry) -- passes just rapid directly to the next
   one's start point.
"""

from ..errors import CannedCycleError
from ..toolpath import Move, Point
from . import contour as contour_mod


def expand_g73(
    start: Point,
    shape_moves: list[Move],
    i_total: float,
    k_total: float,
    num_cuts: int,
    du: float,
    dw: float,
    feed: float | None,
    source_line: int | None,
) -> list[Move]:
    if num_cuts <= 0:
        raise CannedCycleError("G73 number of divisions (d, the R address) must be a positive integer")
    if not shape_moves:
        raise CannedCycleError("G73 shape program produced no motion")

    moves: list[Move] = []
    pos = start
    for n in range(1, num_cuts + 1):
        frac = (num_cuts - n) / num_cuts
        offset_z = dw + k_total * frac
        offset_x = du + i_total * frac
        pass_moves = contour_mod.offset_moves(shape_moves, offset_z, offset_x, feed, "G73")
        if not pass_moves:
            continue
        contour_start = pass_moves[0].start
        if pos != contour_start:
            moves.append(Move(kind="rapid", start=pos, end=contour_start, source_line=source_line, cycle="G73"))
        moves.extend(pass_moves)
        pos = moves[-1].end
    return moves
