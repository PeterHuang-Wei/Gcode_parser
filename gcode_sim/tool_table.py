"""Tool table (T-code lookup).

Phase 0 only needs to record which tool is selected; nose_radius/
orientation stay at their no-op defaults until Phase 4.5 (tool nose
radius compensation) gives them meaning.
"""

from dataclasses import dataclass


@dataclass
class ToolEntry:
    tool_no: str
    offset_no: str
    nose_radius: float = 0.0
    orientation: int = 0


class ToolTable(dict[str, ToolEntry]):
    """Maps a full tool code (e.g. "0101") to its ToolEntry.

    Not every T-code needs to be pre-registered: looking up a missing
    code returns a default all-zero ToolEntry rather than raising.
    """

    def get_entry(self, tool_code: str) -> ToolEntry:
        if tool_code in self:
            return self[tool_code]
        tool_no = tool_code[:2] if len(tool_code) >= 2 else tool_code
        offset_no = tool_code[2:4] if len(tool_code) >= 4 else "00"
        return ToolEntry(tool_no=tool_no, offset_no=offset_no)
