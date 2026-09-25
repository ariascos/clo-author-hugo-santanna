# Lifecycle: Handoff Validation Protocol

Validation rules for agent dispatch and completion. The Orchestrator runs these checks before and after every agent invocation.

---

## The checks

`permissions.md` declares what each agent REQUIRES and PRODUCES. `scripts/pipeline.py` reads it and
checks both, using the research journal for critic scores and verdicts:

```bash
python3 scripts/pipeline.py check-pre  <agent> [--project P] [--script S]   # before dispatch
python3 scripts/pipeline.py check-post <agent> [--project P] [--script S]   # after it finishes
```

Each condition prints PASS, FAIL, or MANUAL. Exit 1 means a FAIL: don't dispatch (check-pre) or don't
advance (check-post), and report the script's one-line reason with the skill that produces the
missing input. MANUAL marks a condition only judgment can settle ("Research idea or research spec",
a placeholder the script cannot fill); decide it yourself and say how you decided.

A critic's result gates the *next* agent, so it is checked by that agent's check-pre, not by the
worker's check-post.

---

## FAIL-FAST Principle

When validation fails:
- Report immediately with a clear, actionable message
- Never dispatch an agent with missing inputs and hope it works
- Never advance past an agent with missing outputs
- The Orchestrator includes the validation failure in its report to the user
