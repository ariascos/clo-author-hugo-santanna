# Clo-Author

[![Version](https://img.shields.io/github/v/release/hugosantanna/clo-author?style=flat-square&color=b44dff&label=version)](CHANGELOG.md)

A Claude Code scaffold for empirical economics research, from literature review to journal submission. Twenty-five agents draft, critique, and referee the work, and scripts enforce the quality gates.

Guide: [hsantanna.org/clo-author](https://hsantanna.org/clo-author/)

---

## To Get Started

```bash
# Fork and clone
gh repo fork hugosantanna/clo-author --clone
cd clo-author

# Open Claude Code (terminal, VS Code, or JetBrains)
claude
```

Then:

```
I am starting a research project on [YOUR TOPIC]. Read CLAUDE.md and help me set up.
```

Claude reads the config and gets to work. It asks for your approval before multi-agent pipeline runs and changes across many files. Works in the terminal, VS Code extension, or JetBrains.

---

## Setup

1. Fill in `CLAUDE.md` — replace `[BRACKETED PLACEHOLDERS]` with your project details
2. Fill in `.claude/references/domain-profile.md` — your field, journals, data, methods. Or run `/discover interview` to do it interactively.
3. Configure your language — R is the default. Python and Julia also supported.

**Other fields:** Economics by default. Adapts to labor, public, health, development, trade, IO, and other applied fields by customizing the domain profile and journal profiles.

---

## Commands

18 skills, each with modes:

| Skill | What It Does |
|-------|-------------|
| `/new-project` | Full pipeline: idea to paper (runs only when you type it) |
| `/discover` | Literature search, data discovery, research interviews |
| `/strategize` | Identification strategy, pre-analysis plan, formal theory |
| `/analyze` | Data analysis (R, Python, Julia) |
| `/write` | Draft paper sections with humanizer pass |
| `/paper-format` | Apply the paper house style: floats, Table 1, wrappers, section order |
| `/review` | Quality review — routes by target (paper, code, peer) |
| `/coherence` | Internal-consistency audit: references, numbers vs. tables, notation |
| `/deepread` | Deep technical read on Codex, no Claude tokens (runs only when you type it) |
| `/explain` | Explainer and quiz for agent-written analysis code |
| `/revise` | R&R cycle: classify referee comments and route fixes |
| `/talk` | Presentations (Quarto RevealJS or Beamer) |
| `/submit` | Journal targeting, replication package, final gate |
| `/tools` | Utilities: commit, compile, validate-bib, journal, deploy, upgrade |
| `/dashboard` | Generate or refresh the single-page HTML project dashboard |
| `/checkpoint` | Session handoff: saves progress to memory + Obsidian |
| `/freeze` | Lock directories from accidental edits |
| `/careful` | Block destructive shell commands |

---

## Agents

25 agents. Workers are paired with critics that can't edit files, creators can't score themselves, and a disagreement that survives 3 rounds escalates. Judgment-heavy roles run at `high` effort and narrow checkers at `low`.

| Phase | Worker | Critic |
|-------|--------|--------|
| Discovery | Librarian | librarian-critic |
| Discovery | Explorer | explorer-critic |
| Strategy | Strategist | strategist-critic (gives a verdict, e.g. SOUND / MAJOR ISSUES) |
| Strategy | Theorist | theorist-critic |
| Execution | Coder | coder-critic |
| Execution | Data-engineer | coder-critic |
| Paper | Writer | writer-critic |
| Paper audit | coherence-finder (one per check group) | coherence-skeptic, coherence-consolidator |
| Understanding | Explainer | — (your quiz is the check) |
| Peer Review | Editor + domain-referee + methods-referee | — |
| Presentation | Storyteller | storyteller-critic |
| Infrastructure | Orchestrator, Verifier, Guide-writer | — |

---

## Peer Review

`/review --peer [journal]` simulates a full journal submission:

1. Editor desk review — novelty check via web search, decides desk reject or send out
2. Two blind referees with intellectual dispositions (Structuralist, Credibility, Measurement, Policy, Theory, Skeptic) weighted by journal culture. In round 1 they read a fenced copy of the manuscript, away from earlier verdicts.
3. Independent scored reports — every major comment includes "what would change my mind"
4. Editorial decision — FATAL / ADDRESSABLE / TASTE classification, MUST / SHOULD / MAY action items

Additional modes:
- `--stress` — adversarial referees for pre-submission battle testing
- `--peer --r2` — R&R second round with referee memory
- Max 3 rounds, then the editor's patience runs out

34 journal profiles across economics and adjacent fields.

---

## HTML Dashboard

`/dashboard` generates a self-contained HTML dashboard of your entire project — sections, data, scripts, quality scores, review history. No server, no dependencies. Double-click to open. It runs `scripts/generate_dashboard.py` for the skeleton, which you can also run directly:

```bash
python3 scripts/generate_dashboard.py
```

Detail reports drill down into individual components:

```bash
python3 scripts/generate_html_report.py peer-review [files...]
python3 scripts/generate_html_report.py code-audit [files...]
python3 scripts/generate_html_report.py strategy-review [files...]
python3 scripts/generate_html_report.py quality-gate [files...]
python3 scripts/generate_html_report.py literature [files...]
```

Self-contained HTML with dark mode, collapsible sections, and print support. Works on `file://`.

---

## Quality Gates

`scripts/score.py` computes a weighted aggregate from each critic's latest entry in the research journal. The weights and thresholds live in one file, `quality-gates.json`.

| Score | Gate |
|-------|------|
| 80 | Commit allowed (passes with a notice before any critic has scored) |
| 90 | PR allowed |
| 95 | Submission allowed: every component ≥ 80, `verify.py` passes, and you have passed the `/explain` quiz for every script behind a table or figure (INV-26) |

Other scripts handle the mechanical checks: `pipeline.py` checks each agent's inputs and outputs, `verify.py` the verifier's checks, `paper_coherence.py` the paper's internal consistency, and `check_scaffold.py` the scaffold itself. A git pre-commit gate runs them on every commit.

---

## Project Structure

```
your-project/
├── CLAUDE.md                    # Project config (fill in placeholders)
├── .claude/                     # Agents, skills, rules, hooks
├── paper/                       # LaTeX manuscript (source of truth)
│   ├── main.tex
│   ├── preambles/header.tex     # House-style preamble (\input{preambles/header})
│   ├── sections/
│   ├── figures/
│   ├── tables/
│   ├── talks/
│   └── replication/
├── data/                        # Raw and cleaned datasets
├── scripts/                     # Your analysis code (R, Python, Julia) + the scaffold's gate scripts
├── .githooks/                   # Pre-commit gate (scripts/install-hooks.sh turns it on)
├── quality_reports/             # Reviews, research journal, plans, traces
├── templates/html/              # HTML report design system
└── explorations/                # Research sandbox
```

---

## Prerequisites

| Tool | Install |
|------|---------|
| [Claude Code](https://code.claude.com/docs) 2.1.295 or later | see the docs |
| Python 3 | runs the hooks and the gate scripts |
| XeLaTeX | [TeX Live](https://tug.org/texlive/) or [MacTeX](https://tug.org/mactex/) |
| R | [r-project.org](https://www.r-project.org/) |

Optional: Julia, [Quarto](https://quarto.org), [gh CLI](https://cli.github.com/), and the [Codex CLI](https://github.com/openai/codex) for `/deepread`.

After cloning, run `scripts/install-hooks.sh` once. It points git at `.githooks/`, whose pre-commit
check blocks commits that break the scaffold's own references, fail the hook or script tests, or add
analysis scripts with `setwd()`, absolute paths, and similar INV-14/15/16/19 violations. Bypass with
`SKIP_GATE=1 git commit ...` and say why in the message.

---

## Upgrading

Run `/tools upgrade` from within Claude Code. It shows you the plan before changing anything, then:

- replaces `.claude/`, keeping your domain profile, custom journal profiles, `settings.local.json`, and anything you added to `settings.json` (moved into `settings.local.json`)
- replaces the scaffold's own scripts in `scripts/`, meaning the files marked `clo-author: infrastructure`, and `.githooks/`
- leaves your paper, analysis scripts, data, and bibliography alone
- runs `check_scaffold.py` and the hook tests before reporting

---

## This is a Scaffold

Every output needs human review. Claude plans and executes; you decide what ships. The peer review catches structural issues but doesn't replicate actual referee expertise. Quality scores flag problems but don't measure publishability. The writer produces drafts, not final prose. `/explain` exists so you can defend every result an agent produced.

---

## Origin

Maintained by [Hugo Sant'Anna](https://hsantanna.org) at UAB. Originally forked from Pedro H. C. Sant'Anna's [claude-code-my-workflow](https://github.com/pedrohcgs/claude-code-my-workflow) in February 2026; developed independently since.

MIT License — see [LICENSE](LICENSE).
