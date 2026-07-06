"""Glue: NC source -> Toolpath."""

from .ignore_config import IgnoreConfig
from .interpreter import Interpreter
from .program_registry import ProgramRegistry
from .tool_table import ToolTable
from .toolpath import Toolpath


def run(
    source: str, tool_table: ToolTable | None = None, ignore_config: IgnoreConfig | None = None
) -> Toolpath:
    registry = ProgramRegistry()
    registry.register_source(source)
    statements = registry.main_program()
    return Interpreter(tool_table=tool_table, ignore_config=ignore_config).run(statements, registry=registry)


def run_file(
    path: str, tool_table: ToolTable | None = None, ignore_config_path: str | None = None
) -> Toolpath:
    with open(path, encoding="utf-8") as f:
        source = f.read()
    ignore_config = IgnoreConfig.load(ignore_config_path) if ignore_config_path else None
    return run(source, tool_table=tool_table, ignore_config=ignore_config)
