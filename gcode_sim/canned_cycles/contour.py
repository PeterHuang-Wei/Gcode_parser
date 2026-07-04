"""Shared geometry utilities for the compound canned cycles G70-G73
(docs/PLAN.md section 7, section 13 point 12).

G71/G72/G73 sample the ns~nf "shape program" to get the finishing
contour, then generate rough-cut passes offset from it; G70 later
re-executes the same ns~nf range for the real finish pass. Actually
*running* the shape program (so macro variables/expressions in it still
work) is done by the interpreter itself (Interpreter._trace_shape /
_execute_shape), since doing so here would require importing Interpreter
and create a cycle (interpreter.py already imports this module). This
module only holds the pure-geometry parts: finding the ns/nf block
range, and flattening a traced Move list into a polyline for the
rough-pass intersection math (arcs are *sampled*, not exact, for that
purpose only -- the final G70 finish pass and the displayed path still
use the exact arc geometry, since those just re-run the real Move list).
"""

from ..ast_nodes import NCStatement, Stmt
from ..errors import CannedCycleError
from ..motion import interpolate_arc, interpolate_line
from ..toolpath import Move, Point


def find_range(statements: list, ns: int, nf: int) -> list:
    ns_idx = nf_idx = None
    for i, stmt in enumerate(statements):
        seq = getattr(stmt, "seq_no", None)
        if seq == ns and ns_idx is None:
            ns_idx = i
        if seq == nf:
            nf_idx = i
    if ns_idx is None:
        raise CannedCycleError(f"sequence number N{ns} (P value) not found in the program")
    if nf_idx is None:
        raise CannedCycleError(f"sequence number N{nf} (Q value) not found in the program")
    if nf_idx < ns_idx:
        raise CannedCycleError(f"N{nf} (Q) must be at or after N{ns} (P) in the program")
    return statements[ns_idx : nf_idx + 1]


def sample_points(moves: list[Move], points_per_arc: int = 50) -> list[Point]:
    """Flattens a traced Move list into a single polyline. Used only for
    the rough-pass boundary intersection math in roughing.py/
    pattern_repeat.py -- not for the actual finishing path (G70 re-runs
    the real Move list with exact arcs)."""
    pts: list[Point] = []
    for m in moves:
        if m.kind == "arc" and m.arc_center is not None:
            seg_pts = interpolate_arc(m.start, m.end, m.arc_center, not m.arc_ccw, points_per_arc)
        else:
            seg_pts = interpolate_line(m.start, m.end, 2)
        if pts and pts[-1] == seg_pts[0]:
            seg_pts = seg_pts[1:]
        pts.extend(seg_pts)
    return pts


def z_at_x(points: list[Point], x_level: float) -> float:
    """Given a polyline (z, x) -- the real shape contour, A' to B, with
    the cycle's own opening positioning move already excluded by the
    caller (roughing.py) -- finds the Z value a horizontal rough pass at
    X=x_level must cut down to. Requires the contour's X to be monotonic
    (Type I's own requirement -- manual 4.2.1), so there is at most one
    crossing.

    If x_level lies entirely outside the contour's own X range (still
    possible for levels between the cycle's start point and A', e.g. the
    first several passes on a plain, untapered cylindrical section),
    this returns the contour's *own last point's* Z -- not the nearest
    point's. That range hasn't been reached by the finished shape yet
    at all, at any depth, so the rough pass must cut the *entire* depth
    of the shape at that level, not stop shallow. (A first attempt at
    this clamped to the nearest point instead, which for a plain
    cylindrical turn produced an almost-no-op first pass instead of
    cutting the full length -- caught by hand-tracing a simple example
    before trusting it, see roughing.py's module docstring.)
    """
    if not points:
        raise CannedCycleError("empty contour: nothing to intersect")
    xs = [p[1] for p in points]
    if x_level <= min(xs) or x_level >= max(xs):
        return points[-1][0]
    for (z0, x0), (z1, x1) in zip(points, points[1:]):
        lo, hi = (x0, x1) if x0 <= x1 else (x1, x0)
        if lo - 1e-9 <= x_level <= hi + 1e-9:
            if x1 == x0:
                return z0  # vertical-in-X segment (a pure Z move at this X)
            t = (x_level - x0) / (x1 - x0)
            return z0 + t * (z1 - z0)
    raise CannedCycleError(
        f"X level {x_level} does not intersect the finishing contour "
        "(is the contour monotonic in X as Type I requires?)"
    )


def x_at_z(points: list[Point], z_level: float) -> float:
    """G72's analogue of z_at_x: finds X where a facing pass at Z=z_level
    must cut down to. Same "return the contour's last point, not the
    nearest, when out of range" behavior as z_at_x -- see its docstring."""
    if not points:
        raise CannedCycleError("empty contour: nothing to intersect")
    zs = [p[0] for p in points]
    if z_level <= min(zs) or z_level >= max(zs):
        return points[-1][1]
    for (z0, x0), (z1, x1) in zip(points, points[1:]):
        lo, hi = (z0, z1) if z0 <= z1 else (z1, z0)
        if lo - 1e-9 <= z_level <= hi + 1e-9:
            if z1 == z0:
                return x0
            t = (z_level - z0) / (z1 - z0)
            return x0 + t * (x1 - x0)
    raise CannedCycleError(
        f"Z level {z_level} does not intersect the finishing contour "
        "(is the contour monotonic in Z as G72 Type I requires?)"
    )
