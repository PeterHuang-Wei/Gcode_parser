"""Phase 4: compound canned cycles G70/G71/G72/G73 (manual 4.2,
docs/PLAN.md section 7 / 13.12). Expected coordinates below were derived
by hand from the shape geometry *before* running the code -- see
roughing.py's module docstring and contour.py's z_at_x/x_at_z docstrings
for the two bugs this hand-tracing actually caught (opening-move leaking
into the intersection lookup, and out-of-range levels clamping to the
nearest point instead of the contour's own last/deepest point).

Both G71/G72 worked examples below use a shape program with a *constant*
step-axis level (a plain cylindrical turn for G71, a plain flat face for
G72), which is deliberately the simplest case where every out-of-range
rough pass must cut the *entire* remaining depth in one go -- exactly the
behavior that was wrong before the fix.
"""

import math
from pathlib import Path

import pytest

from gcode_sim import simulator
from gcode_sim.errors import CannedCycleError, ParseError

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

RETREAT = 1.0 / math.sqrt(2)


def test_g71_roughs_a_plain_cylindrical_turn():
    # S=(z=2,x=22). Shape: N10 G00 X20.0 (diameter -> A'=(2,10), radius),
    # N20 G01 Z-30.0 (-> B=(-30,10)). Delta d=2.0 (radius, U on the
    # depth-setting block is *not* diametric per the manual), e=1.0,
    # finishing allowance Delta u=1.0 diameter (=0.5 radius), Delta w=0.5.
    #
    # N10/N20 are also ordinary blocks in the main program, so after the
    # G71 cycle finishes, normal sequential execution falls through and
    # runs them again for real (this matches real FANUC controls: ns/nf
    # are plain sequence-number labels, not a skip range -- the file's
    # own next blocks are N10/N20, so they execute once more, at the
    # *real* (non-offset) contour, before any G70 statement even appears).
    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G71 U2.0 R1.0;
        G71 P10 Q20 U1.0 W0.5 F0.2;
        N10 G00 X20.0;
        N20 G01 Z-30.0 F0.15;
        M30;
        """
    )
    moves = toolpath.moves
    # direction is -1 (A'.x=10 < S.x=22); step=-2.0; target_x=10.5 (offset).
    # xi steps 22->20->18->16->14->12 (next=10 <= 10.5 stops): 5 rough passes
    # (4 legs each) + 1 connector rapid + final contour pass (2 legs) +
    # the N10/N20 fallthrough re-execution (2 legs) = 5*4 + 1 + 2 + 2.
    assert len(moves) == 5 * 4 + 1 + 2 + 2

    # Every rough pass's step level lies beyond the offset contour's own
    # (constant) x=10.5, so each must cut the *entire* depth down to the
    # contour's own last point (z=-29.5), not stop shallow.
    for i, xi in enumerate([20.0, 18.0, 16.0, 14.0, 12.0]):
        p0, p1, p2, p3 = moves[4 * i : 4 * i + 4]
        assert p0.kind == "rapid" and p0.end == pytest.approx((2.0, xi))
        assert p1.kind == "linear" and p1.start == pytest.approx((2.0, xi))
        assert p1.end == pytest.approx((-29.5, xi))
        assert p2.kind == "rapid"
        assert p2.end == pytest.approx((-29.5 + RETREAT, xi + RETREAT))
        assert p3.kind == "rapid"
        assert p3.end == pytest.approx((2.0, xi + RETREAT))

    connector, final1, final2 = moves[20], moves[21], moves[22]
    assert connector.kind == "rapid"
    assert connector.start == pytest.approx((2.0, 12.0 + RETREAT))
    assert connector.end == pytest.approx((2.5, 22.5))  # back to the offset contour's own start
    assert final1.start == pytest.approx((2.5, 22.5))
    assert final1.end == pytest.approx((2.5, 10.5))
    assert final2.start == pytest.approx((2.5, 10.5))
    assert final2.end == pytest.approx((-29.5, 10.5))

    fallthrough1, fallthrough2 = moves[-2], moves[-1]
    assert fallthrough1.cycle is None and fallthrough1.end == pytest.approx((-29.5, 10.0))
    assert fallthrough2.cycle is None and fallthrough2.end == pytest.approx((-30.0, 10.0))


def test_g71_then_g70_reruns_the_shape_program_for_the_real_finish_pass():
    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G71 U2.0 R1.0;
        G71 P10 Q20 U1.0 W0.5 F0.2;
        N10 G00 X20.0;
        N20 G01 Z-30.0 F0.15;
        G70 P10 Q20;
        M30;
        """
    )
    moves = toolpath.moves
    # G70 P10 Q20 is a *third* traversal of N10/N20 in this program (the
    # G71 cycle's own final contour pass, then the normal-flow fallthrough
    # into N10/N20, then G70 explicitly) -- redundant-looking but this is
    # how real FANUC programs of this shape actually run; see the
    # fallthrough note in test_g71_roughs_a_plain_cylindrical_turn.
    g70_moves = moves[-2:]
    assert g70_moves[0].kind == "rapid"
    assert g70_moves[0].end == pytest.approx((g70_moves[0].start[0], 10.0))
    assert g70_moves[1].kind == "linear"
    assert g70_moves[1].end == pytest.approx((-30.0, 10.0))


