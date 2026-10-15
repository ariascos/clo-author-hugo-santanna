#!/usr/bin/env python3
"""
Session Guard Hook -- PreToolUse

Enforces session-scoped guards:
- freeze: blocks Edit/Write outside allowed directories
- careful: blocks destructive Bash commands

Reads guard configuration from .claude/state/session-guards.json.
If no guards are active or the file doesn't exist, passes through immediately.
A guards file that exists but can't be read is an error, not "no guards":
the user switched a guard on and must hear that it isn't working.

Hook Event: PreToolUse (matcher: "Edit|Write|Bash")
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hooklib import HookError, emit, run  # noqa: E402


def load_guards(project_dir: Path) -> dict:
    """Load active guards from session state."""
    guards_file = project_dir / ".claude" / "state" / "session-guards.json"
    if not guards_file.exists():
        return {}
    try:
        return json.loads(guards_file.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise HookError(
            f"{guards_file} exists but can't be read ({exc}), so /freeze and /careful "
            f"cannot be checked. Fix or delete that file by hand; with onFailure "
            f"\"block\" this hook blocks Edit, Write and Bash until then"
        ) from None


def check_freeze(tool_name: str, tool_input: dict, guards: dict) -> tuple:
    """Check if the edit/write is allowed by freeze guard."""
    freeze = guards.get("freeze", {})
    if not freeze.get("active", False):
        return True, ""

    if tool_name not in ("Edit", "Write"):
        return True, ""

    file_path = tool_input.get("file_path", "")
    if not file_path:
        raise HookError(f"{tool_name} payload has no tool_input.file_path; freeze can't check it")

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")

    # .claude/ is always editable
    if "/.claude/" in file_path or file_path.endswith("/.claude"):
        return True, ""

    # Check against allowed paths
    allowed = freeze.get("allowed_paths", [])
    for allowed_path in allowed:
        # Resolve relative to project dir
        full_allowed = os.path.join(project_dir, allowed_path)
        if file_path.startswith(full_allowed):
            return True, ""

    return False, (
        f"FREEZE ACTIVE: Edit blocked. File '{os.path.basename(file_path)}' "
        f"is outside allowed paths: {allowed}. Run /freeze off to deactivate."
    )


DESTRUCTIVE_PATTERNS = [
    (r"\brm\s+-(r|f|rf|fr)", "rm with recursive/force flags"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard"),
    (r"\bgit\s+push\s+--force\b", "git push --force"),
    (r"\bgit\s+push\s+-f\b", "git push -f"),
    (r"\bgit\s+clean\s+-f\b", "git clean -f"),
    (r"\bgit\s+checkout\s+--\s+\.", "git checkout -- ."),
    (r"\bgit\s+branch\s+-D\b", "git branch -D"),
    (r"\bDROP\s+TABLE\b", "DROP TABLE"),
    (r"\bDROP\s+DATABASE\b", "DROP DATABASE"),
    (r"\bchmod\s+777\b", "chmod 777"),
]


def check_careful(tool_name: str, tool_input: dict, guards: dict) -> tuple:
    """Check if the bash command is allowed by careful guard."""
    careful = guards.get("careful", {})
    if not careful.get("active", False):
        return True, ""

    if tool_name != "Bash":
        return True, ""

    command = tool_input.get("command", "")
    if not command:
        raise HookError("Bash payload has no tool_input.command; careful mode can't check it")

    for pattern, description in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, (
                f"CAREFUL MODE: Blocked '{description}'. "
                f"Run /careful off to deactivate, or rephrase the command."
            )

    return True, ""


def deny(reason: str) -> None:
    """Emit the PreToolUse deny decision (top-level "decision" is deprecated)."""
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    })


def body(hook) -> None:
    tool_name = hook.require("tool_name")
    tool_input = hook.require("tool_input")

    guards = load_guards(hook.project_dir())
    if not any(g.get("active") for g in guards.values() if isinstance(g, dict)):
        hook.skip("no active guards")

    for check in (check_freeze, check_careful):
        allowed, message = check(tool_name, tool_input, guards)
        if not allowed:
            deny(message)
            hook.acted(message)
            return
    hook.skip(f"{tool_name} allowed by active guards")


if __name__ == "__main__":
    run("session-guard", body)
