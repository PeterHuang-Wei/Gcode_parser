import pytest

from gcode_sim.errors import MacroError
from gcode_sim.expression import TokenStream, eval_condition, parse_condition_tokens
from gcode_sim.lexer import tokenize_macro_stmt
from gcode_sim.variables import EMPTY, VariableStore


def cond(text: str, store: VariableStore) -> bool:
    ts = TokenStream(tokenize_macro_stmt(text, line_no=1), line_no=1)
    return eval_condition(parse_condition_tokens(ts), store)


def test_variable_zero_and_3100_are_always_empty_and_read_only():
    store = VariableStore()
    assert store.get(0) is EMPTY
    assert store.get(3100) is EMPTY
    with pytest.raises(MacroError):
        store.set(0, 5.0)
    with pytest.raises(MacroError):
        store.set(3100, 5.0)


def test_local_variable_default_is_empty_until_written():
    store = VariableStore()
    assert store.get(1) is EMPTY
    store.set(1, 42.0)
    assert store.get(1) == 42.0


def test_local_variable_out_of_range_rejected():
    store = VariableStore()
    with pytest.raises(MacroError):
        store.set(34, 1.0)


def test_common_volatile_and_persistent_ranges():
    store = VariableStore()
    store.set(100, 1.0)
    store.set(199, 2.0)
    store.set(500, 3.0)
    store.set(999, 4.0)
    assert (store.get(100), store.get(199), store.get(500), store.get(999)) == (1.0, 2.0, 3.0, 4.0)


def test_local_frames_are_isolated_but_common_variables_are_shared():
    store = VariableStore()
    store.locals.set(1, 10.0)
    store.set(500, 99.0)  # common: shared across frames

    store.locals.push_frame({1: 20.0})
    assert store.locals.get(1) == 20.0  # new frame sees its own #1
    assert store.get(500) == 99.0  # common variable still visible
    store.set(500, 111.0)  # write from inside the "called" frame

    store.locals.pop_frame()
    assert store.locals.get(1) == 10.0  # back to the caller's #1
    assert store.get(500) == 111.0  # common variable write persisted across return


def test_pop_top_level_frame_is_rejected():
    store = VariableStore()
    with pytest.raises(MacroError):
        store.locals.pop_frame()


def test_system_variable_reads_current_position():
    store = VariableStore()
    store.bind_position_provider(lambda: (-12.5, 7.5))
    assert store.get(5001) == -12.5
    assert store.get(5002) == 7.5


def test_variable_2601_reads_current_z_position():
    # Not in either manual excerpt read for this project -- added per the
    # user's own machine/post-processor convention, where #2601 is used
    # the same way as #5001 (current Z position), e.g. in a
    # "G50 Z#2601;" block that re-declares the current position as itself.
    store = VariableStore()
    store.bind_position_provider(lambda: (-12.5, 7.5))
    assert store.get(2601) == -12.5


def test_unsupported_system_variable_raises_clear_error():
    store = VariableStore()
    with pytest.raises(MacroError):
        store.get(2001)  # tool offset -- not in the Phase 1 minimal set


# --- empty-value truth tables (manual 16.1), verified independently for
# both EQ/NE (empty != 0) and GE/GT/LE/LT (empty behaves as 0) ---

def test_empty_vs_zero_truth_table_matches_manual():
    store = VariableStore()
    # #1 left as EMPTY
    assert cond("#1 EQ #0", store) is True
    assert cond("#1 NE 0", store) is True
    assert cond("#1 GE #0", store) is True
    assert cond("#1 GT 0", store) is False
    assert cond("#1 LE #0", store) is True
    assert cond("#1 LT 0", store) is False


def test_zero_vs_empty_truth_table_matches_manual():
    store = VariableStore()
    store.set(1, 0.0)
    assert cond("#1 EQ #0", store) is False
    assert cond("#1 NE 0", store) is False
    assert cond("#1 GE #0", store) is True
    assert cond("#1 GT 0", store) is False
    assert cond("#1 LE #0", store) is True
    assert cond("#1 LT 0", store) is False


def test_compound_condition_and_or():
    store = VariableStore()
    store.set(1, 5.0)
    store.set(2, 5.0)
    store.set(3, 1.0)
    store.set(4, 2.0)
    assert cond("[#1 EQ #2] AND [#3 EQ #4]", store) is False
    assert cond("[#1 EQ #2] OR [#3 EQ #4]", store) is True
