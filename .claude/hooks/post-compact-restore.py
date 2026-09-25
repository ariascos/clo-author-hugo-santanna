#!/usr/bin/env python3
"""
Post-Compact Context Restoration Hook

Fires on SessionStart when the session resumes or has just been compacted
(payload field `source` is "compact" or "resume"). Prints where the work
stands so Claude can continue without re-deriving it. SessionStart stdout is
added to Claude's context, so the output is plain text with no terminal
escape codes.

Sources, in order: the state pre-compact.py saved, the active plan in
quality_reports/plans/, quality_reports/pipeline_state.json, and the latest
SESSION_REPORT.md entry.

Hook Event: SessionStart (matcher: "compact|resume")
Returns: Exit 0 with plain-text stdout (added to Claude's context); exit 1 on error
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hooklib import run  # noqa: E402


def get_session_dir() -> Path:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not project_dir:
        return Path.home() / ".claude" / "sessions" / "default"
    project_hash = hashlib.md5(project_dir.encode()).hexdigest()[:8]
    return Path.home() / ".claude" / "sessions" / project_hash


def read_pre_compact_state() -> dict | None:
    """Read and delete the state file pre-compact.py wrote."""
    state_file = get_session_dir() / "pre-compact-state.json"
    if not state_file.exists():
        return None
    try:
        state = json.loads(state_file.read_text())
        state_file.unlink()
        return state
    except (json.JSONDecodeError, OSError):
        return None


def find_active_plan(project_dir: Path) -> dict | None:
    """Most recent plan that is not marked COMPLETED."""
    plans_dir = project_dir / "quality_reports" / "plans"
    if not plans_dir.exists():
        return None
    plan_files = sorted(plans_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    for plan_file in plan_files[:3]:
        content = plan_file.read_text(errors="replace")
        if "COMPLETED" in content.upper():
            continue
        next_task = None
        for line in content.splitlines():
            if "- [ ]" in line:
                next_task = line.replace("- [ ]", "").strip()
                break
        return {"path": str(plan_file.relative_to(project_dir)), "next_task": next_task}
    return None


def summarize_pipeline_state(project_dir: Path) -> list[str]:
    path = project_dir / "quality_reports" / "pipeline_state.json"
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return [f"  {path.relative_to(project_dir)} exists but could not be parsed"]
    lines = []
    if state.get("phase"):
        lines.append(f"  Phase: {state['phase']}")
    done = [a.get("agent") for a in state.get("agents_completed", []) if a.get("agent")]
    if done:
        lines.append(f"  Completed: {', '.join(done)}")
    active = [a.get("agent") for a in state.get("agents_in_progress", []) if a.get("agent")]
    if active:
        lines.append(f"  In progress: {', '.join(active)}")
    if state.get("agents_pending"):
        lines.append(f"  Pending: {', '.join(state['agents_pending'])}")
    if state.get("blocked_by"):
        lines.append(f"  Blocked by: {state['blocked_by']}")
    if state.get("overall_score") is not None:
        lines.append(f"  Overall score: {state['overall_score']}")
    return lines


def latest_session_entry(project_dir: Path) -> list[str]:
    """Heading and Status block of the newest SESSION_REPORT.md entry."""
    path = project_dir / "SESSION_REPORT.md"
    if not path.exists():
        return []
    text = path.read_text(errors="replace")
    entries = re.split(r"(?m)^## ", text)
    if len(entries) < 2:
        return []
    entry = entries[-1]
    heading = entry.splitlines()[0].strip()
    lines = [f"  Latest entry: {heading}"]
    status = re.search(r"\*\*Status:\*\*\s*\n((?:\s*-.*\n?)+)", entry)
    if status:
        lines += ["  " + ln.strip() for ln in status.group(1).strip().splitlines()]
    return lines


def body(hook) -> None:
    source = hook.require("source")
    if source not in ("compact", "resume"):
        hook.skip(f"source={source}")
    root = hook.project_dir()

    saved = read_pre_compact_state()
    plan = find_active_plan(root)
    pipeline = summarize_pipeline_state(root)
    session = latest_session_entry(root)

    if not (saved or plan or pipeline or session):
        hook.skip("no plan, pipeline state, or session report to restore")

    out = [f"[Context restored after {source}]"]
    if plan:
        out.append(f"Active plan: {plan['path']}")
        if plan["next_task"]:
            out.append(f"  Next unchecked task: {plan['next_task']}")
    if saved and saved.get("decisions"):
        out.append("Decisions recorded before compaction:")
        out += [f"  - {d}" for d in saved["decisions"][-3:]]
    if pipeline:
        out.append("Pipeline state (quality_reports/pipeline_state.json):")
        out += pipeline
    if session:
        out.append("SESSION_REPORT.md:")
        out += session
    out.append("Read the active plan and check `git status` before continuing.")
    print("\n".join(out))
    hook.acted(f"restored after {source}")


if __name__ == "__main__":
    run("post-compact-restore", body)
