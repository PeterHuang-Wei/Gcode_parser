"""Static plot + continuous-playback animation of a Toolpath.

Per docs/PLAN.md section 9: animation only needs to look continuous (the
tool visibly moving along the path in program order) -- it does not
compute real elapsed time from feed rate, so move-to-move timing is just
an even number of animation frames per unit of path length, not derived
from F.
"""

from __future__ import annotations

import math

import matplotlib.pyplot as plt
from matplotlib import animation as mpl_animation

from .motion import interpolate_arc, interpolate_line
from .toolpath import Move, Point, Toolpath

STYLE = {
    "rapid": {"linestyle": "--", "color": "tab:gray", "linewidth": 1.0},
    "linear": {"linestyle": "-", "color": "tab:blue", "linewidth": 1.5},
    "arc": {"linestyle": "-", "color": "tab:blue", "linewidth": 1.5},
    "thread": {"linestyle": "-", "color": "tab:red", "linewidth": 1.5},
}

# A rapid (G00) traverse is frequently much longer than the actual cutting
# geometry (e.g. a retract all the way out to a clearance position) --
# drawing it at full length visually dominates the plot and makes the
# cutting path (what actually matters for checking a program) hard to
# read. Only the last RAPID_DISPLAY_LENGTH_MM of each rapid is drawn, as
# a visual "approach" marker, not the whole traverse.
RAPID_DISPLAY_LENGTH_MM = 1.0

# The plot's axis range is set explicitly from the *cutting* moves' own
# bounding box (excluding rapids entirely, even their now-truncated
# tick), padded by this margin on every side -- otherwise matplotlib's
# autoscale still includes the full, untruncated rapid *coordinates*
# (only the drawn line is shortened, not the underlying move), which
# would silently widen the view back out around a long rapid traverse.
AXIS_MARGIN_MM = 1.0


def _display_point(p: Point, diameter_programming: bool) -> Point:
    z, x = p
    return (z, x * 2.0 if diameter_programming else x)


def _rapid_display_points(move: Move) -> list[Point]:
    """Truncates a rapid move's drawn line to its last RAPID_DISPLAY_
    LENGTH_MM, leaving the move itself (and the animated tool marker's
    real path, see animate() below) untouched -- this only affects what
    gets drawn."""
    (z0, x0), (z1, x1) = move.start, move.end
    length = math.hypot(z1 - z0, x1 - x0)
    if length <= RAPID_DISPLAY_LENGTH_MM:
        return [move.start, move.end]
    t = (length - RAPID_DISPLAY_LENGTH_MM) / length
    return [(z0 + t * (z1 - z0), x0 + t * (x1 - x0)), (z1, x1)]


def _move_points(move: Move) -> list[Point]:
    if move.kind == "arc" and move.arc_center is not None:
        clockwise = not move.arc_ccw
        return interpolate_arc(move.start, move.end, move.arc_center, clockwise)
    return interpolate_line(move.start, move.end)


def _cutting_bounds(
    toolpath: Toolpath, diameter_programming: bool
) -> tuple[float, float, float, float] | None:
    """Bounding box (z_min, z_max, x_min, x_max), in display coordinates,
    of every *cutting* move (i.e. every kind except "rapid") -- rapids
    are excluded entirely, not just truncated, so a long traverse can
    never widen the view. Returns None if the toolpath has no cutting
    moves at all (nothing to bound)."""
    zs: list[float] = []
    xs: list[float] = []
    for move in toolpath.moves:
        if move.kind == "rapid":
            continue
        for p in _move_points(move):
            z, x = _display_point(p, diameter_programming)
            zs.append(z)
            xs.append(x)
    if not zs:
        return None
    return min(zs), max(zs), min(xs), max(xs)


def plot_static(toolpath: Toolpath, diameter_programming: bool = True, ax=None):
    if ax is None:
        _, ax = plt.subplots()
    seen_kinds: set[str] = set()
    for move in toolpath.moves:
        raw_points = _rapid_display_points(move) if move.kind == "rapid" else _move_points(move)
        pts = [_display_point(p, diameter_programming) for p in raw_points]
        zs = [p[0] for p in pts]
        xs = [p[1] for p in pts]
        style = STYLE[move.kind]
        label = move.kind if move.kind not in seen_kinds else None
        seen_kinds.add(move.kind)
        ax.plot(zs, xs, label=label, **style)
    ax.set_xlabel("Z")
    ax.set_ylabel("X (diameter)" if diameter_programming else "X (radius)")
    bounds = _cutting_bounds(toolpath, diameter_programming)
    if bounds is not None:
        z_min, z_max, x_min, x_max = bounds
        ax.set_xlim(z_min - AXIS_MARGIN_MM, z_max + AXIS_MARGIN_MM)
        ax.set_ylim(x_min - AXIS_MARGIN_MM, x_max + AXIS_MARGIN_MM)
    # adjustable="box" (not "datalim"): keeps the exact cutting-path-based
    # limits set above and instead reshapes the plot's own box to enforce
    # equal aspect, so the window's numeric range stays exactly
    # "cutting path + margin" on both axes rather than being silently
    # widened to satisfy a 1:1 pixel scale (which is what "datalim" was
    # doing -- caught by inspecting the actual axis limits before
    # trusting this).
    ax.set_aspect("equal", adjustable="box")
    if seen_kinds:
        ax.legend()
    return ax


def animate(toolpath: Toolpath, diameter_programming: bool = True, ax=None):
    """Return a FuncAnimation that plays the toolpath back continuously."""
    if ax is None:
        fig, ax = plt.subplots()
    else:
        fig = ax.figure

    plot_static(toolpath, diameter_programming=diameter_programming, ax=ax)

    all_points: list[Point] = []
    for move in toolpath.moves:
        pts = [_display_point(p, diameter_programming) for p in _move_points(move)]
        if all_points and all_points[-1] == pts[0]:
            pts = pts[1:]
        all_points.extend(pts)

    if not all_points:
        all_points = [(0.0, 0.0)]

    (tool_marker,) = ax.plot([], [], marker="o", color="black", markersize=6)

    def update(frame_index: int):
        z, x = all_points[frame_index]
        tool_marker.set_data([z], [x])
        return (tool_marker,)

    return mpl_animation.FuncAnimation(
        fig, update, frames=len(all_points), interval=30, blit=True, repeat=False
    )
