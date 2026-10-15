# Reasoning Checks (Layer 2)

What parsing cannot reach. Each check reads a pre-filtered slice written by
`python3 scripts/paper_coherence.py --slices quality_reports/coherence/slices`,
never the raw paper, so the model only sees candidate spans. That keeps this
layer cheap and keeps it from wandering into judgment. Open a source file only
for context a slice does not carry.

**The rule for every check below:** a finding must be resolvable by pointing at
two places in the paper that cannot both be right. If resolving it requires an
opinion about whether the research is good, it is not a coherence finding; it
belongs to `/review`.

This file is the single definition of each check. `coherence-finder` reads the
sections for its group; `coherence-skeptic` reads them to judge whether a finding
is in scope.

---

## Check groups

One `coherence-finder` dispatch per group, each with its own context, so checks
don't anchor on each other.

| Group | Checks | Slice (`quality_reports/coherence/slices/`) | Slice shape |
|---|---|---|---|
| specification | R1 | `specification.json` | `candidates`: `{paragraph, equations[]}` pairs |
| claims | R2, R6 | `claims.json` | `candidates`: `{paragraph, numbers[], cited_cells[]}` |
| continuity | R3 | `continuity.json` | `setup[]` and `restatements[]` |
| notation | R4 | `notation.json` | `symbols`: `{symbol: [use sites]}`, each with environment, label, file, line, body |
| theory | R5 | `theory.json` | `candidates`: theorem, proof, assumption, and definition bodies |

A group whose slice is empty is not dispatched. `theory` is empty for applied
papers using off-the-shelf estimators, which is the correct result.

---

## R1 — Estimand drift

Does the prose describe the same object the equation defines? For each pair,
line up five things between the equation and the prose:

| | Look for |
|---|---|
| Treatment variable | Does the prose's treatment match the equation's regressor? |
| Unit of observation | Individual, household, firm, region, and does the subscript agree? |
| Fixed effects | `\alpha_c + \gamma_t` is two-way; "county-by-year" is one interacted term |
| Comparison group | Never-treated, not-yet-treated, all others |
| Time window | Event window, lags and leads, omitted category |

**Finds.**
- Prose says "the effect of treatment on the treated" where the equation is a
  pooled interaction with no ATT weighting
- Prose says "controlling for county-by-year fixed effects" where the equation
  has separate `\alpha_c` and `\gamma_t`
- Prose describes a balanced panel where the equation indexes an unbalanced one
- The omitted category in the prose differs from the one the equation excludes

**Not a finding.** The equation is faithfully described but the design is
questionable. That is `/review --methods`; this check has no opinion about
whether the specification is a good idea.

---

## R2 — Claim strength vs evidence

Does the estimate support the adjective, judged against the outcome's own scale
in the same table: the mean dependent variable row, the SD, or the baseline?

**Finds.**
- "A substantial increase" on an estimate under a tenth of the baseline
- "Precisely estimated" where the coefficient is smaller than its standard error
- "Robust across specifications" where the cited columns flip sign

**This is the check most likely to overreach.** Require the contradiction to be
arithmetic (the estimate against its own SE, or against the baseline row in the
same table), never rhetorical. "I would not have called that large" is taste,
and taste is out of scope.

**Not a finding.** A large effect the author calls large; disagreement about
whether a magnitude is economically interesting.

---

## R3 — Cross-section contradiction

Does the paper keep its own story straight across sections? A restriction stated
once in Data and restated loosely in the Conclusion is the most common defect
here, and the hardest to catch reading front to back.

Build a scope table from `setup` before comparing anything:

| Dimension | Value the paper commits to |
|---|---|
| Sample period | |
| Unit and population | |
| Treatment definition | |
| Exclusions and restrictions | |
| Clustering level | |
| Key assumption | |

Then read each entry in `restatements` against that table, and report only where
a restatement asserts something the table contradicts.

