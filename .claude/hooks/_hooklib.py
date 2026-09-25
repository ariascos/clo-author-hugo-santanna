"""Shared plumbing for clo-author's Claude Code hooks.

Every hook run ends in one of three outcomes, and every outcome is logged:

  acted    The hook did its job: printed context, blocked a tool, linted a file.
  skipped  Nothing to do here (a .txt edit, no active guard). Silent.
  error    The hook could not do its job. It exits 1 with a one-line message on
           stderr, which Claude Code shows in the transcript as
           "Failed with non-blocking status code: ...". The action proceeds:
           an error never blocks, because a broken guard that blocks every
           Edit would also block the edit that fixes it.

A payload that lacks a field the hook depends on is an error, not a skip.
Two hooks in this repo once sat dead for months because they read a field
Claude Code never sends, found it empty, and exited cleanly as if there were
nothing to do. `require()` turns that case into a visible failure.

The log is .claude/state/hook-log.jsonl (gitignored). hook_health.py reads it
at session start to report errors and hooks that are configured but never run.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_MAX_BYTES = 1_000_000
LOG_KEEP_LINES = 2_000


class HookError(Exception):
    """Raised inside a hook to fail with a specific message."""


class Hook:
    def __init__(self, name: str):
        self.name = name
        self.payload: dict = {}
        self._logged = False

    # -- input ---------------------------------------------------------------

    def read_payload(self) -> dict:
        raw = sys.stdin.read()
        if not raw.strip():
            raise HookError("received an empty payload on stdin")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HookError(f"payload is not valid JSON ({exc.msg})") from None
        if not isinstance(data, dict):
            raise HookError("payload is not a JSON object")
        self.payload = data
        return data

    def require(self, dotted: str):
        """Return payload[a][b]...; fail loudly if any key is missing."""
        node = self.payload
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                raise HookError(
                    f"payload has no '{dotted}' - the Claude Code hook contract "
                    f"may have changed; this hook cannot do its job"
                )
            node = node[key]
        return node

    def project_dir(self) -> Path:
        value = os.environ.get("CLAUDE_PROJECT_DIR") or self.payload.get("cwd")
        if not value:
            raise HookError("neither CLAUDE_PROJECT_DIR nor payload 'cwd' is set")
        return Path(value)

    # -- outcomes ------------------------------------------------------------

    def skip(self, reason: str) -> None:
        self.log("skipped", reason)
        sys.exit(0)

    def acted(self, detail: str = "") -> None:
        self.log("acted", detail)

    def fail(self, message: str) -> None:
        self.log("error", message)
        print(f"clo-author hook {self.name}: {message}", file=sys.stderr)
        sys.exit(1)

    # -- logging -------------------------------------------------------------

    def log(self, outcome: str, detail: str = "") -> None:
        if self._logged:
            return
        self._logged = True
        try:
            root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or self.payload.get("cwd") or ".")
            path = root / ".claude" / "state" / "hook-log.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "hook": self.name,
                "event": self.payload.get("hook_event_name", ""),
                "session": self.payload.get("session_id", ""),
                "outcome": outcome,
                "detail": detail[:300],
            }
            with path.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
            if path.stat().st_size > LOG_MAX_BYTES:
                lines = path.read_text().splitlines()[-LOG_KEEP_LINES:]
                path.write_text("\n".join(lines) + "\n")
        except OSError:
            # The log is diagnostics, not function; a read-only checkout
            # must not turn every hook run into an error.
            pass


def emit(obj: dict) -> None:
    """Print one JSON object on stdout (the only thing a hook may print there)."""
    print(json.dumps(obj))


def run(name: str, body) -> None:
    """Run body(hook); turn any failure into a logged, visible, non-blocking error."""
    hook = Hook(name)
    try:
        hook.read_payload()
        body(hook)
        hook.acted()  # no-op if body already logged a more specific outcome
        sys.exit(0)
    except SystemExit:
        raise
    except HookError as exc:
        hook.fail(str(exc))
    except Exception as exc:  # a bug in the hook itself
        hook.fail(f"crashed with {type(exc).__name__}: {exc}")
