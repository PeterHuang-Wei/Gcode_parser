"""AST node definitions.

Phase 0 only has NCStatement (plain motion/misc-function blocks).
Assignment/Goto/IfGoto/IfThen/WhileDo/MacroCall are added in Phase 1/2.
"""

from dataclasses import dataclass

from .lexer import Word


@dataclass
class NCStatement:
    seq_no: int | None
    words: list[Word]
    skip: bool
    line_no: int
