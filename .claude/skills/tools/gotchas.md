# Tools Skill -- Gotchas

- `latexmk` handles multi-pass compilation automatically -- don't run xelatex/biber manually unless debugging.
- `validate-bib` checks for common issues but doesn't verify that citation keys match the .bib file.
- Journal selection (`/tools journal`) reads journal-profiles.md -- if the target field isn't profiled, results will be generic.
- Commit skill runs `score.py --gate commit`. Once critics have scored, an aggregate below 80 blocks the commit; before that it passes with a notice.
- The lint subcommand is advisory (exit 0 always). It catches grep-able violations; the coder-critic handles judgment calls.
- `upgrade` deletes and replaces `.claude/` entirely -- it preserves domain-profile.md, custom journal profiles, settings.local.json, and the user's additions to settings.json (moved into settings.local.json), but nothing else custom in that directory.
- `upgrade` that skips `scripts/` leaves skills calling missing gate scripts. Scaffold scripts carry "clo-author: infrastructure" in their first lines; that marker is what upgrade replaces, and the only thing.
- Never stage `.env`, credentials, or `.claude/state/` files in commits.
