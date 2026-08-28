#!/usr/bin/env python3
"""PreToolUse guard for the gate-reviewer agent: allow inspection, deny mutation.

Scope, stated so it is not overclaimed. This guard exists to stop the reviewer
*changing* anything -- the repo, the index, the working tree, the machine. It is
not a confidentiality boundary. The reviewer also holds Read, Grep and Glob,
which this hook does not sit in front of, so a guard that also tried to restrict
*what it reads* would be a check that cannot achieve what it claims.

Wired from .claude/agents/gate-reviewer.md frontmatter, so it applies only while
that subagent is running.

Design note, because this file is itself an exemption mechanism and the same
rubric applies to it. Every bypass found in this repo so far was a value-parsing
hole rather than a logic hole: a placeholder matched by substring, a regex value
class that excluded '<' and '>', and a numeric check via float() that accepted
'inf' and '1_000_000'. So the parsing order here is load-bearing:

  1. The character set is an ALLOW-list, not a deny-list of metacharacters, and
     it is applied to the raw string BEFORE tokenising. A deny-list is the shape
     that failed all three previous times.
  2. Only then is the string tokenised.

Step 1 cannot be reordered after step 2. shlex.split() treats a newline as plain
whitespace, so "git diff\nrm -rf ." tokenises to ['git','diff','rm','-rf','.'],
whose argv[0] is an allowed command. Tokenising first would pass it. The raw
character scan is what refuses it. test_review_readonly_guard.py asserts exactly
this case.

Fails closed: anything unrecognised is a deny.
"""

import json
import shlex
import sys

# Allow-list of permitted characters, applied to the raw command string. Excludes
# every shell metacharacter, all whitespace except the plain space, and anything
# outside printable ASCII. Command chaining, substitution and redirection all
# need a character that is not in this set.
ALLOWED_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " -_./=:,'\"@^+#%[]~"
)

# argv[0] must be one of these. All are inspection commands that cannot write
# without a redirection character, which the character allow-list already
# refuses. sed and find are deliberately absent: sed -i and find -delete/-exec
# write without needing any metacharacter, and the reviewer has Read and Glob
# for what they would have been used for.
ALLOWED_COMMANDS = frozenset(
    {"git", "cat", "head", "tail", "wc", "ls", "nl", "basename", "dirname", "true"}
)

# For git, the subcommand must be one of these. Read-only plumbing and porcelain.
ALLOWED_GIT_SUBCOMMANDS = frozenset(
    {
        "diff",
        "show",
        "log",
        "status",
        "blame",
        "shortlog",
        "describe",
        "rev-parse",
        "rev-list",
        "ls-files",
        "ls-tree",
        "cat-file",
        "name-rev",
        "merge-base",
        "diff-tree",
        "show-ref",
        "count-objects",
    }
)

# Residual surface, named rather than hidden. With metacharacters gone, the only
# remaining way for an allowed command to write is a flag that writes to a path
# by itself. This is a deny-list, which is the weaker shape, so it is kept small
# and every entry has a test. Matching is on the whole token and on the
# '--flag=value' form, never on substrings -- 'substring match' is precisely how
# the placeholder check was bypassed.
WRITING_FLAGS = frozenset(
    {"-o", "--output", "-O", "--output-directory", "-i", "--in-place", "--write-tree"}
)


def _deny(reason):
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "gate-reviewer is read-only: " + reason,
            }
        },
        sys.stdout,
    )
    return 0


def _allow():
    # Emit nothing. The tool call falls through to the session's normal
    # permission flow rather than being auto-approved by this hook.
    return 0


def evaluate(command):
    """Return None to allow, or a string reason to deny.

    Split out from main() so the adversarial suite tests the decision directly.
    """
    if not isinstance(command, str):
        return "command was %s, not a string" % type(command).__name__

    if command != command.strip():
        return "command has leading or trailing whitespace"

    if not command:
        return "empty command"

    # Step 1: raw character allow-list. Must precede tokenisation. See module
    # docstring for why the order cannot be swapped.
    bad = sorted({c for c in command if c not in ALLOWED_CHARS})
    if bad:
        return "disallowed character(s) %s -- chaining, substitution and " "redirection are refused" % (
            ", ".join(repr(c) for c in bad),
        )

    # Step 2: tokenise. Safe now that the raw string is known to be free of
    # shell syntax.
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return "could not be parsed (%s)" % exc

    if not argv:
        return "no command after parsing"

    if argv[0] not in ALLOWED_COMMANDS:
        return "'%s' is not an inspection command" % argv[0]

    for token in argv[1:]:
        flag = token.split("=", 1)[0] if token.startswith("-") else token
        if flag in WRITING_FLAGS:
            return "'%s' writes to a path" % token

    if argv[0] == "git":
        if len(argv) < 2:
            return "bare 'git' does nothing to inspect"
        # Refuse pre-subcommand options outright: 'git -c core.hooksPath=...'
        # and 'git -C <dir>' both change what the subcommand acts on.
        if argv[1].startswith("-"):
            return "git option '%s' before the subcommand" % argv[1]
        if argv[1] not in ALLOWED_GIT_SUBCOMMANDS:
            return "'git %s' is not a read-only subcommand" % argv[1]

    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        return _deny("hook input was not readable JSON (%s)" % exc)

    if not isinstance(payload, dict):
        return _deny("hook input was not a JSON object")

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return _deny("hook input carried no tool_input object")

    if "command" not in tool_input:
        return _deny("tool_input carried no command field")

    reason = evaluate(tool_input["command"])
    if reason is not None:
        return _deny(reason)
    return _allow()


if __name__ == "__main__":
    sys.exit(main())
