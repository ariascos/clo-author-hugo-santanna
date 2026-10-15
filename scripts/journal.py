#!/usr/bin/env python3
"""
journal.py — read quality_reports/research_journal.md.

clo-author: infrastructure (not analysis code; explainer_status.py skips it)

The research journal is the pipeline's event log: every agent invocation
appends one entry (format in .claude/rules/logging.md). score.py and
pipeline.py derive scores, gates, and pipeline state from it, so nothing has
to be kept in sync by hand.

    ### 2026-09-25 14:05 — coder-critic
    **Phase:** Execution
    **Target:** scripts/R/02_main.R
    **Score:** 85/100            (or PASS / FAIL / N/A)
    **Verdict:** Clean; two minor style issues
    **Report:** quality_reports/reviews/code_review_02.md

Stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

JOURNAL = Path("quality_reports") / "research_journal.md"

HEADER_RE = re.compile(
    r"^###\s+(?P<when>\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2})?)\s*[—–-]+\s*(?P<agent>.+?)\s*$"
)
FIELD_RE = re.compile(r"^\*\*(?P<key>[A-Za-z ]+):\*\*\s*(?P<value>.*)$")
VERDICTS = ("CRITICAL ERRORS", "MAJOR ISSUES", "MINOR ISSUES", "SOUND")


@dataclass
class Entry:
    when: str
    agent: str
    line: int
    fields: Dict[str, str] = field(default_factory=dict)

    @property
    def phase(self) -> str:
        return self.fields.get("phase", "")

    @property
    def score(self) -> Optional[float]:
        """Numeric score; PASS maps to 100 and FAIL to 0; None if absent or N/A."""
        raw = self.fields.get("score", "")
        if re.search(r"\bPASS\b", raw, re.IGNORECASE):
            return 100.0
        if re.search(r"\bFAIL\b", raw, re.IGNORECASE):
            return 0.0
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:/\s*100)?", raw)
        return float(m.group(1)) if m else None

    @property
    def verdict(self) -> str:
        """One of VERDICTS if the Verdict or Score line names it, else ''."""
        text = (self.fields.get("verdict", "") + " " + self.fields.get("score", "")).upper()
        for v in VERDICTS:
            if v in text:
                return v
        return ""


def normalize_agent(name: str) -> str:
    """'Coder-Critic (round 2)' -> 'coder-critic'."""
    name = re.sub(r"\(.*?\)|\[|\]|\*", "", name)
    return re.sub(r"[\s_]+", "-", name.strip().lower()).strip("-")


def parse(path: Path) -> List[Entry]:
    if not path.exists():
        return []
    entries: List[Entry] = []
    current: Optional[Entry] = None
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        m = HEADER_RE.match(line)
        if m:
            current = Entry(when=m.group("when"), agent=normalize_agent(m.group("agent")), line=i)
            entries.append(current)
            continue
        if current is not None:
            f = FIELD_RE.match(line.strip())
            if f:
                current.fields[f.group("key").strip().lower()] = f.group("value").strip()
    return entries


def latest_by_agent(entries: List[Entry]) -> Dict[str, Entry]:
    """Most recent entry per agent (journal order; later entries win)."""
    out: Dict[str, Entry] = {}
    for e in entries:
        out[e.agent] = e
    return out


def rounds_by_agent(entries: List[Entry]) -> Dict[str, List[Entry]]:
    out: Dict[str, List[Entry]] = {}
    for e in entries:
        out.setdefault(e.agent, []).append(e)
    return out
