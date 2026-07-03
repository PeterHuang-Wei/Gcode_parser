"""Phase 3: G32 (direct thread cutting) and the single-form canned
cycles G90/G92/G94. Expected coordinates below were derived by hand
from each cycle's 4-leg description (manual 4.1.1/4.1.2/4.1.3, and the
G32 example in 3.1) *before* looking at what the code produced -- see
docs/PLAN.md section 10's testing methodology and the worked
derivations in the interpreter/canned_cycles module docstrings.
"""

from pathlib import Path

import pytest

from gcode_sim import simulator
from gcode_sim.errors import ParseError

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_g90_straight_turning_cycle():
    # G50 X50 Z100 -> start (z=100, x=25). G90 X30 Z50 F0.3 -> x=15, z=50, r=0.
    toolpath = simulator.run(
        """
        G50 X50.0 Z100.0;
        G90 X30.0 Z50.0 F0.3;
        M30;
        """
    )
    moves = toolpath.moves
    assert len(moves) == 4
    assert [m.kind for m in moves] == ["rapid", "linear", "rapid", "rapid"]
    expected_points = [(100.0, 25.0), (100.0, 15.0), (50.0, 15.0), (50.0, 25.0), (100.0, 25.0)]
    for m, (sz, sx), (ez, ex) in zip(moves, expected_points, expected_points[1:]):
        assert m.start == pytest.approx((sz, sx))
        assert m.end == pytest.approx((ez, ex))
    assert moves[1].feed == pytest.approx(0.3)
    assert moves[0].feed is None


def test_g90_modal_carry_lets_next_block_omit_g_word_and_z_r_f():
    toolpath = simulator.run(
        """
        G50 X50.0 Z100.0;
        G90 X30.0 Z50.0 F0.3;
        X20.0;
        M30;
        """
    )
    assert len(toolpath.moves) == 8
    second_cycle = toolpath.moves[4:]
    assert [m.kind for m in second_cycle] == ["rapid", "linear", "rapid", "rapid"]
    # Z (50.0) and F (0.3) are reused from the first block; only X changed.
    assert second_cycle[0].end == pytest.approx((100.0, 10.0))
    assert second_cycle[1].end == pytest.approx((50.0, 10.0))
    assert second_cycle[1].feed == pytest.approx(0.3)
    assert second_cycle[-1].end == pytest.approx((100.0, 25.0))  # back to A


def test_g90_cycle_retriggers_on_a_bare_m_code_block():
    # manual 4.1.6: a block with no motion address at all (even just an
    # M-code) still re-runs the cycle with the stored modal parameters
    # while G90/G92/G94 is active -- this is intentional, not a bug.
    toolpath = simulator.run(
        """
        G50 X50.0 Z100.0;
        G90 X30.0 Z50.0 F0.3;
        M08;
        M30;
        """
    )
    assert len(toolpath.moves) == 8
    first_cycle, second_cycle = toolpath.moves[:4], toolpath.moves[4:]
    # same geometry both times (source_line legitimately differs: the
    # second cycle was triggered by the M08 block, not a G90 block)
    for a, b in zip(first_cycle, second_cycle):
        assert (a.kind, a.start, a.end, a.feed) == (b.kind, b.start, b.end, b.feed)


def test_g90_cycle_is_cleared_by_switching_to_a_different_motion_code():
    toolpath = simulator.run(
        """
        G50 X50.0 Z100.0;
        G90 X30.0 Z50.0 F0.3;
        G00 X0.0 Z0.0;
        M30;
        """
    )
    # the G00 block clears the canned-cycle modal state; a subsequent bare
    # X/Z-only block with no G-word now means "G00" (whatever was last
    # active), not "resume G90".
    assert len(toolpath.moves) == 5
    assert toolpath.moves[4].kind == "rapid"
    assert toolpath.moves[4].end == pytest.approx((0.0, 0.0))


def test_g94_straight_facing_cycle():
    toolpath = simulator.run(
        """
        G50 X50.0 Z100.0;
        G94 X10.0 Z80.0 F0.2;
        M30;
        """
    )
    moves = toolpath.moves
    assert len(moves) == 4
    assert [m.kind for m in moves] == ["rapid", "linear", "rapid", "rapid"]
    expected_points = [(100.0, 25.0), (80.0, 25.0), (80.0, 5.0), (100.0, 5.0), (100.0, 25.0)]
    for m, (sz, sx), (ez, ex) in zip(moves, expected_points, expected_points[1:]):
        assert m.start == pytest.approx((sz, sx))
        assert m.end == pytest.approx((ez, ex))


def test_g92_straight_thread_cutting_cycle():
    toolpath = simulator.run(
        """
        G50 X50.0 Z100.0;
        G92 X30.0 Z50.0 F2.0;
        M30;
        """
    )
    moves = toolpath.moves
    assert len(moves) == 4
    assert [m.kind for m in moves] == ["rapid", "thread", "rapid", "rapid"]
    assert moves[1].start == pytest.approx((100.0, 15.0))
    assert moves[1].end == pytest.approx((50.0, 15.0))
    assert moves[1].feed == pytest.approx(2.0)


def test_g32_direct_thread_cutting_matches_manual_example():
    # manual 3.1 example 1 (straight thread cutting), traced relative to
    # an arbitrary (0, 0) start since the example itself has no G50.
    toolpath = simulator.run(
        """
        G00 U-62.0;
        G32 W-74.5 F4.0;
        G00 U62.0;
        W74.5;
        U-64.0;
        G32 W-74.5;
        G00 U64.0;
        W74.5;
        M30;
        """
    )
    moves = toolpath.moves
    assert len(moves) == 8
    assert [m.kind for m in moves] == [
        "rapid", "thread", "rapid", "rapid", "rapid", "thread", "rapid", "rapid",
    ]
    first_thread, second_thread = moves[1], moves[5]
    assert first_thread.start == pytest.approx((0.0, -31.0))
    assert first_thread.end == pytest.approx((-74.5, -31.0))
    assert first_thread.feed == pytest.approx(4.0)
    assert second_thread.start == pytest.approx((0.0, -32.0))
    assert second_thread.end == pytest.approx((-74.5, -32.0))
    assert second_thread.feed is None  # F not modally tracked (docs/PLAN.md section 6)
    assert moves[-1].end == pytest.approx((0.0, 0.0))  # back to the starting point


def test_canned_cycle_without_any_xz_target_raises_clear_error():
    with pytest.raises(ParseError):
        simulator.run(
            """
            G90 F0.3;
            M30;
            """
        )


def test_combined_example_file_runs_end_to_end():
    toolpath = simulator.run_file(str(EXAMPLES / "04_g32_g90_g92_g94.nc"))
    assert len(toolpath.moves) == 16
    assert toolpath.moves[-1].end == pytest.approx((100.0, 25.0))
