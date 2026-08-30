#!/bin/sh
# Run the poller with system sleep disabled, and put the machine's settings
# back afterwards.
#
#     sh scripts/probe/run-awake.sh scripts/probe/config.run2.yaml
#
# With a command after the config, it runs that instead of the poller. Gate 5's
# ingest run needs the same protection for the same reason, and copying forty
# lines of powercfg handling -- whose two gotchas below were both found the hard
# way -- into a second file would be two places to get it wrong:
#
#     sh scripts/probe/run-awake.sh tenants/hsl_tripupdates.yaml #         .venv/Scripts/python.exe -m ingest.run ...
#
# Why this exists: run 2 was voided when the machine slept for 56 of 60
# minutes. SetThreadExecutionState, which the poller asserts from inside the
# process, prevents idle sleep but did not hold -- so the setting is changed at
# the OS level for the duration instead.
#
# TWO GOTCHAS, both found the hard way:
#
# 1. Use `-change`, NOT `/change`. Git Bash rewrites forward-slash arguments
#    into Windows paths, so `powercfg /change` arrives as a filesystem path and
#    powercfg answers "Invalid Parameters". The first version of this wrapper
#    did exactly that: the trap fired, powercfg failed, and the script printed
#    that it had restored the settings while restoring nothing.
#
# 2. Verify the restore. A restore that reports success without taking effect
#    is worse than no restore, because nobody goes looking. This one reads the
#    values back and shouts if they do not match.

set -e

CONFIG="${1:?usage: run-awake.sh <config.yaml> [command...]}"
shift
PY="${PY:-.venv/Scripts/python.exe}"
POWERCFG="$SYSTEMROOT/System32/powercfg.exe"

# Current values in minutes, so whatever the operator had is what they get back
# -- never a hardcoded default that silently becomes their new preference.
read_timeout() {  # $1 = ac|dc
    "$POWERCFG" -query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE \
        | grep -i "Current $1 Power Setting Index" \
        | sed 's/.*0x//' \
        | tr -d '[:space:]'
}

hex_to_min() { printf '%d' "$((0x$1 / 60))"; }

ORIG_AC_HEX=$(read_timeout AC)
ORIG_DC_HEX=$(read_timeout DC)
ORIG_AC=$(hex_to_min "$ORIG_AC_HEX")
ORIG_DC=$(hex_to_min "$ORIG_DC_HEX")
echo "[power] saved originals: standby-timeout ac=${ORIG_AC}min dc=${ORIG_DC}min"

restore() {
    "$POWERCFG" -change -standby-timeout-ac "$ORIG_AC" || true
    "$POWERCFG" -change -standby-timeout-dc "$ORIG_DC" || true
    now_ac=$(hex_to_min "$(read_timeout AC)")
    now_dc=$(hex_to_min "$(read_timeout DC)")
    if [ "$now_ac" = "$ORIG_AC" ] && [ "$now_dc" = "$ORIG_DC" ]; then
        echo "[power] restored: ac=${now_ac}min dc=${now_dc}min"
    else
        echo "[power] RESTORE FAILED -- wanted ac=${ORIG_AC} dc=${ORIG_DC}," \
             "got ac=${now_ac} dc=${now_dc}. Set these back by hand." >&2
    fi
}
trap restore EXIT INT TERM

"$POWERCFG" -change -standby-timeout-ac 0
"$POWERCFG" -change -standby-timeout-dc 0
if [ "$(read_timeout AC)" != "00000000" ] || [ "$(read_timeout DC)" != "00000000" ]; then
    echo "[power] could not disable sleep -- refusing to start a run that will be voided" >&2
    exit 2
fi
echo "[power] sleep disabled for the duration (verified)"

if [ "$#" -gt 0 ]; then
    "$@"
else
    "$PY" scripts/probe/poll.py "$CONFIG"
fi
