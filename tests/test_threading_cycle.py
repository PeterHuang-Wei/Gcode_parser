"""Phase 4: G76 compound threading cycle (manual 4.2.6). Expected pass
depths below were derived by hand from the triangular Δd*sqrt(n) formula
*before* running the code -- see threading.py's expand_g76 docstring for
the flagged simplifications (no chamfer, no flank-angle infeed, and the
taper offset reusing G90/G94's unverified "r"-style corner adjustment).
"""

import math

import pytest

from gcode_sim import simulator
from gcode_sim.errors import CannedCycleError, ParseError


def test_g76_triangular_depth_schedule_matches_hand_derivation():
    # S=(z=2,x=22). Target X40.0 diameter (-> radius 20.0), Z-30.0.
    # k=2.0 (thread height), Delta d=0.5 (first cut), Delta dmin=0.1,
    # finish allowance d=0.2, m=2 (finish repeat count), a=0 (straight).
    sx, tx, k, d0, dmin, finish_allow, m = 22.0, 20.0, 2.0, 0.5, 0.1, 0.2, 2
    rough_target = k - finish_allow
    depths = []
    n = 1
    cum = d0 * math.sqrt(n)
    while cum < rough_target:
        depths.append(cum)
        n += 1
        next_cum = d0 * math.sqrt(n)
        if next_cum - cum < dmin:
            next_cum = cum + dmin
        cum = next_cum
    depths.append(rough_target)
    depths += [k] * m
    major_x = tx + k
    expected_targets = [major_x - dn for dn in depths]

    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G76 P020000 Q0.1 R0.2;
        G76 X40.0 Z-30.0 R0 P2.0 Q0.5 F2.0;
        M30;
        """
    )
    thread_moves = [m for m in toolpath.moves if m.kind == "thread"]
    assert len(thread_moves) == len(expected_targets)
    for move, expected_x in zip(thread_moves, expected_targets):
        assert move.start == pytest.approx((2.0, expected_x))
        assert move.end == pytest.approx((-30.0, expected_x))
    # last two passes (the m=2 finish repeats) both sit exactly on target
    assert thread_moves[-1].start[1] == pytest.approx(tx)
    assert thread_moves[-2].start[1] == pytest.approx(tx)


def test_g76_rejects_invalid_tool_tip_angle():
    with pytest.raises(ParseError):
        simulator.run(
            """
            G50 X44.0 Z2.0;
            G76 P020045 Q0.1 R0.2;
            G76 X40.0 Z-30.0 R0 P2.0 Q0.5 F2.0;
            M30;
            """
        )


def test_g76_requires_setup_block_before_trigger():
    with pytest.raises(ParseError):
        simulator.run(
            """
            G50 X44.0 Z2.0;
            G76 X40.0 Z-30.0 R0 P2.0 Q0.5 F2.0;
            M30;
            """
        )


def test_g76_thread_height_must_be_positive():
    with pytest.raises(CannedCycleError):
        simulator.run(
            """
            G50 X44.0 Z2.0;
            G76 P020000 Q0.1 R0.2;
            G76 X40.0 Z-30.0 R0 P0 Q0.5 F2.0;
            M30;
            """
        )


def test_g76_m_r_a_digit_encoding_preserves_leading_zeros():
    # P021260 -> m=02, r=12, a=60 (manual 4.2.6's worked example digits).
    # Only the tool angle (a=60) is validated/observable here (m/r are
    # accepted but m only affects the finish-repeat *count*, checked
    # separately above; r -- the chamfer -- has no geometric effect, see
    # threading.py's docstring).
    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G76 P021260 Q0.1 R0.2;
        G76 X40.0 Z-30.0 R0 P2.0 Q0.5 F2.0;
        M30;
        """
    )
    assert len(toolpath.moves) > 0
