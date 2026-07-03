"""G90 (turning cycle) and G94 (facing cycle) -- single-form canned
cycles (manual sections 4.1.1 and 4.1.3).

Both trace a 4-leg rectangular (or, with R, a taper-adjusted
parallelogram) tool path from the start point A: one rapid leg to a
computed corner, one cutting leg to the target A', then two rapid legs
straight back to A. G90's corner leg targets X first (manual 4.1.1);
G94's targets Z first (manual 4.1.3) -- otherwise the two are the same
shape, just with the two axes' roles swapped.

The taper R offset formula (target-axis value adjusted by R at the
first corner) is derived from the manual's structural description
("action1 moves to the A' coordinate, adjusted for the taper amount")
rather than copied from a fully worked numeric example -- the manual
excerpts available did not include one for G90/G94 taper specifically.
This is flagged here and in docs/variables.md as the one geometry
formula in Phase 3 that is derived, not independently cross-checked
against a manual worked example; revisit if a real program's expected
path disagrees.
"""

from ..toolpath import Move, Point


def _leg(kind: str, start: Point, end: Point, feed: float | None, source_line: int | None, cycle: str) -> Move | None:
    if start == end:
        return None
    return Move(kind=kind, start=start, end=end, feed=feed, source_line=source_line, cycle=cycle)


def x_first_cycle(
    start: Point,
    x: float,
    z: float,
    r: float,
    feed: float | None,
    source_line: int | None,
    cycle_name: str,
    leg2_kind: str,
) -> list[Move]:
    """Shared 4-leg shape for G90 (leg2_kind="linear") and G92
    (leg2_kind="thread"): rapid to the (taper-adjusted) X corner, cut to
    (z, x), then two rapid legs straight back to the start point."""
    sz, sx = start
    corner_x = x + r
    legs = [
        ("rapid", start, (sz, corner_x), None),
        (leg2_kind, (sz, corner_x), (z, x), feed),
        ("rapid", (z, x), (z, sx), None),
        ("rapid", (z, sx), start, None),
    ]
    moves = []
    for kind, a, b, f in legs:
        m = _leg(kind, a, b, f, source_line, cycle_name)
        if m:
            moves.append(m)
    return moves


def expand_g90(start: Point, x: float, z: float, r: float, feed: float | None, source_line: int | None) -> list[Move]:
    return x_first_cycle(start, x, z, r, feed, source_line, "G90", "linear")


def expand_g94(start: Point, x: float, z: float, r: float, feed: float | None, source_line: int | None) -> list[Move]:
    """Facing cycle: rapid to the (taper-adjusted) Z corner, cut to
    (z, x), then two rapid legs straight back to the start point."""
    sz, sx = start
    corner_z = z + r
    legs = [
        ("rapid", start, (corner_z, sx), None),
        ("linear", (corner_z, sx), (z, x), feed),
        ("rapid", (z, x), (sz, x), None),
        ("rapid", (sz, x), start, None),
    ]
    moves = []
    for kind, a, b, f in legs:
        m = _leg(kind, a, b, f, source_line, "G94")
        if m:
            moves.append(m)
    return moves
