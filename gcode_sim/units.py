"""Diameter/radius and metric/inch unit conversion.

Per docs/PLAN.md section 13.10: conversion happens once, at the point an
NC word's value is read, so everything downstream (Move, canned cycles,
tool_comp, visualization) works in a single consistent internal unit
(radius, millimeters) without needing to know the original programming
mode.

Only X and U are diameter-programmed by convention on this lathe (X is
the cross-slide axis); Z, W, I, K, R are already radius/direct values.
"""

DIAMETER_AXES = {"X", "U"}

INCH_TO_MM = 25.4


def diameter_to_radius(value: float) -> float:
    """Convert a diameter-programmed value to its radius equivalent."""
    return value / 2.0


def to_internal_length(address: str, value: float, *, unit_scale: float, diameter_programming: bool = True) -> float:
    """Convert a raw NC word value to the internal unit (radius, mm).

    ``unit_scale`` is 1.0 for metric (G21) or 25.4 for inch (G20) input,
    reflecting the currently active unit mode.
    """
    value = value * unit_scale
    if diameter_programming and address in DIAMETER_AXES:
        value = diameter_to_radius(value)
    return value
