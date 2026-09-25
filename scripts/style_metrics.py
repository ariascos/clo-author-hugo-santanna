#!/usr/bin/env python3
"""
style_metrics.py — the countable part of the writer-critic's style review.

clo-author: infrastructure (not analysis code; explainer_status.py skips it)

Several writer-critic deductions are counts: AI-vocabulary hits, hedging and
filler phrases, em dashes per page, sentence-length median and spread. The
model estimated them by reading; this script counts them, and the critic
applies the rubric (review/config/scoring-rubrics.md) to the numbers.

The word lists are read from .claude/skills/write/templates/cleanup-patterns.md
(patterns 7, 19, 20 and the anti-hedging list) so there is one list to edit.
The personal style guide's median sentence length, when filled in, is the
comparison target.

Usage:
    python3 scripts/style_metrics.py paper/sections/introduction.tex
    python3 scripts/style_metrics.py paper/            # every .tex under paper/sections
    python3 scripts/style_metrics.py paper/ --json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Dict, List

PATTERNS = Path(".claude/skills/write/templates/cleanup-patterns.md")
STYLE_GUIDE = Path(".claude/references/personal-style-guide.md")
WORDS_PER_PAGE = 300  # double-spaced manuscript page

FALLBACK_VOCAB = ["additionally", "delve", "foster", "garner", "interplay", "tapestry", "underscore",
                  "landscape", "nuanced", "leverage", "multifaceted", "holistic"]


def load_lists(root: Path) -> Dict[str, List[str]]:
    lists = {"ai_vocabulary": [], "hedging": [], "filler": []}
    path = root / PATTERNS
    text = path.read_text(errors="replace") if path.exists() else ""
    m = re.search(r"\*\*AI vocabulary\*\*\s*--\s*(.+)", text)
    lists["ai_vocabulary"] = [w.strip().lower() for w in m.group(1).split(",")] if m else FALLBACK_VOCAB
    hedge = re.search(r"## Anti-Hedging.*?\n(.*?)\n---", text, re.DOTALL)
    if hedge:
        lists["hedging"] = [q.lower() for q in re.findall(r'"([^"]+)"', hedge.group(1))]
    for pat in (r"\*\*Filler phrases\*\*\s*--\s*(.+)", r"\*\*Meta-commentary\*\*\s*--\s*(.+)"):
        m = re.search(pat, text)
        if m:
            lists["filler"] += [q.rstrip(". ").replace("...", "").strip().lower()
                                for q in re.findall(r'"([^"]+)"', m.group(1))]
    return lists


def target_median(root: Path):
    path = root / STYLE_GUIDE
    if not path.exists():
        return None
    m = re.search(r"Median sentence length \(words\)\s*\|\s*(\d+(?:\.\d+)?)\s*\|", path.read_text(errors="replace"))
    return float(m.group(1)) if m else None  # "[e.g., 18]" (the template) does not match


def prose_from_tex(text: str) -> str:
    """Body prose only: no comments, math, floats, or command names."""
    text = re.sub(r"(?<!\\)%.*", "", text)
    text = re.sub(r"\\begin\{(table|figure|equation|align|tabular|gather|multline)\*?\}.*?\\end\{\1\*?\}", " ", text, flags=re.DOTALL)
    text = re.sub(r"\$\$.*?\$\$|\\\[.*?\\\]|\$[^$]*\$", " X ", text, flags=re.DOTALL)
    text = re.sub(r"\\(?:cite[a-z]*|cref|Cref|ref|label|input|include)\*?(\[[^\]]*\])*\{[^}]*\}", " ", text)
    text = text.replace("---", " \u2014 ")
    text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)
    text = re.sub(r"[{}~]", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def sentences(prose: str) -> List[str]:
    flat = re.sub(r"\s+", " ", prose)
    flat = re.sub(r"\b(e\.g|i\.e|et al|cf|vs|Fig|Eq|Sec|No)\.", r"\1<dot>", flat)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", flat)
    return [p.replace("<dot>", ".").strip() for p in parts if len(p.split()) >= 3]


def measure(files: List[Path], root: Path) -> dict:
    lists = load_lists(root)
    prose = "\n".join(prose_from_tex(f.read_text(errors="replace")) for f in files)
    sents = sentences(prose)
    lengths = [len(s.split()) for s in sents]
    words = sum(lengths)
    lower = prose.lower()
    hits = {}
    for group, terms in lists.items():
        counts = {}
        for term in terms:
            n = len(re.findall(r"\b" + re.escape(term) + r"\w*", lower))
            if n:
                counts[term] = n
        hits[group] = counts
    em = prose.count("\u2014")
    pages = max(words / WORDS_PER_PAGE, 1.0)
    mid = sum(1 for n in lengths if 15 <= n <= 25)
    target = target_median(root)
    med = statistics.median(lengths) if lengths else 0
    return {
        "files": [str(f) for f in files],
        "words": words,
        "sentences": len(lengths),
        "sentence_length": {
            "median": med,
            "p10": sorted(lengths)[len(lengths) // 10] if lengths else 0,
            "p90": sorted(lengths)[(len(lengths) * 9) // 10] if lengths else 0,
            "sd": round(statistics.pstdev(lengths), 1) if lengths else 0,
            "share_15_25": round(mid / len(lengths), 2) if lengths else 0,
            "style_guide_median": target,
            "off_by": round(med - target, 1) if target is not None and lengths else None,
        },
        "em_dashes": {"count": em, "per_page": round(em / pages, 2)},
        "hits": hits,
    }


def render(m: dict) -> str:
    sl = m["sentence_length"]
    out = [f"## Style metrics ({len(m['files'])} file(s), {m['words']} words, {m['sentences']} sentences)", "",
           f"- Sentence length: median {sl['median']}, p10 {sl['p10']}, p90 {sl['p90']}, sd {sl['sd']}; "
           f"{int(sl['share_15_25'] * 100)}% of sentences are 15-25 words",
           f"- Style-guide median: {sl['style_guide_median'] if sl['style_guide_median'] is not None else 'not set (template)'}"
           + (f"; off by {sl['off_by']:+g} words" if sl["off_by"] is not None else ""),
           f"- Em dashes: {m['em_dashes']['count']} ({m['em_dashes']['per_page']} per page)"]
    for group, counts in m["hits"].items():
        total = sum(counts.values())
        detail = ", ".join(f"{k} x{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
        label = {"ai_vocabulary": "AI vocabulary", "hedging": "Hedging phrases", "filler": "Filler / meta-commentary"}[group]
        out.append(f"- {label}: {total}" + (f" ({detail})" if detail else ""))
    out.append("")
    out.append("Counts only; the writer-critic applies the rubric in review/config/scoring-rubrics.md.")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Countable writing-style metrics for the writer-critic.")
    ap.add_argument("target", help="A .tex file, or a directory (uses paper/sections/*.tex when present)")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    target = Path(args.target)
    if target.is_dir():
        sections = target / "sections"
        files = sorted((sections if sections.is_dir() else target).rglob("*.tex"))
    else:
        files = [target]
    files = [f for f in files if f.exists()]
    if not files:
        print(f"style_metrics: no .tex files at {args.target}", file=sys.stderr)
        return 2
    m = measure(files, root)
    print(json.dumps(m, indent=2) if args.json else render(m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
