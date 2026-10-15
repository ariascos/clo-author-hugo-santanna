# Freeze Skill -- Gotchas

- Freeze paths are relative to project root. `/freeze paper/` means `$PROJECT_ROOT/paper/`.
- `.claude/` is always editable regardless of freeze -- you can't lock yourself out of configuration.
- Freeze doesn't affect Read or Bash -- you can always read and run commands, just not edit files outside allowed paths.
- Multiple paths: `/freeze paper/ scripts/` allows both directories.
- Freeze survives `/compact` and the end of the conversation: it stays on until `/freeze off`. If edits are blocked unexpectedly, check `.claude/state/session-guards.json`.
