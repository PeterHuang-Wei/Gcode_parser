"""G71 (external/internal roughing, manual 4.2.1) and G72 (facing
roughing, manual 4.2.2) -- compound canned cycles.

Only Type I (a single monotonic contour, no grooves/pockets) is
implemented; Type II (contours with pockets) raises CannedCycleError --
see docs/PLAN.md's phased roadmap (grooves are explicitly lower
priority than the common case).

Algorithm (independently derived from the manual's structural
description -- the action list in 4.2.1/4.2.2 -- and standard, well-
known G71/G72 behavior; not cross-checked against a manual worked
numeric example, since none was available in the excerpts read. Flagged
here, like the G90/G94 taper formula, for extra scrutiny if a real
program's expected path disagrees):

1. Trace the shape program (ns..nf) from the current position S. The
   opening block (ns) is required to move only the "step" axis (X for
   G71, Z for G72), establishing point A' -- comparing S to A' gives the
   cutting direction.
2. Offset every traced point by the signed finishing allowance (Δw in
   Z, Δu in X) to get the "rough target" contour.
3. Step from S toward A' (and beyond, as far as the shape requires) in
   Δd increments. Each pass: rapid to the new step-axis level (at the
   clearance position on the other axis), feed to where that level
   crosses the offset contour, retract 45 degrees by e (away from the
   cut), rapid back to the clearance position.
4. A final pass re-traces the exact offset contour shape (manual
   4.2.1 action 4: "在最後的切削完成後，刀具馬上沿著精削形狀程序執行
   最後的粗精加工切削").

G71 steps parallel to X (cuts by feeding along Z at each X level); G72
steps parallel to Z (cuts by feeding along X at each Z level) -- the two
functions below are axis-swapped mirrors of each other.
"""

import math

from ..errors import CannedCycleError
from ..toolpath import Move, Point
from . import contour as contour_mod


def _offset_point(p: Point, dz: float, dx: float) -> Point:
    return (p[0] + dz, p[1] + dx)


def _final_contour_pass(shape_moves: list[Move], dz: float, dx: float, feed: float | None, cycle_name: str) -> list[Move]:
    moves = []
    for m in shape_moves:
        start = _offset_point(m.start, dz, dx)
        end = _offset_point(m.end, dz, dx)
        if start == end:
            continue
        new_m = Move(kind=m.kind, start=start, end=end, feed=feed, source_line=m.source_line, cycle=cycle_name)
        if m.kind == "arc" and m.arc_center is not None:
            new_m.arc_center = _offset_point(m.arc_center, dz, dx)
            new_m.arc_ccw = m.arc_ccw
        moves.append(new_m)
    return moves


def _connect_to_final_pass(
    pos: Point,
    shape_moves: list[Move],
    dz: float,
    dx: float,
    feed: float | None,
    source_line: int | None,
    cycle_name: str,
) -> list[Move]:
    """Manual 4.2.1 action 4/4.2.2's final rough-finish pass retraces the
    whole offset contour (from the shape's own opening move onward), not
    just the remainder past the last stepped pass -- so, unlike each
    stepped pass which ends near the offset contour, this needs its own
    rapid back to the offset contour's own start point first (without it,
    the last stepped pass's end and the final pass's start were two
    disconnected points -- an unphysical jump caught by inspecting the
    printed Move list before trusting it, see this module's docstring)."""
    final_pass = _final_contour_pass(shape_moves, dz, dx, feed, cycle_name)
    if not final_pass:
        return final_pass
    contour_start = _offset_point(shape_moves[0].start, dz, dx)
    if pos == contour_start:
        return final_pass
    connector = Move(kind="rapid", start=pos, end=contour_start, source_line=source_line, cycle=cycle_name)
    return [connector, *final_pass]


def expand_g71(
    start: Point,
    shape_moves: list[Move],
    depth: float,
    retract: float,
    du: float,
    dw: float,
    feed: float | None,
    source_line: int | None,
) -> list[Move]:
    """External/internal turning rough cycle: steps parallel to X,
    cutting (feeding) along Z at each step."""
    if depth <= 0:
        raise CannedCycleError("G71 depth of cut (Δd) must be a positive amount")

    sz, sx = start
    points = contour_mod.sample_points(shape_moves)
    if len(points) < 2:
        raise CannedCycleError("G71 shape program produced no motion")
    a_prime_x = points[1][1]
    if a_prime_x == sx:
        raise CannedCycleError("G71's opening (ns) block must move X away from the start point")
    direction = 1.0 if a_prime_x > sx else -1.0
    step = depth * direction

    # Exclude the opening (S->A') positioning move from the intersection
    # lookup: it isn't part of the finished shape, so an X level that
    # falls between S and A' must clamp to A's own depth, not interpolate
    # through a segment that was never a cut (see contour.z_at_x).
    offset_points = [_offset_point(p, dw, du) for p in points[1:]]
    target_x = points[-1][1] + du

    moves: list[Move] = []
    pos = start
    xi = sx
    while True:
        xi_next = xi + step
        if (direction > 0 and xi_next >= target_x) or (direction < 0 and xi_next <= target_x):
            break
        cut_z = contour_mod.z_at_x(offset_points, xi_next)
        leg = _g71_pass(pos, sz, xi_next, cut_z, retract, direction, feed, source_line, "G71")
        moves.extend(leg)
        pos = moves[-1].end
        xi = xi_next

    moves.extend(_connect_to_final_pass(pos, shape_moves, dw, du, feed, source_line, "G71"))
    return moves


