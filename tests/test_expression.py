import math

import pytest

from gcode_sim.errors import MacroError, ParseError
from gcode_sim.expression import eval_expr, parse_expression
from gcode_sim.variables import EMPTY, VariableStore


def ev(text: str, store: VariableStore | None = None):
    store = store or VariableStore()
    return eval_expr(parse_expression(text, line_no=1), store)


def test_literal():
    assert ev("100") == 100.0


def test_arithmetic_precedence_matches_manual_example():
    # manual 16.3: #1=#2+#3*SIN[#4] -- multiply/function bind tighter than +
    store = VariableStore()
    store.set(2, 10.0)
    store.set(3, 2.0)
    store.set(4, 90.0)  # SIN[90] == 1.0
    result = ev("#2+#3*SIN[#4]", store)
    assert result == pytest.approx(10.0 + 2.0 * 1.0)


def test_variable_reference_and_bracketed_index():
    store = VariableStore()
    store.set(1, 5.0)
    store.set(100, 7.0)
    assert ev("#1", store) == 5.0
    assert ev("#[#1+95]", store) == 7.0  # #[5+95] == #100


def test_unary_minus():
    assert ev("-5") == -5.0
    store = VariableStore()
    store.set(1, 3.0)
    assert ev("-#1", store) == -3.0


def test_named_variable_alias_evaluates_to_empty_with_a_warning():
    # #_OFST-style named aliases aren't documented in either manual
    # excerpt read for this project, but are a real convention some
    # machines/post-processors use -- accepted syntactically (not a
    # ParseError that would abort the whole program) and treated as
    # <empty>, with a warning so it's still clear something wasn't
    # understood (see NamedVarRef's docstring in ast_nodes.py).
    with pytest.warns(UserWarning, match="_OFST"):
        assert ev("#_OFST") is EMPTY


def test_functions():
    assert ev("SIN[90]") == pytest.approx(1.0)
    assert ev("COS[0]") == pytest.approx(1.0)
    assert ev("SQRT[16]") == pytest.approx(4.0)
    assert ev("ABS[-5]") == pytest.approx(5.0)
    assert ev("ROUND[1.2345]") == pytest.approx(1.0)
    assert ev("FIX[1.2]") == pytest.approx(1.0)
    assert ev("FIX[-1.2]") == pytest.approx(-1.0)  # manual example
    assert ev("FUP[1.2]") == pytest.approx(2.0)
    assert ev("FUP[-1.2]") == pytest.approx(-2.0)  # manual example


def test_function_abbreviations():
    assert ev("RO[1.6]") == pytest.approx(2.0)  # ROUND abbreviated
    assert ev("FI[1.9]") == pytest.approx(1.0)  # FIX abbreviated


def test_pow_is_not_abbreviated_but_is_two_arg():
    assert ev("POW[2,3]") == pytest.approx(8.0)


def test_atan_one_and_two_argument_forms():
    assert ev("ATAN[1]") == pytest.approx(45.0)
    # manual example: #1=ATAN[-1]/[-1]; -> 225.0 (0-360 range, NAT=0 default)
    assert ev("ATAN[-1]/[-1]") == pytest.approx(225.0)
    assert ev("ATAN[-1,-1]") == pytest.approx(225.0)


def test_atan_slash_without_bracket_is_a_parse_error():
    # manual: ATAN[1]/10 (no brackets around the second operand) is a
    # syntax error (cf. PS1131), not a silent fallback to plain division.
    with pytest.raises(ParseError):
        parse_expression("ATAN[1]/10", line_no=1)


def test_bracketed_atan_then_divide_is_ordinary_division():
    assert ev("[ATAN[1]]/10") == pytest.approx(4.5)


def test_bracket_nesting_over_five_levels_is_rejected():
    expr = "1"
    for _ in range(6):
        expr = f"[{expr}]"
    with pytest.raises(ParseError):
        parse_expression(expr, line_no=1)


def test_bitwise_and_or_xor_mod():
    assert ev("6 AND 3") == float(6 & 3)
    assert ev("6 OR 1") == float(6 | 1)
    assert ev("6 XOR 3") == float(6 ^ 3)
    assert ev("7 MOD 3") == 1.0
    assert ev("-7 MOD 3") == -1.0  # manual: sign follows the dividend


def test_division_by_zero_raises():
    with pytest.raises(MacroError):
        ev("1/0")


def test_empty_propagates_through_bare_replacement_but_not_arithmetic():
    store = VariableStore()
    # #1 is untouched -> EMPTY
    assert ev("#1", store) is EMPTY
    assert ev("#1*5", store) == 0.0
    assert ev("#1+#1", store) == 0.0
