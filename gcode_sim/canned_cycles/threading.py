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

import math

from ..errors import CannedCycleError
from ..toolpath import Move, Point
from .turning import x_first_cycle


def expand_g92(start: Point, x: float, z: float, r: float, feed: float | None, source_line: int | None) -> list:
    return x_first_cycle(start, x, z, r, feed, source_line, "G92", "thread")


def expand_g76(
    start: Point,
    target: Point,
    taper_i: float,
    thread_height: float,
    first_cut_depth: float,
    min_cut_depth: float,
    finish_allowance: float,
    finish_repeat_count: int,
    lead: float | None,
    source_line: int | None,
) -> list[Move]:
    """G76 (compound threading cycle, manual 4.2.6): repeated G92-style
    threading passes (see x_first_cycle) at progressively increasing
    depth, each pass reusing the exact same 4-leg rapid/thread-cut/rapid/
    rapid pattern already used and tested for G90/G92 -- only the target
    X gets deeper each pass. The taper offset "i" is applied the same way
    G90/G94's "r" is (an offset at the entry corner) -- not independently
    verified against a manual worked example, like that formula (see
    turning.py's module docstring); flagged here for the same reason.

    Pass depths (measured as a radius reduction from the major diameter
    down toward the minor diameter, target[1]): a triangular schedule
    Δd*sqrt(n), n=1,2,..., stopping once the rough target (thread_height
    minus finish_allowance) is reached, with each increment floored at
    min_cut_depth (Δd_min) so passes don't get arbitrarily thin near the
    end. After the rough schedule, finish_repeat_count (m) additional
    passes repeat at the *full* thread_height depth (the first of these
    removes the remaining finish_allowance stock; the rest are identical
    spring/polishing repeats at that same final depth).

    Like G92, the end-of-thread chamfer and tool-tip-angle-based flank
    infeed are not modeled (see threading.py's module docstring for G92's
    chamfer note) -- every pass infeeds straight in X, not along one
    flank of the V profile.
    """
    if thread_height <= 0:
        raise CannedCycleError("G76 thread height (k, the trigger block's P) must be a positive amount")
    if first_cut_depth <= 0:
        raise CannedCycleError("G76 first cut depth (Δd, the trigger block's Q) must be a positive amount")
    if finish_repeat_count < 0:
        raise CannedCycleError("G76 finish repeat count (m) must not be negative")

    tz, tx = target
    major_x = tx + thread_height
    rough_target_depth = max(thread_height - finish_allowance, 0.0)

    depths: list[float] = []
    n = 1
    cum = first_cut_depth * math.sqrt(n)
    while cum < rough_target_depth:
        depths.append(cum)
        n += 1
        next_cum = first_cut_depth * math.sqrt(n)
        if next_cum - cum < min_cut_depth:
            next_cum = cum + min_cut_depth
        cum = next_cum
    depths.append(rough_target_depth)
    depths.extend([thread_height] * finish_repeat_count)

    moves: list[Move] = []
    for d_n in depths:
        pass_x = major_x - d_n
        moves.extend(x_first_cycle(start, pass_x, tz, taper_i, lead, source_line, "G76", "thread"))
    return moves
