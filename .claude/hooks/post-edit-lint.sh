#!/bin/bash
# post-edit-lint.sh — PostToolUse hook (Edit|Write) that lints R/Python/Julia
# files after they change. Advisory: always exits 0.
#
# Claude Code sends the hook payload as JSON on stdin; the edited path is
# tool_input.file_path. Findings go back to Claude as
# hookSpecificOutput.additionalContext — plain stdout from a PostToolUse hook
# only reaches the transcript, not the model.

FILE=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)
[[ -z "$FILE" ]] && exit 0

# Only run on R/Python/Julia scripts
case "$FILE" in
  *.R|*.py|*.jl) ;;
  *) exit 0 ;;
esac

# Skip files inside .claude/ (hooks, agents, etc.)
case "$FILE" in
  */.claude/*) exit 0 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT=$("$SCRIPT_DIR/lint-scripts.sh" "$FILE" 2>/dev/null)
[[ -z "$OUT" ]] && exit 0
grep -q "Status: CLEAN" <<<"$OUT" && exit 0

python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"Lint findings for the file just edited (content invariants INV-14/15/16/19):\n"+sys.stdin.read()}}))' <<<"$OUT"
exit 0
