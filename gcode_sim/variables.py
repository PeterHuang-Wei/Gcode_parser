"""Macro variable storage: local/common/system variables and empty-value
semantics (docs/PLAN.md section 5).
"""

from typing import Union

from .errors import MacroError

LOCAL_MIN, LOCAL_MAX = 1, 33
COMMON_VOLATILE_MIN, COMMON_VOLATILE_MAX = 100, 199
COMMON_PERSIST_MIN, COMMON_PERSIST_MAX = 500, 999
SYSTEM_MIN = 1000

MAX_CALL_DEPTH_MACRO = 5
MAX_CALL_DEPTH_SUBPROGRAM = 10
MAX_CALL_DEPTH_TOTAL = 15


class _EmptyType:
    """Sentinel for FANUC's <empty value> -- #0 and #3100 are always this,
    and any other local/common variable starts out as this until written.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<empty>"


EMPTY = _EmptyType()

Value = Union[float, _EmptyType]


def arithmetic_value(v: Value) -> float:
    """Empty acts as 0 once it participates in arithmetic (+, -, *, /,
    function calls, comparisons other than EQ/NE). Direct variable-to-
    variable "replacement" (a bare ``#i=#j``) instead propagates EMPTY
    unchanged -- that case is handled by the assignment executor calling
    eval_expr directly, not through this helper.
    """
    return 0.0 if v is EMPTY else v


class VariableStack:
    """Local variable (#1-#33) frames, one per active macro/subprogram call."""

    def __init__(self) -> None:
        self._frames: list[dict[int, Value]] = [{}]

    def push_frame(self, args: dict[int, Value] | None = None) -> None:
        self._frames.append(dict(args) if args else {})

    def pop_frame(self) -> None:
        if len(self._frames) <= 1:
            raise MacroError("cannot pop the top-level local variable frame")
        self._frames.pop()

    def get(self, index: int) -> Value:
        return self._frames[-1].get(index, EMPTY)

    def set(self, index: int, value: Value) -> None:
        if not (LOCAL_MIN <= index <= LOCAL_MAX):
            raise MacroError(f"#{index} is not a valid local variable number (#1-#33)")
        self._frames[-1][index] = value


class VariableStore:
    """Common (#100-#199, #500-#999) and a minimal system variable set.

    Common variables live for the lifetime of one VariableStore (one
    simulation run) and are *not* reset by macro/subprogram call or
    return -- only the local-variable frame changes on call/return (see
    docs/PLAN.md section 5).
    """

    def __init__(self) -> None:
        self._common: dict[int, Value] = {}
        self.locals = VariableStack()
        self._position_provider = None

    def bind_position_provider(self, provider) -> None:
        """``provider`` is a zero-arg callable returning the current
        (z, x) tool position (radius units), used to answer #5001/#5002
        etc. This lathe only has Z/X axes; the other axis slots in the
        usual #5001-#5006 range are not modeled."""
        self._position_provider = provider

    def get(self, index: int) -> Value:
        if index in (0, 3100):
            return EMPTY
        if LOCAL_MIN <= index <= LOCAL_MAX:
            return self.locals.get(index)
        if self._is_common(index):
            return self._common.get(index, EMPTY)
        if index >= SYSTEM_MIN:
            return self._get_system(index)
        raise MacroError(f"#{index} is out of the supported variable range")

    def set(self, index: int, value: Value) -> None:
        if index in (0, 3100):
            raise MacroError(f"#{index} is read-only (always <empty>)")
        if LOCAL_MIN <= index <= LOCAL_MAX:
            self.locals.set(index, value)
            return
        if self._is_common(index):
            self._common[index] = value
            return
        if index >= SYSTEM_MIN:
            raise MacroError(f"#{index} is not a writable system variable in this simulator")
        raise MacroError(f"#{index} is out of the supported variable range")

    @staticmethod
    def _is_common(index: int) -> bool:
        return (COMMON_VOLATILE_MIN <= index <= COMMON_VOLATILE_MAX) or (
            COMMON_PERSIST_MIN <= index <= COMMON_PERSIST_MAX
        )

    def _get_system(self, index: int) -> Value:
        if self._position_provider is not None:
            z, x = self._position_provider()
            if index in (5001, 5021):
                return z
            if index in (5002, 5022):
                return x
            if index in (5003, 5004, 5005, 5006, 5023, 5024, 5025, 5026):
                return EMPTY  # additional axis slots not modeled (Z/X only)
        raise MacroError(
            f"#{index} is a system variable not supported by this simulator "
            "(see docs/variables.md)"
        )
