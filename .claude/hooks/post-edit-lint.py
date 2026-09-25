#!/usr/bin/env python3
"""
Post-Edit Lint Hook

Lints an R/Python/Julia script right after Claude edits it and puts any
findings in front of Claude as additionalContext, so a violation such as
setwd() or a missing set.seed() is fixed in the same editing pass instead of
waiting for the coder-critic. Covers content invariants INV-14/15/16/19.
The linting itself lives in lint-scripts.sh.

Hook Event: PostToolUse (matcher: "Edit|Write")
Returns: Exit 0; findings as hookSpecificOutput.additionalContext
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hooklib import HookError, emit, run  # noqa: E402

SCRIPT_EXTENSIONS = {".R", ".py", ".jl"}
LINTER = Path(__file__).resolve().parent / "lint-scripts.sh"


def body(hook) -> None:
    file_path = hook.require("tool_input.file_path")
    path = Path(file_path)

    if path.suffix not in SCRIPT_EXTENSIONS:
        hook.skip(f"not a script: {path.name}")
    if ".claude" in path.parts:
        hook.skip("scaffold file, not analysis code")
    if not path.exists():
        raise HookError(f"edited file does not exist on disk: {file_path}")
    if not LINTER.exists():
        raise HookError(f"linter missing: {LINTER}")

    result = subprocess.run(
        ["bash", str(LINTER), str(path)],
        capture_output=True, text=True, timeout=8,
    )
    report = result.stdout.strip()
    if not report:
        raise HookError(f"lint-scripts.sh produced no report (stderr: {result.stderr.strip()[:120]})")
    if "Status: CLEAN" in report:
        hook.acted(f"clean: {path.name}")
        return

    emit({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                "Lint findings for the file just edited "
                "(content invariants INV-14/15/16/19):\n" + report
            ),
        }
    })
    hook.acted(f"findings: {path.name}")


if __name__ == "__main__":
    run("post-edit-lint", body)
