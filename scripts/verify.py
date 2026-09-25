#!/usr/bin/env python3
"""
verify.py — the verifier's mechanical checks.

clo-author: infrastructure (not analysis code; explainer_status.py skips it)

The verifier agent used to run these by hand: compile and read the log, glob
for files, compare timestamps, count scripts. Their inputs fully determine the
result, so they run here; the verifier agent keeps the checks that need
judgment (data provenance, README completeness) and reads this report.

Checks (numbering follows .claude/agents/verifier.md):
   1  LaTeX compilation         latexmk exit code, undefined refs/cites, overfull boxes, PDF
   2  Script execution          only for scripts passed with --script
   3  File integrity            every \\input / \\includegraphics target exists
   4  Output freshness          no exhibit older than the script that writes it
   5  Package inventory         numbered scripts, master script, no orphans      (submission)
   6  Dependency files          renv.lock / requirements.txt / Project.toml       (submission)
   8  Execution verification    runs the master script end to end (--run-master)  (submission)
   9  Output cross-reference    every exhibit referenced by the paper and traced  (submission)
  11  Understanding (INV-26)    explainer_status.py --gate                        (submission)

Usage:
    python3 scripts/verify.py                      # standard mode: checks 1-4
    python3 scripts/verify.py --mode submission    # checks 1-6, 8, 9, 11
    python3 scripts/verify.py --no-compile --script scripts/R/02_main.R
    python3 scripts/verify.py --json

Exit 0 when nothing FAILs; SKIP and MANUAL never fail the run.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_coherence as pc  # noqa: E402
from explainer_status import SCRIPT_SUFFIXES, SKIP_DIRS, is_infrastructure  # noqa: E402

INTERPRETERS = {".R": ["Rscript"], ".r": ["Rscript"], ".py": [sys.executable], ".jl": ["julia"], ".do": ["stata-mp", "-b", "do"]}
EXHIBIT_SUFFIXES = {".tex", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg"}
MASTER_RE = re.compile(r"^(00[_-].*|master.*|main|run[_-]?all.*|makefile)$", re.IGNORECASE)


class Result:
    def __init__(self, num: int, name: str):
        self.num, self.name = num, name
        self.status, self.details = "PASS", []

    def fail(self, msg: str) -> None:
        self.status = "FAIL"
        self.details.append(msg)

    def note(self, msg: str) -> None:
        self.details.append(msg)

    def skip(self, msg: str, status: str = "SKIP") -> "Result":
        self.status = status
        self.details.append(msg)
        return self

    def to_dict(self) -> dict:
        return {"check": self.num, "name": self.name, "status": self.status, "details": self.details}


# ---------------------------------------------------------------------------

def analysis_scripts(root: Path) -> List[Path]:
    base = root / "scripts"
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.suffix in SCRIPT_SUFFIXES and not is_infrastructure(p) \
                and not (set(p.relative_to(base).parts) & SKIP_DIRS):
            out.append(p)
    return out


def exhibits(root: Path) -> List[Path]:
    out = []
    for sub in ("paper/tables", "paper/figures"):
        d = root / sub
        if d.is_dir():
            out += [p for p in sorted(d.rglob("*")) if p.is_file() and p.suffix.lower() in EXHIBIT_SUFFIXES]
    return out


def script_for(exhibit: Path, root: Path, scripts: List[Path]) -> Optional[Path]:
    """By-script layout: paper/tables/<folder>/file.tex is written by scripts/**/<folder>.*
    (a leading 'script' in the folder name is optional)."""
    rel = exhibit.relative_to(root / "paper")
    if len(rel.parts) < 3:
        return None
    folder = rel.parts[1].lower()
    keys = {folder, re.sub(r"^script[_-]?", "", folder)}
    for s in scripts:
        stem = s.stem.lower()
        if stem in keys or re.sub(r"^script[_-]?", "", stem) in keys:
            return s
    return None


def index(root: Path) -> Optional[pc.Index]:
    main = pc.find_main(root / "paper") if (root / "paper").is_dir() else None
    if main is None:
        return None
    idx = pc.Index(root=root, main=main)
    idx.build()
    return idx


# ---------------------------------------------------------------------------

def check_compile(root: Path, compile_: bool) -> Result:
    r = Result(1, "LaTeX compilation")
    main = pc.find_main(root / "paper") if (root / "paper").is_dir() else None
    if main is None:
        return r.skip("no main .tex in paper/ (template repo)")
    log = main.with_suffix(".log")
    pdf = main.with_suffix(".pdf")
    if compile_:
        proc = subprocess.run(["latexmk", "-interaction=nonstopmode", main.name], cwd=main.parent,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            r.fail(f"latexmk exited {proc.returncode}: " + (proc.stdout.strip().splitlines() or [""])[-1][:160])
    elif not log.exists():
        return r.skip("--no-compile and no .log to read", "MANUAL")
    if not pdf.exists():
        r.fail(f"{pdf.name} was not produced")
    if log.exists():
        text = log.read_text(errors="replace")
        undefined = len(re.findall(r"(?:Citation|Reference) `[^']+' .*undefined", text))
        overfull = len(re.findall(r"Overfull \\hbox", text))
        if undefined:
            r.fail(f"{undefined} undefined citation(s)/reference(s) in {log.name}")
        if overfull:
            r.note(f"{overfull} overfull \\hbox warning(s)")
    return r


def check_scripts(root: Path, targets: List[str]) -> Result:
    r = Result(2, "Script execution")
    if not targets:
        return r.skip("no --script given; the verifier chooses which scripts to run")
    for t in targets:
        path = root / t
        cmd = ["make", "-f"] if path.name.lower() == "makefile" else INTERPRETERS.get(path.suffix)
        if not path.exists() or cmd is None:
            r.fail(f"{t}: {'missing' if not path.exists() else 'no interpreter for ' + path.suffix}")
            continue
        start = time.time()
        proc = subprocess.run(cmd + [str(path)], cwd=root, capture_output=True, text=True)
        took = time.time() - start
        if proc.returncode != 0:
            r.fail(f"{t} exited {proc.returncode} after {took:.0f}s: " + (proc.stderr.strip().splitlines() or [""])[-1][:160])
        else:
            r.note(f"{t} ran in {took:.0f}s")
    return r


def check_integrity(idx: Optional[pc.Index]) -> Result:
    r = Result(3, "File integrity")
    if idx is None:
        return r.skip("no main .tex in paper/")
    for f in pc.check_files(idx):
        r.fail(f"{f.file}:{f.line} {f.message}")
    if r.status == "PASS":
        r.note(f"{len(idx.inputs)} inputs and {len(idx.graphics)} graphics resolve")
    return r


def check_freshness(root: Path, scripts: List[Path]) -> Result:
    r = Result(4, "Output freshness")
    exs = exhibits(root)
    if not exs:
        return r.skip("no exhibits in paper/tables or paper/figures")
    stale = []
    for e in exs:
        s = script_for(e, root, scripts)
        if s is not None and s.stat().st_mtime > e.stat().st_mtime:
            stale.append(f"{e.relative_to(root)} is older than {s.relative_to(root)}")
    for msg in stale:
        r.fail(msg)
    if not stale:
        r.note(f"{len(exs)} exhibit(s) checked")
    return r


def check_inventory(root: Path, scripts: List[Path]) -> Tuple[Result, Optional[Path]]:
    r = Result(5, "Package inventory")
    if not scripts:
        return r.skip("no analysis scripts"), None
    masters = [s for s in scripts if MASTER_RE.match(s.stem)] + \
              [p for p in [root / "Makefile", root / "makefile"] if p.exists()]
    master = masters[0] if masters else None
    if master is None:
        r.fail("no master script (00_master.*, master.*, main.*, run_all.*, or a Makefile)")
    numbered = [s for s in scripts if s != master]
    nums = []
    for s in numbered:
        m = re.match(r"^(\d{2,3})[_-]", s.name)
        if not m:
            r.fail(f"{s.relative_to(root)} is not numbered (NN_name)")
        else:
            nums.append(int(m.group(1)))
    dupes = sorted({n for n in nums if nums.count(n) > 1})
    if dupes:
        r.fail(f"duplicate script numbers: {dupes}")
    if master is not None:
        text = master.read_text(errors="replace")
        orphans = [s.name for s in numbered if s.name not in text and s.stem not in text]
        for o in orphans:
            r.fail(f"{o} is not called by {master.name}")
    return r, master


def check_dependencies(root: Path, scripts: List[Path]) -> Result:
    r = Result(6, "Dependency files")
    langs = {s.suffix.lower() for s in scripts}
    need = {".r": ["renv.lock", "sessionInfo.txt"], ".py": ["requirements.txt", "pyproject.toml", "environment.yml"],
            ".jl": ["Project.toml", "Manifest.toml"]}
    if not langs:
        return r.skip("no analysis scripts")
    for lang in sorted(langs & set(need)):
        found = [n for n in need[lang] if list(root.rglob(n))]
        if not found:
            r.fail(f"{lang} scripts but none of {', '.join(need[lang])}")
        else:
            r.note(f"{lang}: {', '.join(found)}")
    return r


def check_master_run(root: Path, master: Optional[Path], run: bool) -> Result:
    r = Result(8, "Execution verification")
    if not run:
        return r.skip("pass --run-master to execute the master script end to end")
    if master is None:
        return r.skip("no master script to run", "FAIL")
    res = check_scripts(root, [str(master.relative_to(root))])
    res.num, res.name = 8, "Execution verification"
    return res


def check_crossref(root: Path, idx: Optional[pc.Index], scripts: List[Path]) -> Result:
    r = Result(9, "Output cross-reference")
    if idx is None:
        return r.skip("no main .tex in paper/")
    referenced = set()
    for loc in list(idx.inputs) + list(idx.graphics):
        target = loc.value
        for cand in (root / "paper" / target, root / "paper" / (target + ".tex"), root / target):
            if cand.exists():
                referenced.add(cand.resolve())
        for ext in (".pdf", ".png", ".jpg", ".eps"):
            cand = root / "paper" / (target + ext)
            if cand.exists():
                referenced.add(cand.resolve())
    for e in exhibits(root):
        rel = e.relative_to(root)
        if e.resolve() not in referenced:
            r.fail(f"{rel} is never used by the paper (orphan output)")
        if script_for(e, root, scripts) is None:
            r.fail(f"{rel} cannot be traced to a script (by-script folder layout)")
    return r


def check_understanding(root: Path) -> Result:
    r = Result(11, "Understanding (INV-26)")
    tool = root / "scripts" / "explainer_status.py"
    if not tool.exists():
        return r.skip("scripts/explainer_status.py not found")
    proc = subprocess.run([sys.executable, str(tool), "--gate"], cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        for line in proc.stdout.strip().splitlines()[-5:]:
            r.fail(line.strip())
    return r


# ---------------------------------------------------------------------------

def render(results: List[Result], mode: str) -> str:
    out = ["## Verification Report (mechanical checks — scripts/verify.py)",
           f"**Mode:** {mode.capitalize()}", "",
           "| # | Check | Status | Details |", "|---|---|---|---|"]
    for r in results:
        out.append(f"| {r.num} | {r.name} | {r.status} | {'; '.join(r.details)[:400]} |")
    failed = [r for r in results if r.status == "FAIL"]
    out += ["", f"**Mechanical checks:** {'FAIL' if failed else 'PASS'} "
                f"({sum(r.status == 'PASS' for r in results)} pass, {len(failed)} fail, "
                f"{sum(r.status in ('SKIP', 'MANUAL') for r in results)} skipped)",
            "Judgment checks (7 data provenance, 10 README completeness) are the verifier agent's."]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mechanical verification checks.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--mode", choices=("standard", "submission"), default="standard")
    ap.add_argument("--no-compile", action="store_true", help="Read the existing .log instead of running latexmk")
    ap.add_argument("--script", action="append", default=[], help="Run this script (repeatable)")
    ap.add_argument("--run-master", action="store_true", help="Run the master script end to end (submission)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    scripts = analysis_scripts(root)
    idx = index(root)
    results = [check_compile(root, not args.no_compile), check_scripts(root, args.script),
               check_integrity(idx), check_freshness(root, scripts)]
    if args.mode == "submission":
        inv, master = check_inventory(root, scripts)
        results += [inv, check_dependencies(root, scripts), check_master_run(root, master, args.run_master),
                    check_crossref(root, idx, scripts), check_understanding(root)]
    if args.json:
        print(json.dumps({"mode": args.mode, "checks": [r.to_dict() for r in results]}, indent=2))
    else:
        print(render(results, args.mode))
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
