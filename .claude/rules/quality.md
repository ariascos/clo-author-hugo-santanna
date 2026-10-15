# Quality: Scoring, Thresholds, and Severity

---

## 1. Scoring Protocol

**How individual agent scores aggregate into the overall project score.**

### Weighted Aggregation

The overall project score is a weighted aggregate of the critics' results. Compute it with:

```bash
python3 scripts/score.py                     # component table and every gate's status
python3 scripts/score.py --gate submission   # exit 1 unless the gate passes
```

Report its output; don't recompute by hand. It reads each critic's latest entry in
`quality_reports/research_journal.md`, so log every critic result there (`logging.md`). Weights,
the strategist verdict map, and the gate thresholds live in one file,
`.claude/skills/new-project/config/quality-gates.json`; the QUALITY_WEIGHT fields in `permissions.md`
mirror it for readers, and `scripts/check_scaffold.py` fails if the two disagree.

Components that were never scored are excluded and the rest renormalized, and the output lists
what was excluded. The theorist's 20% counts only when the theorist ran, so an applied paper's
weights sum to 100% and a theory paper's are renormalized from 120%. The strategist-critic rules by
verdict; the verdict maps to a score for this aggregate only.

### Minimum Per Component

No component can be below 80 for submission. A perfect literature review can't compensate for broken identification.

### Score Sources

- Each critic produces a score from 0 to 100 from its deduction table (the strategist-critic, a verdict)
- The verifier is pass/fail (100 or 0)
- The two referees carry 12.5% each, which is the same as averaging them into one 25% component

### Gate Thresholds

| Gate | Overall | Per component | Enforced by |
|------|---------|---------------|-------------|
| Commit | >= 80 | — | `/tools commit` runs `score.py --gate commit` once any critic has scored |
| PR | >= 90 | — | `score.py --gate pr` before opening a PR |
| Submission | >= 95 | >= 80, and every non-conditional component scored | `/submit final` runs `score.py --gate submission` (includes the understanding gate) |

Separately, the git pre-commit hook (`.githooks/pre-commit`, installed by `scripts/install-hooks.sh`)
blocks every commit on scaffold integrity and on HIGH lint findings in staged analysis scripts, and
prints paper-coherence findings as advice. It does not check the score: a new project has no critic
scores yet, and a gate that fails every early commit gets bypassed.

### Gates That Are Not Scores

Two checks sit outside the weighted aggregate entirely — they are pass/fail and never deduct:

| Gate | Rule | Blocks at |
|------|------|-----------|
| Coherence (Layer 1) | `.claude/rules/content-invariants.md` | Zero tolerance, any phase |
| Understanding (INV-26) | `.claude/rules/understanding.md` | `/submit` |

The understanding gate is excluded from the score by design: a quiz result is a fact about the
author, not the artifact. Folding it in would let good code compensate for an author who cannot
explain it — which is the exact trade the gate exists to block.

---

## 2. Severity Gradient

**Critics calibrate severity based on the phase of the project.**

### Phase-Based Severity

| Phase | Critic Stance | Rationale |
|-------|--------------|-----------|
| Discovery | Encouraging (low severity) | Early ideas need space to develop |
| Strategy | Constructive (medium severity) | Identification must be sound, but alternatives should be suggested |
| Execution | Strict (high severity) | Code and paper are near-final — bugs are costly |
| Peer Review | Adversarial (maximum severity) | Simulates real referees — no mercy |
| Presentation | Professional (medium-high) | Talks should be polished but scored as advisory |

### How It Works

The Orchestrator includes the severity level in the critic's prompt:

```
You are reviewing at SEVERITY: HIGH (Execution phase).
State what must change, not what to "consider".
```

Severity sets the register and the deduction scale below, not what gets reported. Critics report
every issue they find at every phase, each with its severity; a critic told to be lenient under-reports,
and an issue missed in Discovery comes back as a larger one in Execution.

### Deduction Scaling

The same issue may have different deductions by phase:

| Issue | Discovery | Strategy | Execution | Peer Review |
|-------|-----------|----------|-----------|-------------|
| Missing citation | -2 | -5 | -10 | -15 |
| Notation inconsistency | -1 | -3 | -5 | -5 |
| Hedging language | — | — | -3 | -5 |
| Missing robustness check | — | -5 | -15 | -20 |

### Principle

Early phases are about getting the direction right. Late phases are about getting the details right. Critics should match their tone and rigor to the phase.
