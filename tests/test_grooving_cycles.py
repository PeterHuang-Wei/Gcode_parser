"""Phase 4: compound canned cycles G74/G75 (manual 4.2.4/4.2.5,
docs/PLAN.md section 7). Expected coordinates below were derived by hand
from the peck/shift arithmetic *before* running the code -- see
grooving.py's module docstring for the flagged simplifications (Δi/Δk
read as ordinary decimals rather than the raw microns-without-decimal-
point encoding some real controls use, and a single retract/relief value
shared between the setup block's "e" and the trigger block's "Δd").
"""

import pytest

from gcode_sim import simulator
from gcode_sim.errors import CannedCycleError, ParseError

RETRACT = 0.5


def test_g74_single_column_peck_drilling():
    # S=(z=2,x=22). Target Z=-10 (no X shift: P0). Delta k=3.0, e=0.5.
    # Peck depths (z_dir=-1): 2 -> -1 -> -4 -> -7 -> -10 (clamped).
    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G74 R0.5;
        G74 Z-10.0 P0 Q3.0 F0.2;
        M30;
        """
    )
    moves = toolpath.moves
    assert [m.kind for m in moves] == [
        "linear", "rapid", "linear", "rapid", "linear", "rapid", "linear", "rapid",
    ]
    depths = [-1.0, -4.0, -7.0, -10.0]
    cur = 2.0
    idx = 0
    for i, zn in enumerate(depths):
        cut = moves[idx]
        assert cut.start == pytest.approx((cur, 22.0))
        assert cut.end == pytest.approx((zn, 22.0))
        idx += 1
        if zn != -10.0:
            retreat = moves[idx]
            assert retreat.kind == "rapid"
            assert retreat.end == pytest.approx((zn + RETRACT, 22.0))
            cur = zn + RETRACT
            idx += 1
    final_retract = moves[-1]
    assert final_retract.kind == "rapid"
    assert final_retract.end == pytest.approx((2.0, 22.0))  # back to clearance Z


def test_g74_shifts_x_between_columns():
    # S=(z=2,x=22). Target X18.0 diameter (-> radius 9.0), Z-8.0.
    # Delta i (P) = 2.0 radius, Delta k (Q) = 5.0 radius, e=0.3.
    # X columns step from 22 down to 9.0 by 2.0 each: 22,20,18,...,10,
    # then clamp to the 9.0 target (a 1.0-wide last step) -- 8 columns.
    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G74 R0.3;
        G74 X18.0 Z-8.0 P2.0 Q5.0 F0.2;
        M30;
        """
    )
    moves = toolpath.moves
    expected_columns = [22.0, 20.0, 18.0, 16.0, 14.0, 12.0, 10.0, 9.0]
    xs_seen = []
    for m in moves:
        if m.kind == "linear":
            xs_seen.append(m.start[1])
    # each column cuts down through 2 peck depths (-3.0, -8.0 given
    # Delta k=5.0 from Z=2 to Z=-8), so each X appears twice in a row.
    assert xs_seen == [x for x in expected_columns for _ in range(2)]
    assert moves[-1].end == pytest.approx((2.0, 9.0))  # final retract at the last column


def test_g75_pecks_along_x_shifting_z_between_columns():
    # S=(z=2,x=22). Target X14.0 diameter (-> radius 7.0), Z-8.0.
    # Delta i (P) = 4.0 radius (X peck depth), Delta k (Q) = 3.0 (Z shift).
    # Z columns step from 2 down to -8 by 3.0 each, clamped: 2,-1,-4,-7,-8.
    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G75 R0.3;
        G75 X14.0 Z-8.0 P4.0 Q3.0 F0.2;
        M30;
        """
    )
    moves = toolpath.moves
    expected_columns = [2.0, -1.0, -4.0, -7.0, -8.0]
    zs_seen = []
    for m in moves:
        if m.kind == "linear":
            zs_seen.append(m.start[0])
    # each column pecks through 4 X depths (22->18->14->10->7.0 given
    # Delta i=4.0 radius from X=22 to X=7.0), so each Z appears 4 times.
    assert zs_seen == [z for z in expected_columns for _ in range(4)]
    assert moves[-1].end == pytest.approx((-8.0, 22.0))  # final retract at the last column


def test_g74_e_defaults_to_zero_without_a_setup_block():
    # Unlike G71/G72/G73 (which require their own setup block first),
    # G74/G75's retract "e" simply defaults to 0.0 (an aggressive but
    # valid retract) if the "G74 R_;" setup block is omitted -- no error.
    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G74 Z-5.0 P0 Q2.0 F0.2;
        M30;
        """
    )
    assert len(toolpath.moves) > 0


def test_g74_target_must_differ_from_start():
    with pytest.raises(CannedCycleError):
        simulator.run(
            """
            G50 X44.0 Z2.0;
            G74 R0.5;
            G74 Z2.0 P0 Q3.0 F0.2;
            M30;
            """
        )
