"""Pure geometry helpers: arc-center solving and point-list interpolation.

These do not touch interpreter state -- they only turn (start, end,
center/radius, direction) into points, for use by the interpreter (to
validate/compute an arc's center) and by viz_matplotlib.py (to draw or
animate a smooth curve instead of a straight chord).
"""

import math

from .errors import MotionError
from .toolpath import Point


def arc_center_from_radius(start: Point, end: Point, radius: float, clockwise: bool) -> Point:
    """Solve for the arc center given a signed radius (FANUC R-format).

    Positive radius selects the <=180 degree arc; negative radius selects
    the >180 degree (reflex) arc. Follows the same convention used by
    grbl/LinuxCNC for R-format arcs.
    """
    sz, sx = start
    ez, ex = end
    dz, dx = ez - sz, ex - sx
    d = math.hypot(dz, dx)
    if d == 0:
        raise MotionError("degenerate arc: start and end points are identical")
    r = abs(radius)
    if r * 2 < d - 1e-9:
        raise MotionError(
            f"arc radius {radius} too small for chord length {d} between {start} and {end}"
        )
    h = math.sqrt(max(r * r - (d / 2) ** 2, 0.0))
    mz, mx = (sz + ez) / 2.0, (sx + ex) / 2.0
    uz, ux = -dx / d, dz / d  # unit vector perpendicular to start->end
    # Verified directly (not from a half-remembered reference algorithm --
    # see the derivation in docs/PLAN.md testing-methodology notes): with
    # our angle convention atan2(dx, dz) (increasing = counterclockwise),
    # a clockwise arc with a non-negative radius (the <=180 degree arc)
    # needs the *negative*-sign center, and vice versa.
    positive_sign = ((not clockwise) and radius >= 0) or (clockwise and radius < 0)
    sign = 1.0 if positive_sign else -1.0
    return (mz + sign * h * uz, mx + sign * h * ux)


def arc_center_from_offset(start: Point, k: float, i: float) -> Point:
    """Arc center given incremental (I, K) offsets from the start point.

    K is the Z-axis component, I is the X-axis component (radius units).
    """
    sz, sx = start
    return (sz + k, sx + i)


def interpolate_line(start: Point, end: Point, num_points: int = 2) -> list[Point]:
    num_points = max(num_points, 2)
    sz, sx = start
    ez, ex = end
    return [
        (sz + (ez - sz) * t / (num_points - 1), sx + (ex - sx) * t / (num_points - 1))
        for t in range(num_points)
    ]


def interpolate_arc(
    start: Point, end: Point, center: Point, clockwise: bool, num_points: int = 50
) -> list[Point]:
    cz, cx = center
    sz, sx = start
    ez, ex = end
    start_angle = math.atan2(sx - cx, sz - cz)
    end_angle = math.atan2(ex - cx, ez - cz)
    radius = math.hypot(sz - cz, sx - cx)

    if clockwise:
        while end_angle > start_angle:
            end_angle -= 2 * math.pi
    else:
        while end_angle < start_angle:
            end_angle += 2 * math.pi

    num_points = max(num_points, 2)
    points = []
    for step in range(num_points):
        t = step / (num_points - 1)
        angle = start_angle + (end_angle - start_angle) * t
        points.append((cz + radius * math.cos(angle), cx + radius * math.sin(angle)))
    return points
