from pathlib import Path

import pytest

from gcode_sim import simulator
from gcode_sim.errors import MacroError
from gcode_sim.interpreter import Interpreter
from gcode_sim.program_registry import ProgramRegistry

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def run_and_get_interpreter(source: str) -> Interpreter:
    registry = ProgramRegistry()
    registry.register_source(source)
    interp = Interpreter()
    interp.run(registry.main_program(), registry=registry)
    return interp


def test_g65_example_adapted_from_manual_produces_expected_path():
    # A=1.0, B=2.0 -> #3=3.0 each call, U3.0 (diameter) -> +1.5 radius per
    # call, L2 -> two separate calls, each with a *fresh* frame (so #3 is
    # recomputed from the same A/B each time, not accumulated).
    toolpath = simulator.run_file(str(EXAMPLES / "03_g65_macro_call.nc"))
    assert len(toolpath.moves) == 2
    assert toolpath.moves[0].kind == "rapid"
    assert toolpath.moves[0].end == pytest.approx((0.0, 1.5))
    assert toolpath.moves[1].end == pytest.approx((0.0, 3.0))


def test_g65_type1_argument_mapping():
    interp = run_and_get_interpreter(
        """
        O0001;
        G65 P9001 A1.0 B2.0 D3.0;
        M30;
        O9001;
        #100=#1;
        #101=#2;
        #102=#7;
        M99;
        """
    )
    # A->#1, B->#2, D->#7 (manual 16.7.1 type I table)
    assert interp.variables.get(100) == 1.0
    assert interp.variables.get(101) == 2.0
    assert interp.variables.get(102) == 3.0


def test_g65_type2_argument_groups():
    interp = run_and_get_interpreter(
        """
        O0001;
        G65 P9002 A9.0 I1.0 J2.0 K3.0 I4.0 J5.0 K6.0;
        M30;
        O9002;
        #100=#1;
        #101=#4;
        #102=#5;
        #103=#6;
        #104=#7;
        #105=#8;
        #106=#9;
        M99;
        """
    )
    # repeated I/J/K -> type II: A->#1, group1(I,J,K)->#4,#5,#6, group2->#7,#8,#9
    assert interp.variables.get(100) == 9.0
    assert interp.variables.get(101) == 1.0
    assert interp.variables.get(102) == 2.0
    assert interp.variables.get(103) == 3.0
    assert interp.variables.get(104) == 4.0
    assert interp.variables.get(105) == 5.0
    assert interp.variables.get(106) == 6.0


def test_g65_gets_a_fresh_local_frame_unlike_m98():
    interp = run_and_get_interpreter(
        """
        O0001;
        #1=111;
        G65 P9003;
        M30;
        O9003;
        #1=222;
        M99;
        """
    )
    # #1 is local: G65 pushes a *new* frame, so the callee's write to #1
    # must not leak back to the caller once the call returns.
    assert interp.variables.get(1) == 111.0


def test_g65_argument_not_specified_is_empty_in_new_frame():
    interp = run_and_get_interpreter(
        """
        O0001;
        G65 P9004 A5.0;
        M30;
        O9004;
        #100=#2;
        M99;
        """
    )
    from gcode_sim.variables import EMPTY

    assert interp.variables.get(100) is EMPTY


def test_g65_macro_call_depth_limit_is_enforced():
    programs = []
    for i in range(7):
        body = f"O{9100 + i};\n"
        if i < 6:
            body += f"G65 P{9100 + i + 1};\n"
        body += "M99;"
        programs.append(body)
    source = "O0001;\nG65 P9100;\nM30;\n" + "\n".join(programs)
    with pytest.raises(MacroError):
        run_and_get_interpreter(source)


def test_g65_and_m98_can_be_combined_in_nested_calls():
    interp = run_and_get_interpreter(
        """
        O0001;
        #1=1;
        G65 P9200 A10.0;
        M30;
        O9200;
        #100=#1;
        M98 P9201;
        M99;
        O9201;
        #101=#1;
        M99;
        """
    )
    # inside the macro frame, #1 == 10 (the argument); M98 shares that
    # same frame (does not push its own), so #101 also sees 10.
    assert interp.variables.get(100) == 10.0
    assert interp.variables.get(101) == 10.0
    # back in the caller, the original #1 == 1 is untouched
    assert interp.variables.get(1) == 1.0