**Finds.**
- Data says the sample runs 2005–2012; the conclusion says "over the 2005–2015 period"
- Strategy defines treatment as share above 0.5; robustness calls the baseline
  "any activation"
- Data restricts to immigrant-headed households; results generalize to "immigrants"
- Standard errors clustered at MSA level in the strategy, "state level" in the text

**Not a finding.**
- A restriction the paper deliberately varies in a robustness check and says so
- Looser shorthand that is unambiguous in context ("the sample" for "our sample")
- The abstract compressing a definition it does not contradict

Quote both statements verbatim. If the contradiction disappears once they sit
side by side, it was not one.

---

## R4 — Notation semantics (INV-7)

The same symbol means the same thing everywhere, and different concepts get
different symbols. The deterministic layer catches a macro *defined* twice; this
catches a symbol *used* two ways. For each symbol, infer its role at every site
from the surrounding equation, then ask whether one definition covers them all.

**Finds.**
- `\beta` is the treatment effect in the main equation and a nuisance coefficient
  in the mechanism section
- `i` indexes individuals in one equation and municipalities in another
- `\ell` is relative event time in one place and a lag order in another
- `N` is the sample size in one place and a count of units in another

**Not a finding.**
- Conventional reuse the paper defines locally and explicitly ("in this
  subsection, $j$ indexes firms")
- Universal conventions: `i` and `t` as generic indices whose meaning is fixed
  throughout, `\epsilon` as an error term
- A symbol carrying a distinguishing subscript or accent at each site: `\beta_1`
  and `\beta_2` are different symbols

State the two meanings in a clause each. If you can't, there is no collision.

---

## R5 — Unstated assumption

Does a proof use something the theorem never assumed?

1. Build the assumption ledger: every `assumption` and `definition` body, plus
   the hypotheses in each theorem's own statement.
2. Walk each proof step by step. At every step that requires a property
   (differentiating, applying a fixed point, exchanging limit and integral,
   invoking monotonicity, taking an interior solution), check the ledger.
3. Report a step whose required property appears nowhere.

**Finds.**
- A proof differentiates a function never assumed differentiable
- A result relies on single-crossing that appears in no assumption
- An interchange of limit and expectation with no dominated-convergence condition
- A first-order condition treated as sufficient with no concavity assumption
- An interior solution assumed where the constraint set permits corners

**Not a finding.**
- Standard steps the field would never state (linearity of expectation)
- A property implied by a stated assumption: say so and move on
- A proof you find inelegant, or a gap in rigor that is not a missing assumption

Flag only where the missing assumption is load-bearing: the step fails without
it. Name the step, the property, and the assumption that should exist.

---

## R6 — Direction language

Does the verb match the sign of the cell the number resolves to?

**Finds.** "Reduces food insecurity by 4.9 percentage points" where the cell is
`+0.0489`. Sign flips survive proofreading because both halves read fluently.

**Not a finding.** A fall in a bad outcome described as an improvement, or any
case where the outcome's polarity makes the verb correct. Check the polarity
before reporting.

---

## Output

A JSON array, one object per finding, matching the deterministic layer's schema
plus two anchors, a layer tag, and a confidence:

```json
{"check": "R2-claim-strength", "severity": "minor",
 "file": "paper/sections/results.tex", "line": 13,
 "anchor_a": "file:line", "anchor_b": "file:line",
 "message": "one sentence stating the contradiction",
 "evidence": "the two quoted fragments",
 "suggestion": "a specific edit, not 'consider revising'",
 "layer": "reasoning", "confidence": "high|medium|low"}
```

- **Two anchors or it is not a finding.** A finding with one anchor is an opinion.
- `severity` never exceeds `minor`. Reasoning findings do not block.
- Return `[]` rather than something weak, and report the candidate count so an
  empty result is informative. An empty pass on a coherent paper is correct.
- Don't restate Layer 1. If a number already failed to match a cell, the
  deterministic layer reported it; these checks are about the description, not
  the digits.
- `low` confidence is legitimate and more useful than inflated `high`.
