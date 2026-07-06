from pathlib import Path

import pytest

from gcode_sim.errors import MacroError, ParseError
from gcode_sim.interpreter import Interpreter
from gcode_sim.program_registry import ProgramRegistry
from gcode_sim.variables import EMPTY

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def run_and_get_interpreter(source: str) -> Interpreter:
    registry = ProgramRegistry()
    registry.register_source(source)
    interp = Interpreter()
    interp.run(registry.main_program(), registry=registry)
    return interp


def test_goto_if_sum_1_to_10_matches_manual_example():
    interp = run_and_get_interpreter(Path(EXAMPLES / "02_macro_sum.nc").read_text())
    assert interp.variables.get(1) == 55.0


def test_while_do_end_sum_1_to_10_matches_manual_example():
    interp = run_and_get_interpreter(
        """
        O0001 ;
        #1=0 ;
        #2=1 ;
        WHILE[#2 LE 10] DO1 ;
        #1=#1+#2 ;
        #2=#2+1 ;
        END1 ;
        M30 ;
        """
    )
    assert interp.variables.get(1) == 55.0


def test_while_loop_that_never_executes():
    interp = run_and_get_interpreter(
        """
        #1=0 ;
        WHILE[#1 GT 10] DO1 ;
        #1=#1+1 ;
        END1 ;
        M30 ;
        """
    )
    assert interp.variables.get(1) == 0.0


def test_if_then_executes_single_statement():
    interp = run_and_get_interpreter(
        """
        #1=5 ;
        #2=5 ;
        IF[#1 EQ #2] THEN #3=100 ;
        M30 ;
        """
    )
    assert interp.variables.get(3) == 100.0


def test_if_then_condition_false_skips_statement():
    interp = run_and_get_interpreter(
        """
        #1=5 ;
        #2=6 ;
        IF[#1 EQ #2] THEN #3=100 ;
        M30 ;
        """
    )
    assert interp.variables.get(3) is EMPTY


def test_do_id_must_be_1_2_or_3():
    with pytest.raises(ParseError):
        run_and_get_interpreter(
            """
            WHILE[1 GT 0] DO4;
            END4;
            M30;
            """
        )


def test_do_ranges_cannot_overlap():
    with pytest.raises(MacroError):
        run_and_get_interpreter(
            """
            WHILE[1 GT 0] DO1;
            WHILE[1 GT 0] DO2;
            END1;
            END2;
            M30;
            """
        )


def test_do_id_cannot_be_reused_while_still_open():
    with pytest.raises(MacroError):
        run_and_get_interpreter(
            """
            WHILE[1 GT 0] DO1;
            WHILE[1 GT 0] DO1;
            END1;
            END1;
            M30;
            """
        )


def test_m98_calls_subprogram_with_repeat_count():
    interp = run_and_get_interpreter(
        """
        O0001;
        #100=0;
        M98 P8000 L3;
        M30;
        O8000 (adds 10 to the common variable, three times via L3);
        #100=#100+10;
        M99;
        """
    )
    assert interp.variables.get(100) == 30.0


def test_m98_nested_subprogram_calls():
    interp = run_and_get_interpreter(
        """
        O0001;
        M98 P8000;
        M30;
        O8000;
        #100=1;
        M98 P8001;
        M99;
        O8001;
        #100=#100+1;
        M99;
        """
    )
    assert interp.variables.get(100) == 2.0


def test_m98_does_not_create_a_new_local_variable_frame():
    # Unlike G65 macro calls (Phase 2), M98 subprogram calls do *not* get
    # their own local-variable (#1-#33) frame -- manual 16.7: "宏程序調用
    # 會引起局部變量的級別變化,但子程式調用不會引起變化". So the callee
    # writing #1 *does* overwrite the caller's #1; this is intentional,
    # not a bug (docs/PLAN.md section 6/13.2).
    interp = run_and_get_interpreter(
        """
        O0001;
        #1=111;
        M98 P8000;
        M30;
        O8000;
        #1=222;
        #500=999;
        M99;
        """
    )
    assert interp.variables.get(1) == 222.0
    # #500 is a common/persistent variable: writes from inside the call
    # are visible after return.
    assert interp.variables.get(500) == 999.0


def test_subprogram_call_depth_limit_is_enforced():
    programs = []
    for i in range(12):
        body = f"O{9000 + i};\n"
        if i < 11:
            body += f"M98 P{9000 + i + 1};\n"
        body += "M99;"
        programs.append(body)
    source = "O0001;\nM98 P9000;\nM30;\n" + "\n".join(programs)
    with pytest.raises(MacroError):
        run_and_get_interpreter(source)
