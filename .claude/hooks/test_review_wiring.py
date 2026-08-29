"""Wiring tests: the guard is connected, and fails closed when it is not.

test_review_readonly_guard.py proves evaluate() decides correctly. That is not
the same as proving the guard runs. Delete the `hooks:` block from
.claude/agents/gate-reviewer.md and every one of those 57 tests stays green while
the reviewer holds unrestricted Bash -- a check that cannot fail on the thing that
matters, which is rubric item 3 applied to the guard rather than by it.

So these tests take the hook command out of the agent's frontmatter and actually
run it, with the same stdin shape Claude Code sends.

What this proves: the frontmatter declares a PreToolUse/Bash command hook, the
command it names dispatches to the guard, a mutating command is refused, a
legitimate one is not, and a dispatch failure denies and exits 2 rather than
letting the command through.

What this does not prove: that Claude Code accepts the frontmatter and honours
the decision. Only Claude Code can demonstrate that, and no test here should be
read as evidence of it.

## The standing live-wiring probe: `git -C <path> diff`

To check whether the hook is actually firing in a running review -- which is the
gap above, and cannot be closed from inside this file -- ask the reviewer to run:

    git -C <absolute path to the repo> diff

`-C` is a pre-subcommand git option and the guard refuses it (`review_readonly_
guard.py`, "git option '-C' before the subcommand"), asserted below. If the
command returns a diff, the hook is not firing.

Three reasons this is the standing method rather than `rm -rf` or any other
destructive command:

- **It is non-destructive.** A probe that has to succeed at damage to prove a
  guard works can only be run somewhere the damage is acceptable, which is never
  the repo you care about.
- **It is denied for a structural reason, not a listed one.** `-C` changes which
  repository the subcommand acts on, so refusing it is load-bearing rather than
  incidental, and it will not quietly drop off a deny-list.
- **It does not ask an agent to attack its own restraints.** This matters more
  than it looks. When the destructive form was tried, the reviewer refused it and
  was right to: a launching agent's instruction is not the human's consent, and a
  result produced by an agent deliberately probing its own limits is not evidence
  anyone can independently check. A probe the reviewer can run in good conscience
  is a probe that will actually get run.

Run:  py -3 -m unittest discover -s .claude/hooks -p 'test_*.py' -v
"""

import json
import os
import re
import subprocess
import unittest

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(HOOKS_DIR))
AGENT_FILE = os.path.join(PROJECT_DIR, ".claude", "agents", "gate-reviewer.md")


def read_frontmatter():
    with open(AGENT_FILE, encoding="utf-8") as handle:
        text = handle.read()
    if not text.startswith("---\n"):
        raise AssertionError("agent file does not open with a frontmatter fence")
    end = text.index("\n---\n", 3)
    # Trailing newline restored: the slice ends at the newline before the closing
    # fence, so without it the last line of a folded block carries no terminator
    # and a line-oriented reader silently drops it. Not hypothetical -- it
    # truncated the hook command mid-brace-group on this file's first run, and a
    # shape assertion would have passed while the command was unrunnable.
    return text[4:end] + "\n"


def hook_command():
    """Extract the PreToolUse/Bash command, folding the YAML '>-' block.

    Hand-rolled rather than using a YAML library because the CI job that runs
    this installs nothing, which is what keeps it ahead of everything else.
    """
    frontmatter = read_frontmatter()
    match = re.search(
        r"^hooks:\n"
        r"  PreToolUse:\n"
        r'    - matcher: "Bash"\n'
        r"      hooks:\n"
        r"        - type: command\n"
        r"          command: >-\n"
        r"((?:            .*\n)+)",
        frontmatter,
        re.M,
    )
    if not match:
        raise AssertionError(
            "no PreToolUse/Bash command hook found in the agent frontmatter -- "
            "either the guard is not wired, or the hook was reformatted away "
            "from the expected 'command: >-' folded block. Both are worth a red "
            "build: the first is the regression this file exists for, and the "
            "second means nothing here is checking the wiring any more."
        )
    return " ".join(line.strip() for line in match.group(1).splitlines())


