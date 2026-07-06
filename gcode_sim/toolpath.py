"""Toolpath data structures.

Coordinates are always stored as (z, x) tuples in radius units,
regardless of whether the source program used diameter or radius
programming (see docs/PLAN.md section 13.10) -- diameter is purely a
display-time conversion done by viz_matplotlib.py / export_json.py.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional

Kind = Literal["rapid", "linear", "arc", "thread"]

Point = tuple[float, float]


@dataclass
class Move:
    kind: Kind
    start: Point
    end: Point
    programmed_end: Optional[Point] = None
    feed: Optional[float] = None
    spindle: Optional[float] = None
    arc_center: Optional[Point] = None
    arc_ccw: Optional[bool] = None
    source_line: Optional[int] = None
    cycle: Optional[str] = None
    tool: Optional[str] = None

    def __post_init__(self) -> None:
        if self.programmed_end is None:
            self.programmed_end = self.end


@dataclass
class Toolpath:
    moves: list[Move] = field(default_factory=list)
    max_spindle_rpm: Optional[float] = None

    def append(self, move: Move) -> None:
        self.moves.append(move)
