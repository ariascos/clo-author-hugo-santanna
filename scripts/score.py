#!/usr/bin/env python3
"""
score.py — the weighted quality score and the commit / PR / submission gates.

clo-author: infrastructure (not analysis code; explainer_status.py skips it)

The arithmetic used to live in prose (quality.md) for the model to carry out,
from sources that disagreed. It lives here now:

  - Scores come from the latest research-journal entry of each critic
    (scripts/journal.py). Nothing is typed in twice.
  - Weights, the strategist verdict map, and gate thresholds come from
    .claude/skills/new-project/config/quality-gates.json.
  - Components that were never scored are excluded and the remaining weights
    renormalized; the report lists what was excluded, so a missing journal
    entry is visible rather than silently ignored.

Usage:
    python3 scripts/score.py                     # component table + every gate's status
    python3 scripts/score.py --gate submission   # exit 1 unless that gate passes
    python3 scripts/score.py --set coder-critic=85 --set strategist-critic="MINOR ISSUES"
    python3 scripts/score.py --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import journal  # noqa: E402

CONFIG = Path(".claude") / "skills" / "new-project" / "config" / "quality-gates.json"


def load_config(root: Path) -> dict:
    path = root / CONFIG
    if not path.exists():
        raise SystemExit(f"score.py: config not found: {path}")
    return json.loads(path.read_text())


def component_scores(cfg: dict, latest: Dict[str, "journal.Entry"], overrides: Dict[str, str]) -> List[dict]:
    rows = []
    verdict_map = cfg.get("verdict_scores", {})
    for name, comp in cfg["components"].items():
        src = comp["source"]
        row = {"component": name, "source": src, "weight": comp["weight"], "score": None,
               "verdict": "", "origin": "", "conditional": bool(comp.get("conditional"))}
        if src in overrides:
            raw = overrides[src].strip()
            if raw.upper() in verdict_map.get(src, {}):
                row["verdict"] = raw.upper()
                row["score"] = float(verdict_map[src][row["verdict"]])
            elif raw.upper() in ("PASS", "FAIL"):
                row["score"] = 100.0 if raw.upper() == "PASS" else 0.0
            else:
                row["score"] = float(raw)
            row["origin"] = "--set"
        elif src in latest:
            e = latest[src]
            if comp.get("scored_by") == "verdict" and e.verdict:
                row["verdict"] = e.verdict
                row["score"] = float(verdict_map[src][e.verdict])
            else:
                row["score"] = e.score
            row["origin"] = f"journal line {e.line} ({e.when})"
        rows.append(row)
    return rows


def aggregate(rows: List[dict]) -> Optional[float]:
    scored = [r for r in rows if r["score"] is not None]
    total_w = sum(r["weight"] for r in scored)
    if not scored or total_w == 0:
        return None
    for r in rows:
        r["used_weight"] = (r["weight"] / total_w * 100) if r["score"] is not None else 0.0
    return round(sum(r["score"] * r["weight"] for r in scored) / total_w, 1)


def evaluate_gate(name: str, gate: dict, overall: Optional[float], rows: List[dict], root: Path) -> dict:
    reasons = []
    if overall is None:
        reasons.append("no component has been scored yet")
    elif overall < gate["overall"]:
        reasons.append(f"overall {overall} < {gate['overall']}")
    if gate.get("require_all_scored"):
        unscored = [r["component"] for r in rows if r["score"] is None and not r.get("conditional")]
        if unscored:
            reasons.append("not yet scored: " + ", ".join(unscored))
    floor = gate.get("per_component")
    if floor is not None:
        for r in rows:
            if r["score"] is not None and r["score"] < floor:
                reasons.append(f"{r['component']} ({r['source']}) {r['score']:g} < {floor}")
    for cmd in gate.get("commands", []):
        proc = subprocess.run(cmd["command"], shell=True, cwd=root, capture_output=True, text=True)
        if proc.returncode != cmd.get("pass_on_exit", 0):
            first = (proc.stdout.strip().splitlines() or proc.stderr.strip().splitlines() or [""])[-1]
            reasons.append(f"{cmd['name']} gate failed (`{cmd['command']}`): {first[:160]}")
    return {"gate": name, "passed": not reasons, "reasons": reasons}


def render(rows: List[dict], overall: Optional[float], gates: List[dict]) -> str:
    out = ["| Component | Source | Weight | Used | Score | From |", "|---|---|---:|---:|---:|---|"]
    for r in rows:
        score = "—" if r["score"] is None else (f"{r['score']:g}" + (f" ({r['verdict']})" if r["verdict"] else ""))
        used = f"{r.get('used_weight', 0):.1f}%" if r["score"] is not None else "excluded"
        out.append(f"| {r['component']} | {r['source']} | {r['weight']:g}% | {used} | {score} | {r['origin'] or 'not scored'} |")
    out.append("")
    out.append(f"**Weighted Aggregate:** {overall if overall is not None else 'n/a'}")
    missing = [r["component"] for r in rows if r["score"] is None]
    if missing:
        out.append(f"Excluded (not scored): {', '.join(missing)}")
    out.append("")
    for g in gates:
        status = "PASS" if g["passed"] else "FAIL"
        out.append(f"- **{g['gate']}** gate: {status}" + ("" if g["passed"] else " — " + "; ".join(g["reasons"])))
    return "\n".join(out)


def compute(root: Path, overrides: Optional[Dict[str, str]] = None, gate_names: Optional[List[str]] = None) -> dict:
    cfg = load_config(root)
    latest = journal.latest_by_agent(journal.parse(root / journal.JOURNAL))
    rows = component_scores(cfg, latest, overrides or {})
    overall = aggregate(rows)
    names = gate_names or list(cfg["gates"])
    gates = [evaluate_gate(n, cfg["gates"][n], overall, rows, root) for n in names]
    return {"overall": overall, "components": rows, "gates": gates}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Weighted quality score and gates for clo-author.")
    ap.add_argument("--root", default=".", help="Project root (default: .)")
    ap.add_argument("--gate", choices=("commit", "pr", "submission"), help="Evaluate one gate; exit 1 if it fails")
    ap.add_argument("--set", action="append", default=[], metavar="AGENT=VALUE",
                    help="Override a critic's result (number, PASS/FAIL, or a strategist verdict)")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    args = ap.parse_args(argv)

    overrides = {}
    for item in args.set:
        if "=" not in item:
            ap.error(f"--set expects AGENT=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        overrides[journal.normalize_agent(k)] = v

    root = Path(args.root).resolve()
    result = compute(root, overrides, [args.gate] if args.gate else None)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render(result["components"], result["overall"], result["gates"]))
    if args.gate:
        return 0 if result["gates"][0]["passed"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
