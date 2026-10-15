#!/usr/bin/env python3
"""
Protect-Files Hook

Blocks Claude's Edit/Write on files that should change only by hand: the
settings file and approved research artifacts (strategy memos, referee
reports, quality scores). Matching is on the file's basename.

Customize PROTECTED_PATTERNS for your project.

Hook Event: PreToolUse (matcher: "Edit|Write")
Returns: Exit 0; a deny decision as JSON when the file is protected
"""

from __future__ import annotations

import sys
from fnmatch import fnmatch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hooklib import emit, run  # noqa: E402

PROTECTED_PATTERNS = [
    "settings.json",
    "strategy-memo-*.md",
    "referee-report-*.md",
    "quality-score-*.json",
]


def body(hook) -> None:
    tool = hook.require("tool_name")
    if tool not in ("Edit", "Write"):
        hook.skip(f"tool {tool} is not a file edit")
    name = Path(hook.require("tool_input.file_path")).name

    for pattern in PROTECTED_PATTERNS:
        if fnmatch(name, pattern):
            emit({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Protected file: {name}. Edit it by hand, or remove the "
                        f"pattern '{pattern}' from .claude/hooks/protect-files.py."
                    ),
                }
            })
            hook.acted(f"blocked {name}")
            return
    hook.skip(f"not protected: {name}")


if __name__ == "__main__":
    run("protect-files", body)
