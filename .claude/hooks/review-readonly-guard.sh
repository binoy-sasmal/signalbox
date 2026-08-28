#!/bin/sh
# Interpreter shim for review_readonly_guard.py.
#
# Ordering matters and is not cosmetic: on Windows, `python3` exists as a
# Microsoft Store execution alias that prints an install message and exits
# non-zero, so a `command -v python3` check finds a stub rather than an
# interpreter. `py -3` is tried first for that reason. Same ordering as
# .githooks/pre-commit.
#
# Hook commands run through Git Bash on Windows and sh elsewhere.

dir=$(dirname "$0")
guard="$dir/review_readonly_guard.py"

if command -v py >/dev/null 2>&1; then
    exec py -3 "$guard"
elif command -v python3 >/dev/null 2>&1 && python3 -c "" >/dev/null 2>&1; then
    exec python3 "$guard"
else
    exec python "$guard"
fi
