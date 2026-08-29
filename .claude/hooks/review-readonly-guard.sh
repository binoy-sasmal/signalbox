#!/bin/sh
# Interpreter shim for review_readonly_guard.py.
#
# Fails closed. Every path through this script emits a decision on stdout and
# exits 0, including the paths where the guard cannot be run at all. Exit 0 is
# what the caller expects: Claude Code treats a non-zero, non-2 hook exit as a
# non-blocking error and runs the command anyway, so a shim that exited 127 when
# it could not find an interpreter would leave the reviewer with unrestricted
# Bash while still appearing to be a constraint.
#
# The one case this script cannot cover is not being run at all -- a rename, or
# an unexpanded ${CLAUDE_PROJECT_DIR}. That is handled by the `||` fallback in
# the hook command in .claude/agents/gate-reviewer.md, which is why this script
# must keep exiting 0 rather than 2: a `||` cannot tell a legitimate denial from
# a dispatch failure if both are non-zero.
#
# Interpreter ordering is not cosmetic. On Windows, `python3` exists as a
# Microsoft Store execution alias that prints an install message and exits
# non-zero, so `command -v python3` finds a stub rather than an interpreter.
# Every branch therefore probes with `-c ""` before committing to it, including
# the `py` branch -- an unprobed branch is the same latent bug one name over.

guard="$(dirname "$0")/review_readonly_guard.py"

deny() {
    printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"gate-reviewer is read-only: '"$1"', so the command is refused"}}'
    exit 0
}

[ -f "$guard" ] || deny "the guard script is missing"

if command -v py >/dev/null 2>&1 && py -3 -c "" >/dev/null 2>&1; then
    py -3 "$guard"
elif command -v python3 >/dev/null 2>&1 && python3 -c "" >/dev/null 2>&1; then
    python3 "$guard"
elif command -v python >/dev/null 2>&1 && python -c "" >/dev/null 2>&1; then
    python "$guard"
else
    deny "no working Python interpreter was found"
fi

status=$?
[ "$status" -eq 0 ] || deny "the guard exited $status without deciding"
exit 0
