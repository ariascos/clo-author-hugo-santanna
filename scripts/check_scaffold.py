#!/usr/bin/env python3
"""
check_scaffold.py — integrity checks for the .claude/ scaffold itself.

clo-author: infrastructure (not analysis code; explainer_status.py skips it)

The scaffold is prose that points at other prose, scripts, and settings. When
one side moves and the other doesn't, nothing fails: a rule names an agent
that no longer exists, a hook points at a deleted file, two files disagree on
a weight. This script makes that drift a commit-time failure. The pre-commit
gate runs it.

Checks:
  frontmatter   agents have name + description; skills have description
  tools         agent `tools:` entries are real tools; Agent(...) rosters name real agents;
                skills that list Task also list Agent (its current name)
  paths         backticked .claude/ scripts/ templates/ paths in the scaffold exist
  registry      every agent in permissions.md has an agent file
  weights       permissions.md QUALITY_WEIGHT agrees with quality-gates.json
  settings      settings.json parses; every hook command points at a file
  hooks         no hook reads CLAUDE_TOOL_* env vars (Claude Code never sets them)
  size          SKILL.md under 500 lines; always-loaded rules within budget

Usage:
    python3 scripts/check_scaffold.py          # exit 1 on any ERROR
    python3 scripts/check_scaffold.py --quiet  # print only problems
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline  # noqa: E402

KNOWN_TOOLS = {
    "Read", "Write", "Edit", "MultiEdit", "Bash", "Grep", "Glob", "WebSearch", "WebFetch",
    "Task", "Agent", "Skill", "NotebookEdit", "TodoWrite", "AskUserQuestion", "LSP", "Monitor",
}
SKILL_MAX_LINES = 500
# Lines of CLAUDE.md plus every .claude/rules/*.md without `paths:` frontmatter. Everything here
# loads into every session, and Claude Code's docs put the adherence limit near 200 lines per file.
ALWAYS_LOADED_BUDGET = 700
PATH_RE = re.compile(r"`((?:\.claude|scripts|templates)/[^`\s]+)`")

Problem = Tuple[str, str, str]  # (level, check, message)


def frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    out, key = {}, None
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if kv:
            key = kv.group(1)
            out[key] = kv.group(2).strip()
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def check(root: Path) -> List[Problem]:
    probs: List[Problem] = []
    claude = root / ".claude"

    # frontmatter + tools
    for agent in sorted((claude / "agents").glob("*.md")):
        fm = frontmatter(agent.read_text(errors="replace"))
        rel = agent.relative_to(root)
        for key in ("name", "description"):
            if not fm.get(key) or fm.get(key) == ">":
                probs.append(("ERROR", "frontmatter", f"{rel}: missing '{key}'"))
        tools_field = fm.get("tools", "")
        roster = re.search(r"\bAgent\(([^)]*)\)", tools_field)
        if roster:
            for name in [n.strip() for n in roster.group(1).split(",") if n.strip()]:
                if not (claude / "agents" / f"{name}.md").exists():
                    probs.append(("ERROR", "tools", f"{rel}: Agent({name}) names an agent with no file"))
        for tool in re.split(r",\s*(?![^()]*\))", tools_field):
            base = re.sub(r"\(.*\)$", "", tool.strip())
            if base and base not in KNOWN_TOOLS and not base.startswith("mcp__"):
                probs.append(("ERROR", "tools", f"{rel}: unknown tool '{tool.strip()}'"))
        if fm.get("effort") and fm["effort"] not in ("low", "medium", "high", "xhigh", "max"):
            probs.append(("ERROR", "frontmatter", f"{rel}: effort '{fm['effort']}' is not low/medium/high/xhigh/max"))
    for skill in sorted((claude / "skills").glob("*/SKILL.md")):
        text = skill.read_text(errors="replace")
        fm = frontmatter(text)
        rel = skill.relative_to(root)
        if not fm.get("description"):
            probs.append(("ERROR", "frontmatter", f"{rel}: missing 'description'"))
        n = text.count("\n") + 1
        if n > SKILL_MAX_LINES:
            probs.append(("ERROR", "size", f"{rel}: {n} lines (limit {SKILL_MAX_LINES}; move detail into reference files)"))
        tools = fm.get("allowed-tools", "")
        if re.search(r"\bTask\b", tools) and not re.search(r"\bAgent\b", tools):
            probs.append(("ERROR", "tools", f"{rel}: allowed-tools has Task but not Agent (Task is the old name)"))

    # paths referenced from the scaffold
    sources = [root / "CLAUDE.md"] + sorted(claude.rglob("*.md"))
    for src in sources:
        if not src.exists() or "archive" in src.parts:
            continue
        for i, line in enumerate(src.read_text(errors="replace").splitlines(), start=1):
            for ref in PATH_RE.findall(line):
                if re.search(r"[{}\[\]*<>$]|YYYY|\.\.\.", ref):
                    continue  # a pattern or placeholder, not a concrete path
                target = ref.split("#")[0].split(":")[0].rstrip(".,;)")
                if target.startswith(".claude/state/"):
                    continue  # runtime state, created on first use and gitignored
                if target.startswith("scripts/") and target.count("/") > 1:
                    continue  # an example analysis path in a user project, not scaffold code
                skill_dir = next((p for p in src.parents if p.parent.name == "skills"), None)
                candidates = [root / target] + ([skill_dir / target] if skill_dir else [])
                if not any(c.exists() for c in candidates):
                    probs.append(("ERROR", "paths", f"{src.relative_to(root)}:{i} points at missing `{target}`"))

    # registry
    registry = pipeline.parse_registry(root)
    for name in registry:
        if not (claude / "agents" / f"{name}.md").exists():
            probs.append(("ERROR", "registry", f"permissions.md registers '{name}' but .claude/agents/{name}.md is missing"))

    # weights
    gates_path = claude / "skills" / "new-project" / "config" / "quality-gates.json"
    try:
        comps = json.loads(gates_path.read_text())["components"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        probs.append(("ERROR", "weights", f"{gates_path.relative_to(root)} unreadable: {exc}"))
        comps = {}
    for comp, spec in comps.items():
        src = spec["source"]
        owners = [n for n, e in registry.items()
                  if (n == src or e.get("CRITIC", "").startswith(src))
                  and re.match(r"\s*[\d.]+%", e.get("QUALITY_WEIGHT", ""))]
        if not owners:
            probs.append(("ERROR", "weights", f"component '{comp}' ({src}) has no QUALITY_WEIGHT % in permissions.md"))
            continue
        declared = float(re.match(r"\s*([\d.]+)%", registry[owners[0]]["QUALITY_WEIGHT"]).group(1))
        if abs(declared - float(spec["weight"])) > 1e-9:
            probs.append(("ERROR", "weights", f"'{comp}': permissions.md says {declared:g}%, quality-gates.json says {spec['weight']:g}%"))

    # settings + hooks
    for name in ("settings.json", "settings.local.json"):
        path = claude / name
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            probs.append(("ERROR", "settings", f".claude/{name} is not valid JSON: {exc.msg}"))
            continue
        for event, groups in settings.get("hooks", {}).items():
            for group in groups:
                for h in group.get("hooks", []):
                    m = re.search(r"\.claude/hooks/([^\s\"']+)", h.get("command", ""))
                    if m and not (claude / "hooks" / m.group(1)).exists():
                        probs.append(("ERROR", "settings", f".claude/{name} {event} hook points at missing .claude/hooks/{m.group(1)}"))
    for hook in sorted((claude / "hooks").glob("*")):
        if hook.is_file() and re.search(r"CLAUDE_TOOL_[A-Z_]+", hook.read_text(errors="replace")):
            probs.append(("ERROR", "hooks", f"{hook.relative_to(root)} reads CLAUDE_TOOL_* env vars; hook input arrives as JSON on stdin"))

    # always-loaded budget
    total = (root / "CLAUDE.md").read_text(errors="replace").count("\n") if (root / "CLAUDE.md").exists() else 0
    for rule in sorted((claude / "rules").glob("*.md")):
        text = rule.read_text(errors="replace")
        if "paths" not in frontmatter(text):
            total += text.count("\n")
    level = "ERROR" if total > ALWAYS_LOADED_BUDGET else "INFO"
    probs.append((level, "size", f"always-loaded instructions: {total} lines (budget {ALWAYS_LOADED_BUDGET})"))
    return probs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Integrity checks for the clo-author scaffold.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    probs = check(Path(args.root).resolve())
    errors = [p for p in probs if p[0] == "ERROR"]
    for level, name, msg in probs:
        if args.quiet and level == "INFO":
            continue
        print(f"{level:<5} {name:<11} {msg}")
    print(f"check_scaffold: {len(errors)} error(s), {sum(p[0] == 'WARN' for p in probs)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
