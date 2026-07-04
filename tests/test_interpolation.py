import math
from pathlib import Path

import pytest

from gcode_sim import simulator
from gcode_sim.errors import UnsupportedFeatureError

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_g50_sets_initial_position_then_rapid_move():
    toolpath = simulator.run(
        """
        G50 X50.0 Z100.0;
        G00 X0.0 Z10.0;
        M30;
        """
    )
    assert len(toolpath.moves) == 1
    move = toolpath.moves[0]
    assert move.kind == "rapid"
    assert move.start == pytest.approx((100.0, 25.0))  # G50: Z100.0, X50.0(diameter)/2
    assert move.end == pytest.approx((10.0, 0.0))


def test_modal_g_code_carries_over_without_repeating_g_word():
    toolpath = simulator.run(
        """
        G50 X50.0 Z100.0;
        G01 Z0.0 F0.3;
        X20.0 Z-10.0;
        M30;
        """
    )
    assert len(toolpath.moves) == 2
    first, second = toolpath.moves
    assert first.kind == "linear"
    assert first.end == pytest.approx((0.0, 25.0))
    assert second.kind == "linear"  # no G-word in this block, reuses G01
    assert second.start == pytest.approx((0.0, 25.0))
    assert second.end == pytest.approx((-10.0, 10.0))  # X20.0 diameter -> radius 10.0


def test_arc_center_computed_from_radius():
    toolpath = simulator.run(
        """
        G50 X40.0 Z-20.0;
        G01 X20.0 Z-10.0;
        G02 X30.0 Z-15.0 R5.0;
        M30;
        """
    )
    arc_move = toolpath.moves[-1]
    assert arc_move.kind == "arc"
    assert arc_move.start == pytest.approx((-10.0, 10.0))
    assert arc_move.end == pytest.approx((-15.0, 15.0))
    # Independently verified (see docs/PLAN.md testing notes): of the two
    # geometrically valid centers, (-10.0, 15.0) is the one for which a
    # clockwise sweep from start to end is <=180 degrees, matching R5.0
    # (positive radius = short arc). The other candidate, (-15.0, 10.0),
    # is equidistant too but requires a 270-degree clockwise sweep -- an
    # earlier version of this test asserted that wrong center because it
    # was hand-derived from the same (buggy) formula being tested.
    assert arc_move.arc_center == pytest.approx((-10.0, 15.0))
    cz, cx = arc_move.arc_center
    assert math.hypot(arc_move.start[0] - cz, arc_move.start[1] - cx) == pytest.approx(5.0)
    assert math.hypot(arc_move.end[0] - cz, arc_move.end[1] - cx) == pytest.approx(5.0)
    assert arc_move.arc_ccw is False  # G02 is clockwise

    start_angle = math.atan2(arc_move.start[1] - cx, arc_move.start[0] - cz)
    end_angle = math.atan2(arc_move.end[1] - cx, arc_move.end[0] - cz)
    while end_angle > start_angle:
        end_angle -= 2 * math.pi
    sweep_degrees = math.degrees(start_angle - end_angle)
    assert sweep_degrees == pytest.approx(90.0)  # positive R => <=180 degree arc


def test_move_programmed_end_defaults_to_end():
    toolpath = simulator.run(
        """
        G50 X0.0 Z0.0;
        G00 X10.0 Z10.0;
        M30;
        """
    )
    move = toolpath.moves[0]
    assert move.programmed_end == move.end


def test_g50_s_sets_max_spindle_rpm_without_creating_a_move():
    toolpath = simulator.run(
        """
        G50 S1500;
        M30;
        """
    )
    assert toolpath.moves == []
    assert toolpath.max_spindle_rpm == pytest.approx(1500.0)


def test_unsupported_canned_cycle_raises_clear_error():
    # G71/G72 are implemented (Phase 4); G73 is not yet.
    with pytest.raises(UnsupportedFeatureError):
        simulator.run(
            """
            G73 U1.0 W0.5 R3;
            M30;
            """
        )


def test_m98_to_undefined_program_raises_clear_error():
    # M98/#-assignment are implemented starting Phase 1 (see
    # test_control_flow.py / test_expression.py); this now only checks
    # that calling a program that was never registered fails loudly.
    from gcode_sim.errors import MacroError

    with pytest.raises(MacroError):
        simulator.run(
            """
            M98 P1000;
            M30;
            """
        )


def test_full_example_file_produces_expected_move_count():
    toolpath = simulator.run_file(str(EXAMPLES / "01_basic_line_arc.nc"))
    assert len(toolpath.moves) == 6
    kinds = [m.kind for m in toolpath.moves]
    assert kinds == ["rapid", "linear", "linear", "arc", "linear", "rapid"]
    assert toolpath.moves[0].start == pytest.approx((100.0, 25.0))
    assert toolpath.moves[-1].end == pytest.approx((100.0, 25.0))
