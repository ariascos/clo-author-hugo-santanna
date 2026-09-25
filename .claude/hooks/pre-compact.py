#!/usr/bin/env python3
"""
Pre-Compact State Capture Hook

Fires before context compaction to capture the current state:
- Active plan path and status
- Current task description
- Recent decisions from the latest SESSION_REPORT.md entry

This state is read by post-compact-restore.py after compaction.

Hook Event: PreCompact
Returns: Exit 0; the checklist as systemMessage, shown to the user (stderr on
exit 0 goes only to the debug log). Never blocks compaction.
"""

from __future__ import annotations

import json
import os
import sys
import re
from pathlib import Path
from datetime import datetime
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hooklib import emit, run  # noqa: E402



def get_session_dir() -> Path:
    """Get the session directory for storing state files."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not project_dir:
        return Path.home() / ".claude" / "sessions" / "default"

    project_hash = hashlib.md5(project_dir.encode()).hexdigest()[:8]
    session_dir = Path.home() / ".claude" / "sessions" / project_hash
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def find_active_plan(project_dir: str) -> dict | None:
    """Find the most recent non-completed plan."""
    plans_dir = Path(project_dir) / "quality_reports" / "plans"
    if not plans_dir.exists():
        return None

    plan_files = sorted(plans_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)

    for plan_file in plan_files[:3]:  # Check last 3 plans
        content = plan_file.read_text()

        # Skip completed plans
        if "COMPLETED" in content.upper():
            continue

        # Extract status
        status = "in_progress"
        if "APPROVED" in content.upper():
            status = "approved"
        elif "DRAFT" in content.upper():
            status = "draft"

        # Find current task (first unchecked item)
        current_task = None
        for line in content.split("\n"):
            if "- [ ]" in line:
                current_task = line.replace("- [ ]", "").strip()
                break

        return {
            "plan_path": str(plan_file),
            "plan_name": plan_file.name,
            "status": status,
            "current_task": current_task
        }

    return None


def extract_recent_decisions(project_dir: str, limit: int = 3) -> list[str]:
    """Bullets under **Decisions:** in the newest SESSION_REPORT.md entry."""
    report = Path(project_dir) / "SESSION_REPORT.md"
    if not report.exists():
        return []
    entries = re.split(r"(?m)^## ", report.read_text(errors="replace"))
    if len(entries) < 2:
        return []
    block = re.search(r"\*\*Decisions:\*\*\s*\n((?:\s*-.*\n?)+)", entries[-1])
    if not block:
        return []
    bullets = [ln.strip()[1:].strip() for ln in block.group(1).splitlines() if ln.strip().startswith("-")]
    return [b[:160] for b in bullets[-limit:]]


def save_state(state: dict) -> None:
    """Save state to the session directory."""
    state_file = get_session_dir() / "pre-compact-state.json"
    state["timestamp"] = datetime.now().isoformat()

    try:
        state_file.write_text(json.dumps(state, indent=2))
    except IOError as e:
        print(f"Warning: Could not save pre-compact state: {e}", file=sys.stderr)


def format_compaction_message(plan_info: dict | None, decisions: list[str]) -> str:
    """Format the pre-compaction message."""
    lines = []
    lines.append(f"\nContext compaction starting")
    lines.append("")

    # Context survival checklist (merged from pre-compact.sh)
    lines.append(f"Context Survival Checklist:")
    lines.append("  [ ] Active plan saved to quality_reports/plans/")
    lines.append("  [ ] SESSION_REPORT.md updated")
    lines.append("  [ ] Open questions documented")
    lines.append("")

    if plan_info:
        lines.append(f"Current state saved:")
        lines.append(f"  Plan: {plan_info['plan_name']} ({plan_info['status']})")
        if plan_info.get("current_task"):
            lines.append(f"  Next task: {plan_info['current_task']}")

    if decisions:
        lines.append("")
        lines.append(f"Recent decisions captured:")
        for d in decisions:
            lines.append(f"  • {d[:80]}...")

    lines.append("")
    lines.append(f"State will be restored after compaction.")
    lines.append("")

    return "\n".join(lines)


def body(hook) -> None:
    trigger = hook.payload.get("trigger", "auto")
    project_dir = str(hook.project_dir())

    plan_info = find_active_plan(project_dir)
    decisions = extract_recent_decisions(project_dir)

    save_state({
        "trigger": trigger,
        "plan_path": plan_info["plan_path"] if plan_info else None,
        "plan_status": plan_info["status"] if plan_info else None,
        "current_task": plan_info.get("current_task") if plan_info else None,
        "decisions": decisions,
    })

    emit({"systemMessage": format_compaction_message(plan_info, decisions).strip()})
    hook.acted(f"state saved ({trigger})")


if __name__ == "__main__":
    run("pre-compact", body)
