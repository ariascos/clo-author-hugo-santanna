# Logging

## Session Report
Append to `SESSION_REPORT.md` at end of session or before context compression.
**Rules:** Append only. Bullet points. Include file paths and commit hashes when available.
Create the file if it doesn't exist: `# Session Report — [Project Name]`

**Entry format:**
```markdown
## YYYY-MM-DD HH:MM — [Brief Title]

**Operations:**
- [Scripts run, files created/modified/deleted]

**Decisions:**
- [Choice made] — [rationale]

**Results:**
- [Key findings, outputs produced]

**Commits:**
- `[hash]` [commit message]

**Status:**
- Done: [what's complete]
- Pending: [what remains]
```

## Research Journal
Append to `quality_reports/research_journal.md` whenever an agent completes work — writing code, drafting a section, producing a review, making an editorial decision, or transitioning between phases.
**Rules:** Append only. One entry per agent invocation. Include phase transitions and editorial decisions.

**Entry format:**
```markdown
### YYYY-MM-DD HH:MM — [Agent Name]
**Phase:** [Discovery/Strategy/Execution/Peer Review/Presentation]
**Target:** [file or topic]
**Score:** [XX/100 or PASS/FAIL or N/A]
**Verdict:** [one line; the strategist-critic starts it with SOUND, MINOR ISSUES, MAJOR ISSUES, or CRITICAL ERRORS]
**Report:** [path to full report]
```
**Why it exists:** `scripts/score.py` and `scripts/pipeline.py` compute scores, gates, and pipeline state from these entries, so a critic result that isn't logged here doesn't count. Agents also read it to understand pipeline state — the editor checks the strategist-critic verdict, the orchestrator checks which phases passed, the coder-critic checks what the coder built. It's the shared context across agents.

Agent outputs (reports, scripts, memos, decisions) are saved to `quality_reports/` by the skills that produce them.

## Pipeline State

Structured pipeline state lives in `quality_reports/pipeline_state.json`.

**Location:** `quality_reports/pipeline_state.json`
**Template:** `templates/pipeline-state.json`
**Format:** JSON (machine-readable)

It is derived, not hand-maintained: `python3 scripts/pipeline.py status` rebuilds it from the
research journal and the registry (completed agents with rounds and latest results, agents whose
requirements now hold, the overall score, the first failing gate). Run it after each agent
completes and before a phase transition. The journal is the record; the state file is a view of it.

**Execution traces:** `python3 scripts/pipeline.py traces` tabulates rounds, first-pass and final
score per agent, and flags HIGH-PERF (first pass >= 90), FRICTION (3+ rounds without passing), and
USER ESCALATION. After a multi-agent skill, save its output with a short reading of the patterns to
`quality_reports/traces/YYYY-MM-DD_trace.md`; the orchestrator's learning loop (`orchestrator.md` §9)
starts from it.

---

## 4. Project Dashboard

**Managed by the `/dashboard` skill.** See `.claude/skills/dashboard/SKILL.md` for the full specification.

The dashboard is `project_dashboard.html` — a single unified HTML page with all project information. Generated and refreshed by `/dashboard refresh`. Changelog entries appended by `/dashboard add-changelog`.
