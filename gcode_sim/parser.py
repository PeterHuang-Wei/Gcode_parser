"""token -> AST.

Phase 0: every block is an NCStatement (macro statements are rejected
earlier, by the lexer). Block classification into macro-vs-NC statements
(docs/PLAN.md section 3.2) arrives with Phase 1.
"""

from .ast_nodes import NCStatement
from .lexer import tokenize


def parse(source: str) -> list[NCStatement]:
    return [
        NCStatement(seq_no=b.seq_no, words=b.words, skip=b.skip, line_no=b.line_no)
        for b in tokenize(source)
    ]