def run_hook(command_string, stdin, project_dir):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project_dir)
    return subprocess.run(
        ["sh", "-c", command_string],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


class TestFrontmatterDeclaresTheGuard(unittest.TestCase):
    def test_hook_block_exists(self):
        # Fails loudly if the hooks: block is removed or restructured.
        self.assertIn("review-readonly-guard.sh", hook_command())

    def test_guard_files_exist_at_the_referenced_paths(self):
        self.assertTrue(os.path.isfile(os.path.join(HOOKS_DIR, "review-readonly-guard.sh")))
        self.assertTrue(os.path.isfile(os.path.join(HOOKS_DIR, "review_readonly_guard.py")))

    def test_write_tools_are_not_granted(self):
        frontmatter = read_frontmatter()
        tools = re.search(r"^tools: (.*)$", frontmatter, re.M)
        self.assertIsNotNone(tools, "agent declares no tools allow-list")
        granted = {t.strip() for t in tools.group(1).split(",")}
        for forbidden in ("Edit", "Write", "NotebookEdit", "Agent"):
            self.assertNotIn(forbidden, granted)

    def test_bash_is_granted_and_therefore_needs_the_guard(self):
        # If Bash were ever dropped the guard would be dead weight; if the guard
        # were dropped while Bash remains, that is the failure this file exists
        # for. Asserting both keeps the pair honest.
        frontmatter = read_frontmatter()
        self.assertIn("Bash", frontmatter)
        self.assertIn("PreToolUse", frontmatter)


class TestHookCommandBehaviour(unittest.TestCase):
    """Run the real command string from the frontmatter."""

    def setUp(self):
        self.command = hook_command()

    def _decision(self, result):
        self.assertTrue(
            result.stdout, "hook emitted no decision (stderr: %r)" % result.stderr
        )
        return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_mutating_command_is_denied(self):
        payload = json.dumps({"tool_input": {"command": "git commit -m x"}})
        result = run_hook(self.command, payload, PROJECT_DIR)
        self.assertEqual(self._decision(result), "deny")

    def test_escape_is_denied_end_to_end(self):
        payload = json.dumps({"tool_input": {"command": "git diff; rm -rf ."}})
        result = run_hook(self.command, payload, PROJECT_DIR)
        self.assertEqual(self._decision(result), "deny")

    def test_legitimate_command_is_not_denied(self):
        payload = json.dumps({"tool_input": {"command": "git diff --cached"}})
        result = run_hook(self.command, payload, PROJECT_DIR)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.returncode, 0)

    def test_dispatch_failure_denies_and_exits_2(self):
        # The finding this file was written for. With the shim unreachable the
        # old wiring exited 127, which Claude Code treats as a non-blocking hook
        # error, so the command ran unguarded.
        payload = json.dumps({"tool_input": {"command": "git commit -m x"}})
        result = run_hook(self.command, payload, "/nonexistent-project-dir")
        self.assertEqual(self._decision(result), "deny")
        self.assertEqual(result.returncode, 2)

    def test_missing_guard_script_denies(self):
        # The shim present but the Python guard beside it gone.
        payload = json.dumps({"tool_input": {"command": "git commit -m x"}})
        result = run_hook(self.command, payload, os.path.join(PROJECT_DIR, "docs"))
        self.assertEqual(self._decision(result), "deny")

    def test_the_standing_live_wiring_probe_is_denied(self):
        # If this ever starts passing through, the documented probe in this
        # module's docstring stops meaning anything and the live-wiring check
        # silently becomes a no-op -- a test that cannot fire, checking a hook
        # that cannot fire.
        probe = 'git -C "%s" diff' % PROJECT_DIR
        payload = json.dumps({"tool_input": {"command": probe}})
        result = run_hook(self.command, payload, PROJECT_DIR)
        self.assertEqual(self._decision(result), "deny")
        self.assertIn("before the subcommand", result.stdout)

    def test_deny_output_is_a_single_json_object(self):
        # Two decisions on stdout would be malformed, and the failure mode of a
        # naive `||` fallback is exactly that: the guard denies, the fallback
        # fires on the non-zero exit, and both print.
        payload = json.dumps({"tool_input": {"command": "git push"}})
        result = run_hook(self.command, payload, PROJECT_DIR)
        json.loads(result.stdout)  # raises if a second object is concatenated
        self.assertEqual(result.stdout.count('"permissionDecision"'), 1)


if __name__ == "__main__":
    unittest.main()
