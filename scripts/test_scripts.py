#!/usr/bin/env python3
"""
Tests for the enforcement scripts: score.py, pipeline.py, verify.py,
check_scaffold.py, style_metrics.py, and the INV-5 / INV-24 checks in
paper_coherence.py. Each runs against a throwaway fixture project.

clo-author: infrastructure (not analysis code; explainer_status.py skips it)

Usage:
    python3 scripts/test_scripts.py        # exit 1 on any failure
    python3 scripts/test_scripts.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERBOSE = "-v" in sys.argv
failures = []


def check(label, ok, detail=""):
    if ok:
        if VERBOSE:
            print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}  {str(detail)[:300]}")


def run(script, *args, root=None):
    cmd = [sys.executable, str(REPO / "scripts" / script), *args] + (["--root", str(root)] if root else [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def project(journal: str = "") -> Path:
    root = Path(tempfile.mkdtemp(prefix="clo-scripttest-"))
    (root / ".claude" / "rules").mkdir(parents=True)
    cfg = root / ".claude" / "skills" / "new-project" / "config"
    cfg.mkdir(parents=True)
    shutil.copy(REPO / ".claude/skills/new-project/config/quality-gates.json", cfg)
    shutil.copy(REPO / ".claude/rules/permissions.md", root / ".claude/rules")
    (root / "scripts").mkdir()
    (root / "scripts" / "explainer_status.py").write_text("import sys; sys.exit(0)\n")
    (root / "quality_reports").mkdir()
    if journal:
        (root / "quality_reports" / "research_journal.md").write_text(journal)
    return root


def entry(agent, score=None, verdict=None, phase="Execution", when="2026-09-25 10:00"):
    out = f"### {when} — {agent}\n**Phase:** {phase}\n"
    if score is not None:
        out += f"**Score:** {score}\n"
    if verdict is not None:
        out += f"**Verdict:** {verdict}\n"
    return out + "\n"


# ---------------------------------------------------------------------------

def test_score():
    print("score.py")
    j = (entry("librarian-critic", "88/100") + entry("strategist-critic", "N/A", "MINOR ISSUES — Oster bounds")
         + entry("coder-critic", "72/100") + entry("Coder-Critic (round 2)", "90/100") + entry("writer-critic", "84"))
    root = project(j)
    code, out, _ = run("score.py", "--json", root=root)
    d = json.loads(out)
    expected = round((88 * 10 + 85 * 25 + 90 * 15 + 84 * 10) / 60, 1)
    check("weighted aggregate matches hand computation", d["overall"] == expected, (d["overall"], expected))
    ident = next(r for r in d["components"] if r["component"] == "identification")
    check("strategist verdict mapped through verdict_scores", ident["score"] == 85 and ident["verdict"] == "MINOR ISSUES", ident)
    code_c = next(r for r in d["components"] if r["component"] == "code")
    check("latest journal entry wins (round 2 over round 1)", code_c["score"] == 90, code_c)

    code, out, _ = run("score.py", "--gate", "commit", root=root)
    check("commit gate passes at 86.6 (exit 0)", code == 0, out)
    code, out, _ = run("score.py", "--gate", "submission", root=root)
    check("submission gate fails (exit 1) and names unscored components", code == 1 and "not yet scored" in out and "referee_domain" in out, out)

    code, out, _ = run("score.py", "--json", "--set", "strategist-critic=MAJOR ISSUES", root=root)
    ident = next(r for r in json.loads(out)["components"] if r["component"] == "identification")
    check("--set accepts a verdict", ident["score"] == 65, ident)

    theory = project(j + entry("theorist-critic", "70/100"))
    d = json.loads(run("score.py", "--json", root=theory)[1])
    expected = round((88 * 10 + 85 * 25 + 70 * 20 + 90 * 15 + 84 * 10) / 80, 1)
    check("theory component renormalizes (weights sum to 120% before)", d["overall"] == expected, (d["overall"], expected))

    empty = project()
    code, out, _ = run("score.py", "--gate", "commit", root=empty)
    check("nothing scored: commit gate passes with a notice (allow_unscored)", code == 0 and "nothing scored yet" in out, out)
    code, out, _ = run("score.py", "--gate", "pr", root=empty)
    check("nothing scored: pr gate fails with a clear reason", code == 1 and "no component has been scored" in out, out)


def test_pipeline():
    print("pipeline.py")
    root = project(entry("strategist-critic", "N/A", "MAJOR ISSUES — parallel trends", phase="Strategy"))
    (root / "quality_reports/literature/minwage").mkdir(parents=True)
    (root / "quality_reports/literature/minwage/annotated_bibliography.md").write_text("x")
    memo = root / "quality_reports/strategy/minwage/strategy_memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text("# Memo\n## Estimand\n## Specification\n## Assumptions\n## Threats\n")

    code, out, _ = run("pipeline.py", "check-pre", "strategist", root=root)
    check("check-pre passes on an OR with one satisfied branch", code == 0, out)
    code, out, _ = run("pipeline.py", "check-post", "strategist", root=root)
    check("check-post fails on a missing required section", code == 1 and "Robustness Plan" in out, out)
    code, out, _ = run("pipeline.py", "check-pre", "coder", root=root)
    check("check-pre blocks the coder on a MAJOR ISSUES verdict", code == 1 and "MAJOR ISSUES" in out, out)

    memo.write_text(memo.read_text() + "## Robustness Plan\n")
    with (root / "quality_reports/research_journal.md").open("a") as fh:
        fh.write(entry("strategist-critic", "N/A", "SOUND", phase="Strategy", when="2026-09-26 10:00"))
    code, out, _ = run("pipeline.py", "check-pre", "coder", root=root)
    check("coder unblocked after a SOUND verdict", code == 0, out)
    code, out, _ = run("pipeline.py", "check-pre", "coherence-finder", root=root)
    check("unfillable placeholder is MANUAL, not FAIL", code == 0 and "MANUAL" in out, out)

    code, out, _ = run("pipeline.py", "status", root=root)
    state = json.loads((root / "quality_reports/pipeline_state.json").read_text())
    check("status writes pipeline_state.json derived from the journal",
          state["agents_completed"][0]["agent"] == "strategist-critic" and state["agents_completed"][0]["rounds"] == 2, state)
    check("coder is pending once its requirements hold", "coder" in state["agents_pending"], state["agents_pending"])

    code, out, _ = run("pipeline.py", "traces", root=root)
    check("traces lists rounds per agent", "| strategist-critic | 2 |" in out, out)


def toy_paper(root: Path, abstract_words: int, table1_cols: str, figure_older: bool = False):
    (root / "paper/tables/01_desc").mkdir(parents=True)
    (root / "paper/figures/02_main").mkdir(parents=True)
    (root / "scripts/R").mkdir(parents=True, exist_ok=True)
    (root / "paper/main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\begin{abstract}\n"
        + " ".join(["word"] * abstract_words)
        + "\n\\end{abstract}\n\\section{Intro}\nSee \\cref{tab:t1} and \\cref{fig:f1}.\n"
        "\\begin{table}[p]\\caption{Pre-Treatment Characteristics}\\label{tab:t1}\n\\input{tables/01_desc/t1.tex}\n\\end{table}\n"
        "\\begin{figure}[p]\\caption{Main}\\label{fig:f1}\n\\includegraphics{figures/02_main/f1.pdf}\n\\end{figure}\n\\end{document}\n")
    (root / "paper/tables/01_desc/t1.tex").write_text(
        "\\begin{tabular}{l%s}\n\\toprule\n & %s \\\\\n\\midrule\nWage & %s \\\\\n\\bottomrule\n\\end{tabular}\n"
        % ("c" * len(table1_cols.split("&")), table1_cols, " & ".join(["1.0"] * len(table1_cols.split("&")))))
    fig = root / "paper/figures/02_main/f1.pdf"
    fig.write_bytes(b"%PDF-1.4\n")
    (root / "scripts/R/01_desc.R").write_text("library(here)\n")
    script = root / "scripts/R/02_main.R"
    script.write_text("library(here)\n")
    if figure_older:
        os.utime(fig, (1_000_000_000, 1_000_000_000))


def test_coherence_additions():
    print("paper_coherence.py (INV-5, INV-24)")
    bad = project()
    toy_paper(bad, 180, "Treated & Control & Difference & p-value")
    code, out, _ = run("paper_coherence.py", "--json", str(bad / "out.json"), "--quiet", root=bad)
    checks = {f["check"] for f in json.loads((bad / "out.json").read_text())["findings"]}
    check("180-word abstract flagged (INV-5)", "abstract-too-long" in checks, checks)
    check("Table 1 with Difference/p-value flagged (INV-24)", "table1-extra-columns" in checks, checks)
    good = project()
    toy_paper(good, 120, "Treated Group & Control Group")
    run("paper_coherence.py", "--json", str(good / "out.json"), "--quiet", root=good)
    checks = {f["check"] for f in json.loads((good / "out.json").read_text())["findings"]}
    check("clean paper: neither check fires", not ({"abstract-too-long", "table1-extra-columns"} & checks), checks)
    run("paper_coherence.py", "--json", str(good / "out2.json"), "--quiet", "--abstract-limit", "100", root=good)
    checks = {f["check"] for f in json.loads((good / "out2.json").read_text())["findings"]}
    check("--abstract-limit 100 flags a 120-word abstract", "abstract-too-long" in checks, checks)


def test_verify():
    print("verify.py")
    root = project()
    toy_paper(root, 120, "Treated Group & Control Group", figure_older=True)
    code, out, _ = run("verify.py", "--no-compile", "--json", root=root)
    d = {c["check"]: c for c in json.loads(out)["checks"]}
    check("file integrity passes when every input resolves", d[3]["status"] == "PASS", d[3])
    check("stale exhibit (older than its script) fails freshness", d[4]["status"] == "FAIL" and "02_main.R" in " ".join(d[4]["details"]), d[4])
    check("exit 1 when a check fails", code == 1)
    code, out, _ = run("verify.py", "--no-compile", "--mode", "submission", "--json", root=root)
    d = {c["check"]: c for c in json.loads(out)["checks"]}
    check("submission: missing master script fails inventory", d[5]["status"] == "FAIL" and "master" in " ".join(d[5]["details"]), d[5])
    check("submission: missing renv.lock fails dependencies", d[6]["status"] == "FAIL", d[6])
    check("submission: exhibits traced and referenced", d[9]["status"] == "PASS", d[9])

    bp = project()
    toy_paper(bp, 120, "Treated Group & Control Group")
    (bp / "paper/tables/robustness").mkdir(parents=True)
    (bp / "paper/tables/robustness/alt_controls.tex").write_text("\\begin{tabular}{l}\nx \\\\\n\\end{tabular}\n")
    main = bp / "paper/main.tex"
    main.write_text(main.read_text().replace("\\end{document}", "\\input{tables/robustness/alt_controls.tex}\n\\end{document}"))
    robust = bp / "scripts/R/05_robust.R"
    robust.write_text('writeLines(x, here("paper", "tables", "robustness", "alt_controls.tex"))\n')
    d = {c["check"]: c for c in json.loads(run("verify.py", "--no-compile", "--mode", "submission", "--json", root=bp)[1])["checks"]}
    check("by-purpose layout: exhibit traced to the script that names it", d[9]["status"] == "PASS", d[9])
    robust.write_text("library(here)\n")
    d = {c["check"]: c for c in json.loads(run("verify.py", "--no-compile", "--mode", "submission", "--json", root=bp)[1])["checks"]}
    check("exhibit no script writes: cross-reference fails", d[9]["status"] == "FAIL" and "alt_controls" in " ".join(d[9]["details"]), d[9])


def test_check_scaffold():
    print("check_scaffold.py")
    code, out, _ = run("check_scaffold.py", "--quiet", root=REPO)
    check("the real scaffold has no errors", code == 0, out[-500:])
    root = Path(tempfile.mkdtemp(prefix="clo-scaffold-"))
    shutil.copytree(REPO / ".claude", root / ".claude", ignore=shutil.ignore_patterns("state"))
    shutil.copy(REPO / "CLAUDE.md", root)
    (root / "scripts").mkdir()
    for f in (REPO / "scripts").glob("*.py"):
        shutil.copy(f, root / "scripts")
    gates = root / ".claude/skills/new-project/config/quality-gates.json"
    g = json.loads(gates.read_text())
    g["components"]["code"]["weight"] = 20
    gates.write_text(json.dumps(g))
    with (root / ".claude/rules/logging.md").open("a") as fh:
        fh.write("\nSee `scripts/does_not_exist.py`.\n")
    (root / ".claude/skills/zz-broken").mkdir()
    (root / ".claude/skills/zz-broken/SKILL.md").write_text(
        "---\nname: zz-broken\ndescription: >\ndisable-model-invocation: true\n"
        "  Folded text that meant to be the description.\n---\nBody.\n")
    code, out, _ = run("check_scaffold.py", "--quiet", root=root)
    check("weight disagreement caught", "permissions.md says 15%, quality-gates.json says 20%" in out, out[-600:])
    check("phantom path caught", "does_not_exist.py" in out, out[-600:])
    check("empty block-scalar description caught", "zz-broken/SKILL.md: 'description: >' has no indented body" in out, out[-900:])
    check("boolean key that swallowed text caught", "'disable-model-invocation' must be true or false" in out, out[-900:])
    check("exit 1 on errors", code == 1)


def test_style_metrics():
    print("style_metrics.py")
    root = Path(tempfile.mkdtemp(prefix="clo-style-"))
    (root / ".claude/skills/write/templates").mkdir(parents=True)
    shutil.copy(REPO / ".claude/skills/write/templates/cleanup-patterns.md", root / ".claude/skills/write/templates")
    tex = root / "intro.tex"
    tex.write_text("Additionally, we delve into the nuanced interplay --- a question. It is worth noting that "
                   "effects are small. % delve delve in a comment\nThis section discusses the data. We find it.\n")
    code, out, _ = run("style_metrics.py", str(tex), "--json", root=root)
    d = json.loads(out)
    check("AI vocabulary counted from cleanup-patterns.md", d["hits"]["ai_vocabulary"].get("delve") == 1, d["hits"])
    check("LaTeX comments ignored", d["hits"]["ai_vocabulary"].get("delve") == 1)
    check("hedging and filler phrases counted", d["hits"]["hedging"] and d["hits"]["filler"], d["hits"])
    check("em dash counted", d["em_dashes"]["count"] == 1, d["em_dashes"])


if __name__ == "__main__":
    for t in (test_score, test_pipeline, test_coherence_additions, test_verify, test_check_scaffold, test_style_metrics):
        t()
    print("all script tests passed" if not failures else f"{len(failures)} script test(s) FAILED")
    sys.exit(1 if failures else 0)
