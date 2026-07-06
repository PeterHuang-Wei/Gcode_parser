"""User-configurable ignore list (gcode_sim/ignore_config.py): lets a
user force-skip specific G-codes or #variable references (and the whole
line they appear in), on top of the automatic unknown-G-code skip
already covered by test_interpolation.py's G88 tests.
"""

from pathlib import Path

import pytest

from gcode_sim import simulator
from gcode_sim.ignore_config import IgnoreConfig


def test_load_parses_g_codes_and_variables(tmp_path: Path):
    ignore_file = tmp_path / "ignore.txt"
    ignore_file.write_text("G88\nG4\n\n#500\n#501\nnot a valid line\n", encoding="utf-8")
    cfg = IgnoreConfig.load(ignore_file)
    assert cfg.g_codes == {88.0, 4.0}
    assert cfg.variables == {500, 501}


def test_ignored_g_code_skips_the_whole_line_even_if_otherwise_supported():
    # G01 is fully supported -- but an explicit ignore entry still forces
    # the whole line (including its X/Z motion) to be skipped.
    cfg = IgnoreConfig(g_codes={1.0})
    toolpath = simulator.run(
        """
        G50 X50.0 Z100.0;
        G01 X10.0 Z10.0;
        G00 X20.0 Z20.0;
        M30;
        """,
        ignore_config=cfg,
    )
    assert len(toolpath.moves) == 1
    assert toolpath.moves[0].kind == "rapid"
    assert toolpath.moves[0].end == pytest.approx((20.0, 10.0))


def test_ignored_variable_skips_assignment_and_any_line_referencing_it():
    cfg = IgnoreConfig(variables={500})
    toolpath = simulator.run(
        """
        G50 X0.0 Z0.0;
        #500=999;
        #501=#500+1;
        G00 X[#501] Z10.0;
        M30;
        """,
        ignore_config=cfg,
    )
    # #500=999 is skipped (ignored assignment target); #501=#500+1 is also
    # skipped (its expression references #500), so #501 stays <empty> ->
    # arithmetic value 0 -> X radius 0.
    assert len(toolpath.moves) == 1
    assert toolpath.moves[0].end == pytest.approx((10.0, 0.0))


def test_ignored_variable_referenced_in_nc_statement_address_skips_that_line():
    cfg = IgnoreConfig(variables={100})
    toolpath = simulator.run(
        """
        G50 X0.0 Z0.0;
        #100=5.0;
        G00 X[#100] Z1.0;
        G00 X20.0 Z20.0;
        M30;
        """,
        ignore_config=cfg,
    )
    # #100=5.0 is skipped (ignored assignment target); the G00 line
    # referencing #100 is also skipped entirely; only the last G00 runs.
    assert len(toolpath.moves) == 1
    assert toolpath.moves[0].end == pytest.approx((20.0, 10.0))


def test_no_ignore_config_behaves_exactly_as_before():
    toolpath = simulator.run(
        """
        G50 X50.0 Z100.0;
        G01 X10.0 Z10.0;
        M30;
        """
    )
    assert len(toolpath.moves) == 1
