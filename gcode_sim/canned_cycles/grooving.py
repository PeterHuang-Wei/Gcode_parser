"""G74 (end-face peck drilling / grooving, manual 4.2.4) and G75
(external/internal peck grooving, manual 4.2.5) -- compound canned
cycles.

Both are chip-breaking peck cycles: cut a fixed depth increment, retract
a small amount to break the chip, then continue past the retract point to
the next depth increment, repeating until the target depth is reached,
then fully retract to the clearance position. G74 pecks along Z (with an
optional periodic shift in X, for cutting several parallel face grooves
in one cycle); G75 pecks along X (with an optional periodic shift in Z,
for several parallel grooves along the part's length) -- the two
functions below are axis-swapped mirrors of each other, matching G71/G72.

No sequence-number shape program is involved (unlike G70-G73) -- the
target point and step amounts are given directly on the cycle's own
trigger block, so there is nothing here to trace via contour.py.

Simplifications, flagged for extra scrutiny like G71/G72/G73's derived
algorithms:
- This simulator does not model the raw "integer, no decimal point,
  microns" encoding some real FANUC controls use for the Δi/Δk (P/Q)
  addresses; here they're read as ordinary decimal lengths like every
  other address in this parser (see docs/PLAN.md section 13's units.py
  note -- this is a deliberate, documented simplification, not an
  oversight).
- The manual's trigger-block "Δd" (relief amount at the very bottom) is
  treated as the same value as the setup block's "e" (retract amount
  used between pecks) -- this simulator does not distinguish the two,
  using a single retract/relief amount for both roles.
"""

from ..errors import CannedCycleError
from ..toolpath import Move, Point


def _peck_depths(sz: float, tz: float, peck: float) -> list[float]:
    if peck <= 0:
        raise CannedCycleError("peck depth per stroke must be a positive amount")
    if tz == sz:
        raise CannedCycleError("peck target must differ from the start position")
    z_dir = 1.0 if tz > sz else -1.0
    depths = []
    zi = sz
    while True:
        zi_next = zi + peck * z_dir
        if (z_dir > 0 and zi_next >= tz) or (z_dir < 0 and zi_next <= tz):
            zi_next = tz
        depths.append(zi_next)
        if zi_next == tz:
            break
        zi = zi_next
    return depths


def _shift_columns(sx: float, tx: float, shift: float) -> list[float]:
    if shift == 0.0 or tx == sx:
        return [tx]
    x_dir = 1.0 if tx > sx else -1.0
    columns = []
    xi = sx
    while True:
        columns.append(xi)
        if xi == tx:
            break
        xi_next = xi + abs(shift) * x_dir
        if (x_dir > 0 and xi_next >= tx) or (x_dir < 0 and xi_next <= tx):
            xi_next = tx
        xi = xi_next
    return columns


def _g74_column(
    pos: Point,
    clearance_z: float,
    xi: float,
    target_z: float,
    peck_z: float,
    retract: float,
    feed: float | None,
    source_line: int | None,
) -> list[Move]:
    """One X-column's worth of Z pecking for G74 (rapid to the column at
    clearance Z, then feed-retract-feed... down to target_z, then rapid
    fully back out to clearance Z)."""
    moves: list[Move] = []
    p0 = (clearance_z, xi)
    if pos != p0:
        moves.append(Move(kind="rapid", start=pos, end=p0, source_line=source_line, cycle="G74"))
    z_dir = 1.0 if target_z > clearance_z else -1.0
    depths = _peck_depths(clearance_z, target_z, peck_z)
    cur = p0
    for zn in depths:
        nxt = (zn, xi)
        moves.append(Move(kind="linear", start=cur, end=nxt, feed=feed, source_line=source_line, cycle="G74"))
        if zn != target_z:
            retracted = (zn - z_dir * retract, xi)
            moves.append(Move(kind="rapid", start=nxt, end=retracted, source_line=source_line, cycle="G74"))
            cur = retracted
        else:
            cur = nxt
    moves.append(Move(kind="rapid", start=cur, end=p0, source_line=source_line, cycle="G74"))
    return moves


def expand_g74(
    start: Point,
    target: Point,
    shift_x: float,
    peck_z: float,
    retract: float,
    feed: float | None,
    source_line: int | None,
) -> list[Move]:
    """Face peck-drilling/grooving: pecks along Z at each of one or more
    X columns, shifting by shift_x (Δi) between columns."""
    sz, sx = start
    tz, tx = target
    columns = _shift_columns(sx, tx, shift_x)
    moves: list[Move] = []
    pos = start
    for xi in columns:
        leg = _g74_column(pos, sz, xi, tz, peck_z, retract, feed, source_line)
        moves.extend(leg)
        pos = moves[-1].end
    return moves


def _g75_column(
    pos: Point,
    clearance_x: float,
    zi: float,
    target_x: float,
    peck_x: float,
    retract: float,
    feed: float | None,
    source_line: int | None,
) -> list[Move]:
    """One Z-column's worth of X pecking for G75 -- G74's axis-swapped
    mirror (rapid to the column at clearance X, then feed-retract-feed...
    to target_x, then rapid fully back out to clearance X)."""
    moves: list[Move] = []
    p0 = (zi, clearance_x)
    if pos != p0:
        moves.append(Move(kind="rapid", start=pos, end=p0, source_line=source_line, cycle="G75"))
    x_dir = 1.0 if target_x > clearance_x else -1.0
    depths = _peck_depths(clearance_x, target_x, peck_x)
    cur = p0
    for xn in depths:
        nxt = (zi, xn)
        moves.append(Move(kind="linear", start=cur, end=nxt, feed=feed, source_line=source_line, cycle="G75"))
        if xn != target_x:
            retracted = (zi, xn - x_dir * retract)
            moves.append(Move(kind="rapid", start=nxt, end=retracted, source_line=source_line, cycle="G75"))
            cur = retracted
        else:
            cur = nxt
    moves.append(Move(kind="rapid", start=cur, end=p0, source_line=source_line, cycle="G75"))
    return moves


def expand_g75(
    start: Point,
    target: Point,
    peck_x: float,
    shift_z: float,
    retract: float,
    feed: float | None,
    source_line: int | None,
) -> list[Move]:
    """External/internal peck grooving: pecks along X at each of one or
    more Z columns, shifting by shift_z (Δk) between columns -- G74's
    axis-swapped mirror."""
    sz, sx = start
    tz, tx = target
    columns = _shift_columns(sz, tz, shift_z)
    moves: list[Move] = []
    pos = start
    for zi in columns:
        leg = _g75_column(pos, sx, zi, tx, peck_x, retract, feed, source_line)
        moves.extend(leg)
        pos = moves[-1].end
    return moves
