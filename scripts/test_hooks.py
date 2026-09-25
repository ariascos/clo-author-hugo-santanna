#!/usr/bin/env python3
"""
Smoke tests for the Claude Code hooks in .claude/hooks/.

Each hook is fed a synthetic payload in a throwaway project directory and
checked for the three outcomes the hooks promise: it acts when it should,
stays silent when there is nothing to do, and fails visibly (exit 1, one line
on stderr, an "error" log entry) when the payload is not what it expects.
The last case is the one that matters most: two hooks once exited cleanly for
months because they read a field Claude Code never sends.

Usage:
    python3 scripts/test_hooks.py          # run all tests, exit 1 on any failure
    python3 scripts/test_hooks.py -v       # also print passing tests
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / ".claude" / "hooks"
VERBOSE = "-v" in sys.argv
failures: list[str] = []


def run_hook(name: str, payload, project: Path, raw: str | None = None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "HOME": str(project / "_home")}
    stdin = raw if raw is not None else json.dumps(payload)
    proc = subprocess.run(
        [sys.executable, str(HOOKS / name)], input=stdin,
        capture_output=True, text=True, env=env, timeout=20,
    )
    return proc.returncode, proc.stdout, proc.stderr


def last_log(project: Path) -> dict:
    path = project / ".claude" / "state" / "hook-log.jsonl"
    lines = path.read_text().splitlines() if path.exists() else []
    return json.loads(lines[-1]) if lines else {}


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        if VERBOSE:
            print(f"  ok    {label}")
    else:
        failures.append(f"{label}  {detail}")
        print(f"  FAIL  {label}  {detail}")


def new_project() -> Path:
    root = Path(tempfile.mkdtemp(prefix="clo-hooktest-"))
    (root / ".claude" / "state").mkdir(parents=True)
    (root / "_home").mkdir()
    return root


def expect_error(label: str, name: str, payload, raw: str | None = None) -> None:
    p = new_project()
    code, out, err = run_hook(name, payload, p, raw)
    check(f"{label}: exits 1", code == 1, f"(got {code})")
    check(f"{label}: one-line stderr naming the hook", err.startswith(f"clo-author hook "), repr(err[:120]))
    check(f"{label}: logged as error", last_log(p).get("outcome") == "error", str(last_log(p)))


# ---------------------------------------------------------------------------

def test_post_edit_lint() -> None:
    print("post-edit-lint.py")
    p = new_project()
    script = p / "scripts" / "a.R"
    script.parent.mkdir()
    script.write_text('setwd("/Users/x")\nlibrary(dplyr)\n')
    code, out, _ = run_hook("post-edit-lint.py", {"hook_event_name": "PostToolUse", "tool_input": {"file_path": str(script)}}, p)
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"] if out.strip() else ""
    check("findings reach Claude as additionalContext", code == 0 and "setwd" in ctx, out[:200])

    clean = p / "scripts" / "b.R"
    clean.write_text("library(here)\nx <- 1\n")
    code, out, _ = run_hook("post-edit-lint.py", {"tool_input": {"file_path": str(clean)}}, p)
    check("clean script: silent, logged as acted", code == 0 and not out.strip() and last_log(p).get("outcome") == "acted")

    code, out, _ = run_hook("post-edit-lint.py", {"tool_input": {"file_path": str(p / "notes.txt")}}, p)
    check("non-script: silent skip", code == 0 and not out.strip() and last_log(p).get("outcome") == "skipped")

    expect_error("missing tool_input.file_path", "post-edit-lint.py", {"tool_input": {}})
    expect_error("empty payload", "post-edit-lint.py", None, raw="")


def test_protect_files() -> None:
    print("protect-files.py")
    p = new_project()
    code, out, _ = run_hook("protect-files.py", {"tool_name": "Edit", "tool_input": {"file_path": str(p / ".claude" / "settings.json")}}, p)
    decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out.strip() else ""
    check("settings.json edit denied", code == 0 and decision == "deny", out[:200])

    code, out, _ = run_hook("protect-files.py", {"tool_name": "Write", "tool_input": {"file_path": str(p / "scripts" / "a.R")}}, p)
    check("ordinary file: silent skip", code == 0 and not out.strip())

    expect_error("Edit without file_path", "protect-files.py", {"tool_name": "Edit", "tool_input": {}})
    expect_error("no tool_name", "protect-files.py", {"tool_input": {"file_path": "x"}})


def test_session_guard() -> None:
    print("session-guard.py")
    p = new_project()
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(p / "scripts" / "x.R")}}
    code, out, _ = run_hook("session-guard.py", payload, p)
    check("no guards: silent skip", code == 0 and not out.strip() and last_log(p).get("outcome") == "skipped")

    guards = p / ".claude" / "state" / "session-guards.json"
    guards.write_text(json.dumps({"freeze": {"active": True, "allowed_paths": ["paper/"]}}))
    code, out, _ = run_hook("session-guard.py", payload, p)
    decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out.strip() else ""
    check("freeze: write outside allowed path denied", code == 0 and decision == "deny", out[:200])

    code, out, _ = run_hook("session-guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(p / "paper" / "x.tex")}}, p)
    check("freeze: write inside allowed path passes", code == 0 and not out.strip())

    guards.write_text(json.dumps({"careful": {"active": True}}))
    code, out, _ = run_hook("session-guard.py", {"tool_name": "Bash", "tool_input": {"command": "rm -rf data"}}, p)
    check("careful: rm -rf denied", code == 0 and '"deny"' in out, out[:200])

    guards.write_text("{not json")
    code, _, err = run_hook("session-guard.py", payload, p)
    check("corrupt guards file: visible error, not silent pass", code == 1 and "NOT being enforced" in err, err[:200])

    expect_error("no tool_input", "session-guard.py", {"tool_name": "Write"})


def test_compaction_pair() -> None:
    print("pre-compact.py / post-compact-restore.py")
    p = new_project()
    (p / "quality_reports" / "plans").mkdir(parents=True)
    (p / "quality_reports" / "plans" / "2026-09-25_x.md").write_text("# Plan\nStatus: APPROVED\n- [x] a\n- [ ] Build score.py\n")
    (p / "quality_reports" / "pipeline_state.json").write_text(json.dumps({"phase": "Execution", "agents_completed": [{"agent": "strategist"}]}))
    (p / "SESSION_REPORT.md").write_text("# Session Report\n\n## 2026-09-25 10:00 - Coder\n\n**Decisions:**\n- Cluster at state - policy varies by state\n\n**Status:**\n- Pending: robustness\n")

    code, out, _ = run_hook("pre-compact.py", {"hook_event_name": "PreCompact", "trigger": "auto"}, p)
    msg = json.loads(out).get("systemMessage", "") if out.strip() else ""
    check("pre-compact: checklist shown to the user via systemMessage", code == 0 and "Context Survival Checklist" in msg, out[:200])

    code, out, _ = run_hook("post-compact-restore.py", {"hook_event_name": "SessionStart", "source": "compact"}, p)
    check("restore: prints plan, decision, pipeline, status", code == 0 and all(
        s in out for s in ("Build score.py", "Cluster at state", "Phase: Execution", "Pending: robustness")), out[:300])
    check("restore: no terminal escape codes in model context", "\x1b" not in out)

    code, out, _ = run_hook("post-compact-restore.py", {"source": "startup"}, p)
    check("restore: silent on a fresh start", code == 0 and not out.strip())

    expect_error("restore without 'source'", "post-compact-restore.py", {"hook_event_name": "SessionStart"})


def test_hook_health() -> None:
    print("hook-health.py")
    p = new_project()
    hooks_dir = p / ".claude" / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "live.py").write_text("from _hooklib import run\n")
    settings = {"hooks": {
        "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/live.py'}]}],
    }}
    (p / ".claude" / "settings.json").write_text(json.dumps(settings))

    code, out, _ = run_hook("hook-health.py", {"hook_event_name": "SessionStart", "source": "startup"}, p)
    check("healthy project: silent", code == 0 and not out.strip(), out[:200])

    settings["hooks"]["PreToolUse"] = [{"matcher": "Bash", "hooks": [{"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/gone.py'}]}]
    (p / ".claude" / "settings.json").write_text(json.dumps(settings))
    code, out, _ = run_hook("hook-health.py", {"source": "startup"}, p)
    check("missing hook file reported to the user", code == 0 and "missing file" in out and "systemMessage" in out, out[:200])
    del settings["hooks"]["PreToolUse"]
    (p / ".claude" / "settings.json").write_text(json.dumps(settings))

    log = p / ".claude" / "state" / "hook-log.jsonl"
    with log.open("a") as fh:
        fh.write(json.dumps({"ts": "2999-01-01T00:00:00+00:00", "hook": "live", "outcome": "error", "detail": "boom", "session": "s0"}) + "\n")
    code, out, _ = run_hook("hook-health.py", {"source": "startup"}, p)
    check("errors since last check reported", "live failed 1 time" in out and "boom" in out, out[:200])

    log.write_text("".join(json.dumps({"ts": "2000-01-01T00:00:00+00:00", "hook": "other", "outcome": "skipped", "session": f"s{i}"}) + "\n" for i in range(3)))
    code, out, _ = run_hook("hook-health.py", {"source": "startup"}, p)
    check("configured-but-never-run hook reported", "live.py" in out and "not running" in out, out[:300])


def test_real_settings_resolve() -> None:
    print(".claude/settings.json")
    code, out, _ = run_hook("hook-health.py", {"source": "startup"}, REPO_COPY)
    check("every hook in the real settings.json points at an existing file", "missing file" not in out and "not executable" not in out, out[:300])


if __name__ == "__main__":
    # Point the real-settings check at a scratch copy so it never writes state into the repo.
    REPO_COPY = new_project()
    (REPO_COPY / ".claude" / "settings.json").write_text((REPO / ".claude" / "settings.json").read_text())
    os.symlink(HOOKS, REPO_COPY / ".claude" / "hooks")

    for test in (test_post_edit_lint, test_protect_files, test_session_guard,
                 test_compaction_pair, test_hook_health, test_real_settings_resolve):
        test()
    total = "all hook tests passed" if not failures else f"{len(failures)} hook test(s) FAILED"
    print(total)
    sys.exit(1 if failures else 0)
