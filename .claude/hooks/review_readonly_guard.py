#!/usr/bin/env python3
"""PreToolUse guard for the gate-reviewer agent: allow inspection, deny mutation.

Scope, stated so it is not overclaimed. This guard stops the reviewer *changing*
things -- the repo, the index, the working tree, the machine. It is not a
confidentiality boundary. The reviewer also holds Read, Grep and Glob, which this
hook does not sit in front of, so a guard that also tried to restrict *what it
reads* would be a check that cannot achieve what it claims.

Wired from .claude/agents/gate-reviewer.md frontmatter, so it applies only while
that agent is running.

## Failing closed

This process emits a decision on every path and always exits 0. Allow is silence;
everything else -- policy denial, unreadable input, an unexpected exception -- is a
deny decision on stdout. There is no code path that exits without a decision.

Exiting 0 on denial is deliberate: a JSON `permissionDecision` of "deny" is the
documented mechanism, and it surfaces the reason to the agent. Exit 2 is reserved
for the case this process cannot cover, which is not running at all. That case is
handled one layer out, by review-readonly-guard.sh and by the `||` fallback in the
agent's frontmatter, because a non-zero exit that is neither 0 nor 2 is treated as
a non-blocking hook error and the command would otherwise run unguarded.

## Parsing order is the design

Every bypass found in this repo was a value-parsing hole rather than a logic hole:
a placeholder matched by substring, a regex value class that excluded '<' and '>',
and a numeric check via float() that accepted 'inf' and '1_000_000'. So:

  1. The character check is an ALLOW-list, not a deny-list of metacharacters, and
     it runs on the raw string BEFORE tokenising. A deny-list is the shape that
     failed all three previous times.
  2. Only then is the string tokenised.

The order cannot be swapped. shlex.split() treats a newline as ordinary
whitespace, so "git diff\nrm -rf ." tokenises to ['git','diff','rm','-rf','.'],
whose argv[0] is an allowed command. Tokenising first would pass it. The raw
character scan is what refuses it, and test_review_readonly_guard.py asserts that
exact case.

## Accepted limitation: no positional character exemptions

'{', '}', '(' and ')' are refused everywhere, including where they would be
legitimate: `git show HEAD@{1}`, `git diff @{upstream}...HEAD`, and a `--grep=`
pattern containing parentheses -- which matters here because every commit subject
in this repo uses the `type(scope):` form.

Permitting them only in those positions was considered and rejected. It would mean
adding an exemption mechanism *to the exemption mechanism*, and its correctness
would rest on shlex's quote handling agreeing with the executing shell's. A
divergence there is precisely the value-parsing hole class above. The capability
lost is small: `git log --grep=fix` still works, plain revisions, ranges, `~` and
`^` all still work, and `HEAD@{n}` has no role in reviewing a diff.
"""

import json
import shlex
import sys

# Allow-list of permitted characters, applied to the raw command string. Excludes
# every shell metacharacter, all whitespace except the plain space, and everything
# outside printable ASCII. Command chaining, substitution and redirection each
# need a character that is not in this set. See the module docstring for why
# braces and parentheses are absent rather than positionally permitted.
ALLOWED_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " -_./=:,'\"@^+#%[]~"
)

