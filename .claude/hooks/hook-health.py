#!/usr/bin/env python3
"""
Hook Health Check

Runs at session start and speaks only when something is wrong. It catches the
failure a hook can't report about itself: never running at all.

  1. Every hook command in .claude/settings*.json points at a file that
     exists (and, for shell scripts, is executable).
  2. Errors logged in .claude/state/hook-log.jsonl since the last check.
  3. Liveness: a hook on a frequent event (PreToolUse/PostToolUse) that has
     logged nothing across 3+ logged sessions is configured but not running.

Problems go to the user as systemMessage and to Claude as additionalContext.

Hook Event: SessionStart (matcher: "startup|resume")
Returns: Exit 0; silent when healthy
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hooklib import emit, run  # noqa: E402

FREQUENT_EVENTS = {"PreToolUse", "PostToolUse"}
MIN_SESSIONS_FOR_LIVENESS = 3


def configured_hooks(root: Path) -> list[dict]:
    """(event, script path) for every command hook in the project settings."""
    found = []
    for name in ("settings.json", "settings.local.json"):
        path = root / ".claude" / name
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            found.append({"event": "?", "script": None, "problem": f"{path.name} is not valid JSON ({exc.msg})"})
            continue
        for event, groups in settings.get("hooks", {}).items():
            for group in groups:
                for h in group.get("hooks", []):
                    cmd = h.get("command", "")
                    m = re.search(r'([^\s"\']*\.claude/hooks/[^\s"\']+)', cmd.replace('"$CLAUDE_PROJECT_DIR"', str(root)).replace("$CLAUDE_PROJECT_DIR", str(root)))
                    if m:
                        found.append({"event": event, "script": Path(m.group(1)), "command": cmd})
    return found


def read_log(root: Path) -> list[dict]:
    path = root / ".claude" / "state" / "hook-log.jsonl"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def body(hook) -> None:
    root = hook.project_dir()
    state_path = root / ".claude" / "state" / "hook-health.json"
    try:
        last_check = json.loads(state_path.read_text()).get("last_check", "")
    except (OSError, json.JSONDecodeError):
        last_check = ""

    problems: list[str] = []
    hooks = configured_hooks(root)

    # 1. Files exist and are runnable
    for h in hooks:
        if h.get("problem"):
            problems.append(h["problem"])
            continue
        script = h["script"]
        if not script.exists():
            problems.append(f"{h['event']} hook points at a missing file: {script.relative_to(root) if script.is_relative_to(root) else script}")
        elif script.suffix == ".sh" and not os.access(script, os.X_OK):
            problems.append(f"{script.name} is not executable (chmod +x it)")

    # 2. Errors since the last check
    log = read_log(root)
    errors = defaultdict(list)
    for e in log:
        if e.get("outcome") == "error" and e.get("ts", "") > last_check and e.get("hook") != "hook-health":
            errors[e.get("hook", "?")].append(e)
    for name, errs in errors.items():
        problems.append(f"{name} failed {len(errs)} time(s) since the last session; latest: {errs[-1].get('detail', '')}")

    # 3. Liveness for hooks that log through _hooklib
    sessions = {e.get("session") for e in log if e.get("session")}
    if len(sessions) >= MIN_SESSIONS_FOR_LIVENESS:
        seen = {e.get("hook") for e in log}
        for h in hooks:
            script = h.get("script")
            if not script or not script.exists() or h["event"] not in FREQUENT_EVENTS:
                continue
            if "_hooklib" not in script.read_text(errors="replace"):
                continue
            if script.stem not in seen:
                problems.append(
                    f"{script.name} ({h['event']}) has not logged a single run across "
                    f"{len(sessions)} sessions; it is configured but not running"
                )

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state_path.write_text(json.dumps({"last_check": now}))
    except OSError:
        pass

    if not problems:
        hook.skip(f"{len(hooks)} hooks healthy")

    unique = list(dict.fromkeys(problems))
    emit({
        "systemMessage": f"clo-author hook health: {len(unique)} problem(s). " + unique[0]
                         + (" (more in context)" if len(unique) > 1 else ""),
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "Hook health check found problems. Each one means a check or automation "
                "this project relies on is not running. Mention them to the user before "
                "other work:\n" + "\n".join(f"- {p}" for p in unique)
            ),
        },
    })
    hook.acted(f"{len(unique)} problem(s)")


if __name__ == "__main__":
    run("hook-health", body)
