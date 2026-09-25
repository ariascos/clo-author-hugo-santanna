#!/usr/bin/env python3
"""
pipeline.py — dispatch checks and pipeline state, derived from the registry.

clo-author: infrastructure (not analysis code; explainer_status.py skips it)

The orchestrator used to do this bookkeeping by hand on every dispatch: glob
the REQUIRES paths, look up critic scores, check section headings, and keep
pipeline_state.json current. The inputs fully determine the answer, so it is
code now. .claude/rules/permissions.md stays the single registry; this script
parses it, and scripts/journal.py supplies the critic results.

Subcommands:
    check-pre  <agent> [--project P] [--script S]   Can this agent be dispatched?
    check-post <agent> [--project P] [--script S]   Did it produce what it declares?
    status     [--project P]                        Write quality_reports/pipeline_state.json
    traces                                          Per-agent rounds and first-pass scores

check-pre/check-post exit 0 when every checkable condition passes, 1 when one
fails, and print MANUAL for conditions that need judgment (e.g. "Research idea
or research spec") so nothing is silently treated as satisfied.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import journal  # noqa: E402
import score  # noqa: E402

REGISTRY = Path(".claude") / "rules" / "permissions.md"
STATE = Path("quality_reports") / "pipeline_state.json"

PASS, FAIL, MANUAL = "PASS", "FAIL", "MANUAL"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def parse_registry(root: Path) -> Dict[str, dict]:
    """Agent name -> {KEY: value, 'produces_files': [...], 'produces_sections': {...}}."""
    text = (root / REGISTRY).read_text(encoding="utf-8")
    agents: Dict[str, dict] = {}
    names: List[str] = []
    last_key = ""
    for line in text.splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            names = [n.strip() for n in h.group(1).split("/")]
            if any(not re.fullmatch(r"[a-z][a-z0-9-]*", n) for n in names):
                names = []  # a prose section such as "Parallel Groups"
                continue
            for n in names:
                agents[n] = {"produces_files": [], "produces_sections": {}}
            continue
        if not names:
            continue
        f = re.match(r"^- \*\*([A-Z_]+):\*\*\s*(.*)$", line)
        if f:
            last_key = f.group(1)
            for n in names:
                agents[n][last_key] = f.group(2).strip()
            continue
        sub = re.match(r"^\s+- Required files:\s*(.+)$", line)
        if sub and last_key == "PRODUCES":
            files = re.findall(r"`([^`]+)`", sub.group(1))
            for n in names:
                agents[n]["produces_files"] = files
            continue
        sub = re.match(r"^\s+- Required sections(?:\s*\(([^)]+)\))?:\s*(.+)$", line)
        if sub and last_key == "PRODUCES":
            which = sub.group(1) or ""
            sections = [s.strip() for s in sub.group(2).split(",") if s.strip()]
            for n in names:
                agents[n]["produces_sections"][which] = sections
    return agents


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

class Context:
    def __init__(self, root: Path, project: Optional[str], script: Optional[str]):
        self.root = root
        self.project = project
        self.script = script
        self.latest = journal.latest_by_agent(journal.parse(root / journal.JOURNAL))
        self._score = None

    def fill(self, path: str) -> Tuple[Optional[str], str]:
        """Substitute {project}/{script}; infer {project} when exactly one candidate exists."""
        if "{script}" in path:
            if not self.script:
                return None, "needs --script"
            path = path.replace("{script}", Path(self.script).stem)
        if "{project}" in path:
            project = self.project
            if not project:
                parent = self.root / path.split("{project}")[0]
                subdirs = [d.name for d in parent.iterdir() if d.is_dir()] if parent.is_dir() else []
                if len(subdirs) == 1:
                    project = subdirs[0]
                else:
                    return None, "needs --project" + (f" (candidates: {', '.join(subdirs)})" if subdirs else "")
            path = path.replace("{project}", project)
        other = re.search(r"\{[a-z_]+\}", path)
        if other:
            return None, f"has placeholder {other.group(0)} this script cannot fill"
        return path, ""

    def overall(self) -> dict:
        if self._score is None:
            self._score = score.compute(self.root)
        return self._score


def exists(ctx: Context, rel: str) -> bool:
    p = ctx.root / rel
    if rel.endswith("/"):
        return p.is_dir() and any(p.iterdir())
    return p.exists()


def eval_clause(ctx: Context, text: str) -> Tuple[str, str]:
    t = text.strip()

    m = re.match(r"^([a-z-]+?)\s+score\s*>=\s*(\d+)", t)
    if m:
        agent, need = m.group(1), float(m.group(2))
        e = ctx.latest.get(agent)
        if e is None or e.score is None:
            return FAIL, f"{agent} has no score in the research journal"
        return (PASS if e.score >= need else FAIL), f"{agent} score {e.score:g} (needs >= {need:g})"

    m = re.match(r"^([a-z-]+-critic)\s+verdict\s+(.+)$", t)
    if m:
        agent = m.group(1)
        allowed = [v.strip().upper() for v in re.split(r",|\bor\b", m.group(2)) if v.strip()]
        e = ctx.latest.get(agent)
        if e is None or not e.verdict:
            return FAIL, f"{agent} has no verdict in the research journal"
        return (PASS if e.verdict in allowed else FAIL), f"{agent} verdict {e.verdict} (needs {' or '.join(allowed)})"

    m = re.match(r"^overall score\s*>=\s*(\d+)", t, re.IGNORECASE)
    if m:
        o = ctx.overall()["overall"]
        need = float(m.group(1))
        return (PASS if o is not None and o >= need else FAIL), f"overall {o} (needs >= {need:g})"

    m = re.match(r"^all components\s*>=\s*(\d+)", t, re.IGNORECASE)
    if m:
        need = float(m.group(1))
        low = [r["component"] for r in ctx.overall()["components"] if r["score"] is not None and r["score"] < need]
        return (FAIL if low else PASS), (f"below {need:g}: {', '.join(low)}" if low else f"all scored components >= {need:g}")

    paths = re.findall(r"`([^`]+)`", t)
    if paths:
        target, why = ctx.fill(paths[0])
        if target is None:
            return MANUAL, f"`{paths[0]}` {why}"
        if "contains" in t and len(paths) > 1 and paths[1].startswith("."):
            hits = list((ctx.root / target).rglob(f"*{paths[1]}")) if (ctx.root / target).is_dir() else []
            return (PASS if hits else FAIL), f"`{target}` has {len(hits)} {paths[1]} file(s)"
        if "contains the target script" in t:
            if ctx.script:
                ok = (ctx.root / ctx.script).exists()
                return (PASS if ok else FAIL), f"`{ctx.script}` {'exists' if ok else 'missing'}"
            return MANUAL, "pass --script to check the target script"
        ok = exists(ctx, target)
        return (PASS if ok else FAIL), f"`{target}` {'present' if ok else 'missing or empty'}"

    return MANUAL, t


def eval_requires(ctx: Context, text: str) -> List[Tuple[str, str]]:
    if " OR " in text:
        results = [eval_clause(ctx, c) for c in text.split(" OR ")]
        if any(s == PASS for s, _ in results):
            return [(PASS, "one of: " + " | ".join(m for _, m in results))]
        return results
    return [eval_clause(ctx, c) for c in text.split(" AND ")]


def check_post(ctx: Context, entry: dict) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    produces = entry.get("PRODUCES", "")
    paths = re.findall(r"`([^`]+)`", produces)
    if not paths:
        return [(MANUAL, produces or "no PRODUCES declared")]
    base_dir = None
    for raw in paths:
        target, why = ctx.fill(raw)
        if target is None:
            out.append((MANUAL, f"`{raw}` {why}"))
            continue
        if "*" in target:
            hits = list(ctx.root.glob(target))
            out.append(((PASS if hits else FAIL), f"`{target}`: {len(hits)} match(es)"))
            continue
        ok = exists(ctx, target)
        out.append(((PASS if ok else FAIL), f"`{target}` {'present' if ok else 'missing or empty'}"))
        if base_dir is None and target.endswith("/"):
            base_dir = target
    files = entry.get("produces_files", [])
    for f in files:
        name, why = ctx.fill(f)
        if name is None or base_dir is None:
            out.append((MANUAL, f"`{f}` {why or 'has no directory to check in'}"))
            continue
        ok = (ctx.root / base_dir / name).exists()
        out.append(((PASS if ok else FAIL), f"`{base_dir}{name}` {'present' if ok else 'missing'}"))
    for which, sections in entry.get("produces_sections", {}).items():
        doc = next((f for f in files if not which or which in f), files[0] if files else None)
        name, why = ctx.fill(doc) if doc else (None, "no file named for sections")
        if name is None or base_dir is None:
            out.append((MANUAL, f"sections {sections}: {why}"))
            continue
        path = ctx.root / base_dir / name
        if not path.exists():
            continue  # already reported missing above
        headings = [l.lower() for l in path.read_text(errors="replace").splitlines() if l.lstrip().startswith("#")]
        for sec in sections:
            ok = any(sec.lower() in h for h in headings)
            out.append(((PASS if ok else FAIL), f"`{name}` section '{sec}' {'present' if ok else 'missing'}"))
    return out


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def report(agent: str, stage: str, results: List[Tuple[str, str]]) -> int:
    print(f"{stage} {agent}")
    for status, msg in results:
        print(f"  {status:<6} {msg}")
    failed = [m for s, m in results if s == FAIL]
    if failed:
        verb = "dispatch" if stage == "check-pre" else "advance past"
        print(f"Cannot {verb} {agent}: {failed[0]}")
        return 1
    return 0


def cmd_status(ctx: Context, registry: Dict[str, dict]) -> dict:
    entries = journal.parse(ctx.root / journal.JOURNAL)
    by_agent = journal.rounds_by_agent(entries)
    s = ctx.overall()
    completed = []
    for agent, es in by_agent.items():
        last = es[-1]
        completed.append({"agent": agent, "score": last.score, "verdict": last.verdict,
                          "rounds": len(es), "report": last.fields.get("report", ""), "timestamp": last.when})
    ready, waiting = [], []
    for agent, entry in registry.items():
        if agent in by_agent or "REQUIRES" not in entry:
            continue
        results = eval_requires(ctx, entry["REQUIRES"])
        failed = [m for st, m in results if st == FAIL]
        (waiting if failed else ready).append(agent if not failed else {"agent": agent, "missing": failed[0]})
    failing_gate = next((g for g in s["gates"] if not g["passed"]), None)
    state = {
        "project": ctx.project or "",
        "phase": entries[-1].phase if entries else "",
        "last_updated": datetime.now().isoformat(timespec="seconds"),
        "agents_completed": completed,
        "agents_in_progress": [],
        "agents_pending": ready,
        "agents_waiting": waiting,
        "overall_score": s["overall"],
        "components": {r["component"]: r["score"] for r in s["components"]},
        "blocked_by": (f"{failing_gate['gate']} gate: " + "; ".join(failing_gate["reasons"])) if failing_gate else None,
        "derived_from": "quality_reports/research_journal.md via scripts/pipeline.py status",
    }
    path = ctx.root / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")
    return state


def cmd_traces(ctx: Context) -> str:
    by_agent = journal.rounds_by_agent(journal.parse(ctx.root / journal.JOURNAL))
    lines = ["| Agent | Rounds | First score | Last score | Flag |", "|---|---:|---:|---:|---|"]
    for agent, es in sorted(by_agent.items()):
        first, last = es[0].score, es[-1].score
        flag = ""
        if first is not None and first >= 90:
            flag = "HIGH-PERF"
        elif len(es) >= 3 and (last is None or last < 80):
            flag = "FRICTION"
        if any("ESCALAT" in (e.fields.get("verdict", "") + e.fields.get("score", "")).upper() for e in es):
            flag = (flag + " USER ESCALATION").strip()
        fmt = lambda v: "—" if v is None else f"{v:g}"
        lines.append(f"| {agent} | {len(es)} | {fmt(first)} | {fmt(last)} | {flag} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Registry-driven dispatch checks and pipeline state.")
    ap.add_argument("command", choices=("check-pre", "check-post", "status", "traces"))
    ap.add_argument("agent", nargs="?")
    ap.add_argument("--project")
    ap.add_argument("--script")
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    registry = parse_registry(root)
    ctx = Context(root, args.project, args.script)

    if args.command in ("check-pre", "check-post"):
        if not args.agent:
            ap.error(f"{args.command} needs an agent name")
        entry = registry.get(args.agent)
        if entry is None:
            print(f"Unknown agent '{args.agent}'. Registered: {', '.join(sorted(registry))}")
            return 2
        if args.command == "check-pre":
            return report(args.agent, "check-pre", eval_requires(ctx, entry.get("REQUIRES", "")))
        return report(args.agent, "check-post", check_post(ctx, entry))
    if args.command == "status":
        state = cmd_status(ctx, registry)
        print(json.dumps(state, indent=2))
        return 0
    print(cmd_traces(ctx))
    return 0


if __name__ == "__main__":
    sys.exit(main())
