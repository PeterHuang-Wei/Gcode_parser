"""Static plot + continuous-playback animation of a Toolpath.

Per docs/PLAN.md section 9: animation only needs to look continuous (the
tool visibly moving along the path in program order) -- it does not
compute real elapsed time from feed rate, so move-to-move timing is just
an even number of animation frames per unit of path length, not derived
from F.
"""

from __future__ import annotations

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


def _display_point(p: Point, diameter_programming: bool) -> Point:
    z, x = p
    return (z, x * 2.0 if diameter_programming else x)


def _move_points(move: Move) -> list[Point]:
    if move.kind == "arc" and move.arc_center is not None:
        clockwise = not move.arc_ccw
        return interpolate_arc(move.start, move.end, move.arc_center, clockwise)
    return interpolate_line(move.start, move.end)


def plot_static(toolpath: Toolpath, diameter_programming: bool = True, ax=None):
    if ax is None:
        _, ax = plt.subplots()
    seen_kinds: set[str] = set()
    for move in toolpath.moves:
        pts = [_display_point(p, diameter_programming) for p in _move_points(move)]
        zs = [p[0] for p in pts]
        xs = [p[1] for p in pts]
        style = STYLE[move.kind]
        label = move.kind if move.kind not in seen_kinds else None
        seen_kinds.add(move.kind)
        ax.plot(zs, xs, label=label, **style)
    ax.set_xlabel("Z")
    ax.set_ylabel("X (diameter)" if diameter_programming else "X (radius)")
    ax.set_aspect("equal", adjustable="datalim")
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
