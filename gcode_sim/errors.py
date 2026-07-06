"""Exception hierarchy for gcode_sim.

Alarm-code fidelity is intentionally not modeled (see docs/PLAN.md section
12.2) -- messages may reference the manual's PS-code for cross-checking,
but no alarm state machine is simulated.
"""


class GcodeSimError(Exception):
    """Base class for all gcode_sim errors."""


class LexError(GcodeSimError):
    """Raised when the source text cannot be tokenized."""


class ParseError(GcodeSimError):
    """Raised when a block of tokens cannot be turned into a statement."""


class UnsupportedFeatureError(GcodeSimError):
    """Raised for syntax/codes that are recognized but not implemented in
    the current phase (e.g. macro statements, canned cycles not yet
    built)."""


class MotionError(GcodeSimError):
    """Raised for invalid motion geometry (e.g. an arc radius too small
    for the given start/end points)."""


class MacroError(GcodeSimError):
    """Reserved for the macro interpreter (Phase 1+)."""


class CannedCycleError(GcodeSimError):
    """Reserved for canned-cycle expansion (Phase 3+)."""
