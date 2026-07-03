"""Minimal, single-registry O-number lookup (docs/PLAN.md section 13.13).

v1 assumption: every program that might be called by G65/M98 (main
program, subprograms, macros) is registered in one ProgramRegistry, built
from one source blob split on "O<number>" lines. Real-machine folder
search order / same-name overriding is *not* implemented -- see
docs/program_registry.md.
"""

import re

from .errors import MacroError
from .parser import parse

O_NUMBER_RE = re.compile(r"^\s*[Oo](\d+)")

MAIN_KEY = -1  # key for the unnumbered ("main") program, if any


class ProgramRegistry:
    def __init__(self) -> None:
        self._programs: dict[int, list] = {}

    def register_source(self, source: str) -> None:
        """Split ``source`` on O-number lines and register each chunk. A
        source with no O-number line at all is registered as the single
        "main" program."""
        for o_number, body in self._split_by_o_number(source):
            statements = parse(body)
            key = o_number if o_number is not None else MAIN_KEY
            self._programs[key] = statements

    def get(self, o_number: int) -> list:
        if o_number not in self._programs:
            raise MacroError(f"program O{o_number:04d} not found in the program registry")
        return self._programs[o_number]

    def main_program(self) -> list:
        if MAIN_KEY in self._programs:
            return self._programs[MAIN_KEY]
        if self._programs:
            return next(iter(self._programs.values()))
        raise MacroError("no program registered")

    @staticmethod
    def _split_by_o_number(source: str) -> list[tuple[int | None, str]]:
        chunks: list[tuple[int | None, str]] = []
        current_o: int | None = None
        current_lines: list[str] = []

        def _flush() -> None:
            body = "\n".join(current_lines)
            # A leading blank/whitespace-only run before the first O-number
            # line (e.g. a leading blank line in a triple-quoted string)
            # must not become a spurious empty "main program" chunk that
            # would shadow the real numbered program in main_program().
            if body.strip():
                chunks.append((current_o, body))

        for line in source.splitlines():
            m = O_NUMBER_RE.match(line)
            if m:
                _flush()
                current_o = int(m.group(1))
                current_lines = [line[m.end():]]
            else:
                current_lines.append(line)
        _flush()
        return chunks