def test_g72_faces_a_plain_flat_taper_stock():
    # S=(z=2,x=22). Shape: N10 G00 Z-2.0 (-> A'=(-2,22)), N20 G01 X30.0
    # Z-20.0 (diameter -> B=(-20,15), radius). Delta d=2.0 (radius, on the
    # *W* address -- G72's depth-setting block mirrors G71's but on its own
    # step axis), e=1.0, Delta u=0.5 diameter (=0.25 radius), Delta w=0.3.
    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G72 W2.0 R1.0;
        G72 P10 Q20 U0.5 W0.3 F0.2;
        N10 G00 Z-2.0;
        N20 G01 X30.0 Z-20.0 F0.15;
        M30;
        """
    )
    moves = toolpath.moves
    # direction is -1 (A'.z=-2 < S.z=2); step=-2.0; target_z=-19.7 (offset).
    # zi steps 2->0 first: z=0 is beyond A'.z=-2, i.e. still outside the
    # shape's own Z range entirely, so it must cut the full remaining
    # radius down to the contour's own last point (x=15.25), not stop
    # shallow -- same out-of-range behavior as the G71 case above.
    first_pass = moves[:4]
    assert first_pass[0].kind == "rapid" and first_pass[0].end == pytest.approx((0.0, 22.0))
    assert first_pass[1].kind == "linear" and first_pass[1].end == pytest.approx((0.0, 15.25))

    connector, final_leg1, final_leg2 = [m for m in moves if m.cycle == "G72"][-3:]
    assert connector.kind == "rapid"
    assert connector.end == pytest.approx((2.3, 22.25))  # back to the offset contour's own start
    assert final_leg1.start == pytest.approx((2.3, 22.25))
    assert final_leg1.end == pytest.approx((-1.7, 22.25))
    assert final_leg2.end == pytest.approx((-19.7, 15.25))


def test_g72_needs_its_own_w_address_for_depth_not_u():
    # A prior bug shared _set_g7x_params's "U" lookup between G71 and G72;
    # G72's depth-of-cut block uses W (it steps parallel to Z), so a bare
    # "G72 W2.0 R1.0;" must be enough -- no U required at this stage.
    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G72 W2.0 R1.0;
        G72 P10 Q20 F0.2;
        N10 G00 Z-2.0;
        N20 G01 X30.0 Z-20.0 F0.15;
        M30;
        """
    )
    assert len(toolpath.moves) > 0


