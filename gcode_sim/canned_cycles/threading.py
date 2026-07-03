"""G92 (thread cutting cycle, manual 4.1.2). G32 (direct thread cutting,
manual 3.1) is handled directly in interpreter.py alongside G00/G01/G02/
G03, since it is not a 4-leg cycle -- it is a single motion command
whose end point is given directly (like G01), just marked kind="thread".

Straight/taper/spiral thread distinctions in the manual only matter for
the real 3D helical path (which depends on spindle angle/pitch); since
this simulator only tracks the ZX-plane path and does not model
rotation, all three forms project to the same thing here: a straight
line from start to end. Q (multi-start thread angle offset) likewise
only affects *when* in the spindle rotation cutting begins, not the
Z-X shape, so it is accepted but has no geometric effect (recorded
nowhere, matching the "no consumer" treatment of G96/G97/G98/G99 --
docs/PLAN.md section 13.7). The end-of-thread chamfer described in the
manual is not modeled (whether it happens at all "depends on a
machine-side signal" per the manual, so many machines don't chamfer by
default either).
"""

from ..toolpath import Point
from .turning import x_first_cycle


def expand_g92(start: Point, x: float, z: float, r: float, feed: float | None, source_line: int | None) -> list:
    return x_first_cycle(start, x, z, r, feed, source_line, "G92", "thread")