# argv[0] must be one of these. Absent by deliberate choice, each because it
# writes or blocks without needing a metacharacter, and each replaceable by a tool
# the reviewer already holds:
#   sed   -- `sed -i` edits in place; use Read.
#   find  -- `-delete` and `-exec` write; use Glob.
#   tail  -- `-f` blocks forever, and short flags bundle (`-fn5`), so denying the
#            flag means parsing a bundle, which is new value-parsing surface. Use
#            Read with an offset.
ALLOWED_COMMANDS = frozenset(
    {"git", "cat", "head", "wc", "ls", "nl", "basename", "dirname", "true"}
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

# Residual surface, scoped by command rather than checked context-free. With
# metacharacters gone, what remains is a flag that writes or blocks by itself --
# but the same letter means different things to different commands, and a
# context-free list denied `git log -i` (case-insensitive grep), `git ls-files -o`
# (--others) and `git diff -O` (read an orderfile), none of which write anything.
#
# Keys are (command,) or (command, git-subcommand). Values are exact flag names;
# `--flag=value` is matched on the part before '='.
DENIED_FLAGS = {
    ("git", "diff"): {"--output"},
    ("git", "show"): {"--output"},
    ("git", "log"): {"--output"},
    ("git", "diff-tree"): {"--output"},
}

# `git cat-file --batch*` reads object names from stdin and blocks until EOF. A
# hanging reviewer is a stalled gate. Prefix matching is correct here and only
# here: the entire --batch family streams, so there is no legitimate --batch flag
# for the prefix to swallow.
DENIED_FLAG_PREFIXES = {("git", "cat-file"): ("--batch",)}


def _decision(reason):
    """Emit a deny decision. Always the only thing written to stdout."""
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


def evaluate(command):
    """Return None to allow, or a string reason to deny.

    Separate from main() so the adversarial suite tests the decision directly.
    """
    if not isinstance(command, str):
        return "command was %s, not a string" % type(command).__name__

    if command != command.strip():
        return "command has leading or trailing whitespace"

    if not command:
        return "empty command"

    # Step 1: raw character allow-list. Must precede tokenisation. See the module
    # docstring for why the order cannot be swapped.
    bad = sorted({c for c in command if c not in ALLOWED_CHARS})
    if bad:
        return (
            "disallowed character(s) %s -- chaining, substitution and redirection "
            "are refused" % ", ".join(repr(c) for c in bad)
        )

    # Step 2: tokenise. Safe now that the raw string is known to carry no shell
    # syntax.
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return "could not be parsed (%s)" % exc

    if not argv:
        return "no command after parsing"

    if argv[0] not in ALLOWED_COMMANDS:
        return "'%s' is not an inspection command" % argv[0]

    key = (argv[0],)
    if argv[0] == "git":
        if len(argv) < 2:
            return "bare 'git' does nothing to inspect"
        # Refuse pre-subcommand options outright: `git -c core.hooksPath=...` and
        # `git -C <dir>` both change what the subcommand acts on.
        if argv[1].startswith("-"):
            return "git option '%s' before the subcommand" % argv[1]
        if argv[1] not in ALLOWED_GIT_SUBCOMMANDS:
            return "'git %s' is not a read-only subcommand" % argv[1]
        key = (argv[0], argv[1])

    denied = DENIED_FLAGS.get(key, frozenset())
    prefixes = DENIED_FLAG_PREFIXES.get(key, ())
    for token in argv[1:]:
        if not token.startswith("-"):
            continue
        flag = token.split("=", 1)[0]
        if flag in denied:
            return "'%s' writes to a path" % token
        if any(flag.startswith(prefix) for prefix in prefixes):
            return "'%s' reads from stdin and would block" % token

    return None


def main():
    """Emit a decision and return 0. Never returns non-zero, never returns silently
    except on allow."""
    try:
        try:
            payload = json.load(sys.stdin)
        except (ValueError, OSError) as exc:
            _decision("hook input was not readable JSON (%s)" % exc)
            return 0

        if not isinstance(payload, dict):
            _decision("hook input was not a JSON object")
            return 0

        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            _decision("hook input carried no tool_input object")
            return 0

        if "command" not in tool_input:
            _decision("tool_input carried no command field")
            return 0

        reason = evaluate(tool_input["command"])
        if reason is not None:
            _decision(reason)
        return 0
    except Exception as exc:  # noqa: BLE001 -- fail closed on anything at all
        _decision("guard raised %s: %s" % (type(exc).__name__, exc))
        return 0


if __name__ == "__main__":
    sys.exit(main())