def expand_g72(
    start: Point,
    shape_moves: list[Move],
    depth: float,
    retract: float,
    du: float,
    dw: float,
    feed: float | None,
    source_line: int | None,
) -> list[Move]:
    """Facing rough cycle: steps parallel to Z, cutting (feeding) along
    X at each step."""
    if depth <= 0:
        raise CannedCycleError("G72 depth of cut (Δd) must be a positive amount")

    sz, sx = start
    points = contour_mod.sample_points(shape_moves)
    if len(points) < 2:
        raise CannedCycleError("G72 shape program produced no motion")
    a_prime_z = points[1][0]
    if a_prime_z == sz:
        raise CannedCycleError("G72's opening (ns) block must move Z away from the start point")
    direction = 1.0 if a_prime_z > sz else -1.0
    step = depth * direction

    offset_points = [_offset_point(p, dw, du) for p in points[1:]]  # see expand_g71's comment
    target_z = points[-1][0] + dw

    moves: list[Move] = []
    pos = start
    zi = sz
    while True:
        zi_next = zi + step
        if (direction > 0 and zi_next >= target_z) or (direction < 0 and zi_next <= target_z):
            break
        cut_x = contour_mod.x_at_z(offset_points, zi_next)
        leg = _g72_pass(pos, sx, zi_next, cut_x, retract, direction, feed, source_line, "G72")
        moves.extend(leg)
        pos = moves[-1].end
        zi = zi_next

    moves.extend(_connect_to_final_pass(pos, shape_moves, dw, du, feed, source_line, "G72"))
    return moves


def _g71_pass(
    pos: Point,
    clearance_z: float,
    xi: float,
    cut_z: float,
    retract: float,
    direction: float,
    feed,
    source_line,
    cycle_name: str,
) -> list[Move]:
    """One Δd-stepped rough pass for G71: rapid to the new X level (at
    the clearance Z), feed along Z to the contour, retract 45 degrees
    (toward clearance in Z, away from the cut in X), rapid back to the
    clearance Z."""
    moves = []
    p1 = (clearance_z, xi)
    if pos != p1:
        moves.append(Move(kind="rapid", start=pos, end=p1, source_line=source_line, cycle=cycle_name))
    p2 = (cut_z, xi)
    moves.append(Move(kind="linear", start=p1, end=p2, feed=feed, source_line=source_line, cycle=cycle_name))
    retreat = retract / math.sqrt(2)
    z_dir = 1.0 if clearance_z >= cut_z else -1.0
    p3 = (cut_z + z_dir * retreat, xi - direction * retreat)
    if p3 != p2:
        moves.append(Move(kind="rapid", start=p2, end=p3, source_line=source_line, cycle=cycle_name))
    p4 = (clearance_z, p3[1])
    if p4 != p3:
        moves.append(Move(kind="rapid", start=p3, end=p4, source_line=source_line, cycle=cycle_name))
    return moves


def _g72_pass(
    pos: Point,
    clearance_x: float,
    zi: float,
    cut_x: float,
    retract: float,
    direction: float,
    feed,
    source_line,
    cycle_name: str,
) -> list[Move]:
    """G72's axis-swapped mirror of _g71_pass: rapid to the new Z level
    (at the clearance X), feed along X to the contour, retract 45
    degrees (toward clearance in X, away from the cut in Z), rapid back
    to the clearance X."""
    moves = []
    p1 = (zi, clearance_x)
    if pos != p1:
        moves.append(Move(kind="rapid", start=pos, end=p1, source_line=source_line, cycle=cycle_name))
    p2 = (zi, cut_x)
    moves.append(Move(kind="linear", start=p1, end=p2, feed=feed, source_line=source_line, cycle=cycle_name))
    retreat = retract / math.sqrt(2)
    x_dir = 1.0 if clearance_x >= cut_x else -1.0
    p3 = (zi - direction * retreat, cut_x + x_dir * retreat)
    if p3 != p2:
        moves.append(Move(kind="rapid", start=p2, end=p3, source_line=source_line, cycle=cycle_name))
    p4 = (p3[0], clearance_x)
    if p4 != p3:
        moves.append(Move(kind="rapid", start=p3, end=p4, source_line=source_line, cycle=cycle_name))
    return moves