def test_g71_opening_block_must_move_x_away_from_start():
    with pytest.raises(CannedCycleError):
        simulator.run(
            """
            G50 X44.0 Z2.0;
            G71 U2.0 R1.0;
            G71 P10 Q20 U1.0 W0.5 F0.2;
            N10 G00 Z0.0;
            N20 G01 Z-30.0 F0.15;
            M30;
            """
        )


def test_g71_requires_depth_set_before_p_q_block():
    with pytest.raises(ParseError):
        simulator.run(
            """
            G50 X44.0 Z2.0;
            G71 P10 Q20 U1.0 W0.5 F0.2;
            N10 G00 X20.0;
            N20 G01 Z-30.0 F0.15;
            M30;
            """
        )


def test_g73_repeats_the_whole_contour_with_decreasing_parallel_offsets():
    # S=(z=2,x=22). Shape: N10 G00 X10.0 (diameter -> A'=(2,5), radius),
    # N20 G01 Z-30.0 (-> B=(-30,5)). Delta i=4.0 (radius, X total
    # retreat), Delta k=2.0 (Z total retreat), d=3 divisions. Delta
    # u=1.0 diameter (=0.5 radius), Delta w=0.5.
    #
    # Pass n's offset is (dw + k*(d-n)/d, du + i*(d-n)/d):
    #   n=1: frac=2/3 -> offset=(0.5+2*2/3, 0.5+4*2/3)=(1.8333..., 3.1666...)
    #   n=2: frac=1/3 -> offset=(0.5+2/3,   0.5+4/3)  =(1.1666..., 1.8333...)
    #   n=3: frac=0   -> offset=(0.5, 0.5)  -- just the finishing allowance
    # Each pass is the *entire* shape (both moves) shifted by that amount.
    toolpath = simulator.run(
        """
        G50 X44.0 Z2.0;
        G73 U4.0 W2.0 R3;
        G73 P10 Q20 U1.0 W0.5 F0.2;
        N10 G00 X10.0;
        N20 G01 Z-30.0 F0.15;
        M30;
        """
    )
    moves = [m for m in toolpath.moves if m.cycle == "G73"]
    assert len(moves) == 3 * 3  # 3 passes x (connector rapid + 2 shifted shape legs)

    expected_offsets = [
        (0.5 + 2.0 * 2 / 3, 0.5 + 4.0 * 2 / 3),
        (0.5 + 2.0 * 1 / 3, 0.5 + 4.0 * 1 / 3),
        (0.5, 0.5),
    ]
    for i, (dz, dx) in enumerate(expected_offsets):
        connector, leg1, leg2 = moves[3 * i : 3 * i + 3]
        assert connector.kind == "rapid"
        assert connector.end == pytest.approx((2.0 + dz, 22.0 + dx))
        assert leg1.kind == "rapid"  # shape's own opening move (N10 G00) stays rapid
        assert leg1.start == pytest.approx((2.0 + dz, 22.0 + dx))
        assert leg1.end == pytest.approx((2.0 + dz, 5.0 + dx))
        assert leg2.kind == "linear"
        assert leg2.start == pytest.approx((2.0 + dz, 5.0 + dx))
        assert leg2.end == pytest.approx((-30.0 + dz, 5.0 + dx))


def test_g73_requires_params_set_before_p_q_block():
    with pytest.raises(ParseError):
        simulator.run(
            """
            G50 X44.0 Z2.0;
            G73 P10 Q20 U1.0 W0.5 F0.2;
            N10 G00 X10.0;
            N20 G01 Z-30.0 F0.15;
            M30;
            """
        )


def test_g73_division_count_must_be_positive():
    with pytest.raises(CannedCycleError):
        simulator.run(
            """
            G50 X44.0 Z2.0;
            G73 U4.0 W2.0 R0;
            G73 P10 Q20 U1.0 W0.5 F0.2;
            N10 G00 X10.0;
            N20 G01 Z-30.0 F0.15;
            M30;
            """
        )
