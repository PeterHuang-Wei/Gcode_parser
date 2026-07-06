"""User-configurable ignore list for G-codes and macro variables.

Lets a user skip specific G-codes or #variable references -- and the
*whole* line they appear in -- without editing this simulator's own
source, for machine-/post-processor-specific codes or variables this
dialect doesn't model. This is a user-facing escape hatch on top of the
automatic "unrecognized G-code" skip already in interpreter.py (see its
module docstring and docs/PLAN.md section 13 point 14): that one only
catches codes this dialect has *never heard of*; this one lets the user
force-skip a line even for a code/variable the simulator *does*
otherwise understand.

File format (plain text, one entry per line):
    G88       -- ignore G88 wherever it appears
    G4        -- ignore G4 (dwell) wherever it appears
    #500      -- ignore any reference to macro variable #500 (as an
                 assignment target, or referenced in an NC statement's
                 address value)

Blank lines and anything that doesn't match "G<number>" or "#<number>"
are silently skipped -- consistent with this project's general policy of
tolerating unrecognized noise in *this* file too, rather than erroring
on a typo'd line.

Scope note: only plain NC statements and macro-variable assignments are
checked (see interpreter.py's _should_ignore_nc_statement/_assignment).
Control-flow statements (GOTO/IF/WHILE/END) are deliberately never
skipped this way, even if they reference an ignored variable -- silently
dropping one of those could desynchronize WHILE/END nesting or jump
targets, which is a worse failure than just leaving the variable
reference in place.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

_G_LINE_RE = re.compile(r"^G(\d+(?:\.\d+)?)$", re.IGNORECASE)
_VAR_LINE_RE = re.compile(r"^#(\d+)$")


@dataclass
class IgnoreConfig:
    g_codes: set[float] = field(default_factory=set)
    variables: set[int] = field(default_factory=set)

    @classmethod
    def load(cls, path: str | Path) -> "IgnoreConfig":
        g_codes: set[float] = set()
        variables: set[int] = set()
        for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            m = _G_LINE_RE.match(line)
            if m:
                g_codes.add(float(m.group(1)))
                continue
            m = _VAR_LINE_RE.match(line)
            if m:
                variables.add(int(m.group(1)))
        return cls(g_codes=g_codes, variables=variables)
