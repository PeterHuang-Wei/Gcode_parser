"""Glue: NC source -> Toolpath."""

from .interpreter import Interpreter
from .parser import parse
from .tool_table import ToolTable
from .toolpath import Toolpath


def run(source: str, tool_table: ToolTable | None = None) -> Toolpath:
    statements = parse(source)
    return Interpreter(tool_table=tool_table).run(statements)


def run_file(path: str, tool_table: ToolTable | None = None) -> Toolpath:
    with open(path, encoding="utf-8") as f:
        source = f.read()
    return run(source, tool_table=tool_table)
