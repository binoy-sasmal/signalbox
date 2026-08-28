"""Adversarial suite for the gate-reviewer read-only guard.

The guard is an exemption mechanism -- it exists to let one agent run a narrow
set of commands that the rest of its constraints would forbid. Rubric item 1
says an exemption without an adversarial test in the same commit is a defect,
and that applies to the guard as much as to anything it reviews.

All three bypasses found in this repo were value-parsing holes rather than logic
holes, so this suite is weighted towards inputs shaped like an allowed command
that carry an escape inside the value.

Run:  py -3 -m unittest discover -s .claude/hooks -p 'test_*.py' -v
"""

import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import review_readonly_guard as guard  # noqa: E402


class TestShellEscapes(unittest.TestCase):
    """The escape class the guard exists to refuse.

    Note what tokenisation alone would do with several of these. shlex.split()
    treats newline, carriage return and tab as ordinary whitespace, so
    "git diff\\nrm -rf ." tokenises to ['git','diff','rm','-rf','.'] -- argv[0]
    is 'git', argv[1] is 'diff', and a guard that checked only the parsed form
    would allow it. The raw character scan running first is the whole defence.
    """

    def assertDenied(self, command, label):
        reason = guard.evaluate(command)
        self.assertIsNotNone(reason, "%s was ALLOWED: %r" % (label, command))

    def test_semicolon_chain(self):
        self.assertDenied("git diff; rm -rf .", "semicolon")

    def test_newline_chain(self):
        # The case tokenisation would pass. See class docstring.
        self.assertDenied("git diff\nrm -rf .", "newline")

    def test_carriage_return_chain(self):
        self.assertDenied("git diff\rrm -rf .", "carriage return")

    def test_tab_separator(self):
        self.assertDenied("git\tdiff\trm -rf .", "tab")

    def test_and_chain(self):
        self.assertDenied("git diff && rm -rf .", "and-chain")

    def test_or_chain(self):
        self.assertDenied("git diff || rm -rf .", "or-chain")

    def test_single_ampersand_background(self):
        self.assertDenied("git diff & rm -rf .", "background")

    def test_pipe(self):
        self.assertDenied("git diff | tee out.txt", "pipe")

    def test_backtick_substitution(self):
        self.assertDenied("git diff `rm -rf .`", "backticks")

    def test_dollar_paren_substitution(self):
        self.assertDenied("git diff $(rm -rf .)", "dollar-paren")

    def test_dollar_brace_expansion(self):
        self.assertDenied("git diff ${HOME}", "dollar-brace")

    def test_bare_dollar_variable(self):
        self.assertDenied("git diff $HOME", "dollar-var")

    def test_stdout_redirect(self):
        self.assertDenied("git diff > out.txt", "redirect")

    def test_append_redirect(self):
        self.assertDenied("git diff >> out.txt", "append-redirect")

    def test_stdin_redirect(self):
        self.assertDenied("cat < /etc/passwd", "stdin-redirect")

    def test_process_substitution(self):
        self.assertDenied("cat <(rm -rf .)", "process-substitution")

    def test_line_continuation(self):
        self.assertDenied("git diff \\\n rm -rf .", "backslash continuation")

    def test_glob(self):
        self.assertDenied("cat runs/*/run.json", "glob")

    def test_brace_expansion(self):
        self.assertDenied("cat {a,b}.txt", "brace expansion")

    def test_history_expansion(self):
        self.assertDenied("cat " + chr(33) * 2, "history expansion")

    def test_nul_byte(self):
        self.assertDenied("git diff\x00rm -rf .", "NUL byte")

    def test_non_ascii_lookalike(self):
        # U+037E GREEK QUESTION MARK renders like a semicolon. It is not a shell
        # metacharacter, but the allow-list refuses it for free, which is the
        # point of using an allow-list rather than a deny-list.
        self.assertDenied("git diff;rm -rf .", "unicode lookalike")

    def test_fullwidth_semicolon(self):
        self.assertDenied("git diff；rm -rf .", "fullwidth semicolon")


class TestMutatingCommands(unittest.TestCase):
    def assertDenied(self, command):
        self.assertIsNotNone(guard.evaluate(command), "ALLOWED: %r" % command)

    def test_git_commit(self):
        self.assertDenied("git commit -m wip")

    def test_git_push(self):
        self.assertDenied("git push origin master")

    def test_git_checkout(self):
        self.assertDenied("git checkout master")

    def test_git_reset(self):
        self.assertDenied("git reset --hard")

    def test_git_add(self):
        self.assertDenied("git add .")

    def test_git_config(self):
        self.assertDenied("git config user.name x")

    def test_git_stash(self):
        self.assertDenied("git stash")

    def test_git_clean(self):
        self.assertDenied("git clean -fd")

    def test_rm(self):
        self.assertDenied("rm docs/metrics.md")

    def test_terraform_apply(self):
        self.assertDenied("terraform apply")

    def test_kubectl_apply(self):
        self.assertDenied("kubectl apply -f x.yaml")

    def test_python_arbitrary(self):
        # An interpreter is a general-purpose write primitive.
        self.assertDenied("python evil.py")

    def test_sed_in_place(self):
        # sed is absent from ALLOWED_COMMANDS entirely, rather than allowed with
        # -i denied. Removing the command removes the value-parsing surface.
        self.assertDenied("sed -i s/a/b/ docs/metrics.md")

    def test_find_delete(self):
        self.assertDenied("find . -delete")

    def test_tee(self):
        self.assertDenied("tee out.txt")


class TestPreSubcommandOptions(unittest.TestCase):
    """'git <option> <subcommand>' changes what the subcommand acts on."""

    def test_git_dash_c(self):
        self.assertIsNotNone(guard.evaluate("git -c core.hooksPath=/tmp/x diff"))

    def test_git_dash_capital_c(self):
        self.assertIsNotNone(guard.evaluate("git -C /other/repo log"))

    def test_git_git_dir(self):
        self.assertIsNotNone(guard.evaluate("git --git-dir=/other/.git log"))

    def test_bare_git(self):
        self.assertIsNotNone(guard.evaluate("git"))


class TestWritingFlags(unittest.TestCase):
    """With metacharacters gone, a flag that writes by itself is what is left."""

    def test_git_diff_output_equals(self):
        self.assertIsNotNone(guard.evaluate("git diff --output=leak.txt"))

    def test_git_diff_output_spaced(self):
        self.assertIsNotNone(guard.evaluate("git diff --output leak.txt"))

    def test_short_o(self):
        self.assertIsNotNone(guard.evaluate("git log -o leak.txt"))

    def test_flag_matching_is_not_substring(self):
        # The placeholder bypass in this repo was a substring match. Assert the
        # opposite failure does not exist here: a legitimate flag whose name
        # merely starts with an entry of WRITING_FLAGS must still be allowed.
        self.assertIsNone(guard.evaluate("git log --oneline"))
        self.assertIsNone(guard.evaluate("git diff --output-indicator-new=x"))


class TestInputIntegrity(unittest.TestCase):
    """Fail closed on anything unrecognised."""

    def test_non_string_command(self):
        self.assertIsNotNone(guard.evaluate(None))
        self.assertIsNotNone(guard.evaluate(123))
        self.assertIsNotNone(guard.evaluate(["git", "diff"]))
        self.assertIsNotNone(guard.evaluate({"cmd": "git diff"}))

    def test_empty_and_whitespace(self):
        self.assertIsNotNone(guard.evaluate(""))
        self.assertIsNotNone(guard.evaluate("   "))
        self.assertIsNotNone(guard.evaluate("git diff "))
        self.assertIsNotNone(guard.evaluate(" git diff"))

    def test_unbalanced_quote(self):
        self.assertIsNotNone(guard.evaluate("git log --format='%H"))


class TestMainFailsClosed(unittest.TestCase):
    """The stdin/JSON layer, exercised end to end."""

    def _run(self, raw):
        stdin, stdout = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = io.StringIO(raw), io.StringIO()
        try:
            guard.main()
            return sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = stdin, stdout

    def assertDeniedOutput(self, raw):
        out = self._run(raw)
        self.assertTrue(out, "no decision emitted for %r" % raw)
        decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, "deny")

    def test_malformed_json(self):
        self.assertDeniedOutput("{not json")

    def test_empty_stdin(self):
        self.assertDeniedOutput("")

    def test_json_not_an_object(self):
        self.assertDeniedOutput('["git diff"]')

    def test_missing_tool_input(self):
        self.assertDeniedOutput('{"hook_event_name": "PreToolUse"}')

    def test_missing_command_field(self):
        self.assertDeniedOutput('{"tool_input": {"description": "look at things"}}')

    def test_escaped_newline_survives_json_decoding(self):
        # The shape the hook actually receives: a JSON-escaped newline that
        # decodes into a real one inside the command string. A shell-level smoke
        # test cannot reach this path, because a literal newline makes the JSON
        # itself invalid and the guard then denies for the wrong reason -- which
        # would look like a pass while testing nothing.
        raw = json.dumps({"tool_input": {"command": "git diff\nrm -rf ."}})
        self.assertIn("\\n", raw)
        self.assertDeniedOutput(raw)

    def test_allowed_command_emits_no_decision(self):
        # Silence means "fall through to the normal permission flow", not
        # "auto-approve".
        self.assertEqual(self._run('{"tool_input": {"command": "git diff"}}'), "")


class TestLegitimateInspectionStillWorks(unittest.TestCase):
    """A guard that blocks everything is not a guard, it is a broken agent.

    A reviewer that cannot read a diff would return ACCEPT over no evidence,
    which is the worst outcome available to it.
    """

    def assertAllowed(self, command):
        reason = guard.evaluate(command)
        self.assertIsNone(reason, "DENIED %r: %s" % (command, reason))

    def test_core_review_vocabulary(self):
        for command in [
            "git diff",
            "git diff --cached",
            "git diff --stat",
            "git status --short",
            "git show HEAD",
            "git show HEAD:docs/metrics.md",
            "git log --oneline -20",
            "git log -p docs/metrics.md",
            "git diff HEAD~3..HEAD",
            "git diff HEAD~1 -- scripts/probe/analyse.py",
            "git blame docs/limits.md",
            "git rev-parse HEAD",
            "git ls-files docs",
            "git log --format=%H -5",
            "cat docs/metrics.md",
            "head -50 runs/run2/observations.jsonl",
            "tail -20 runs/run2/run.json",
            "wc -l docs/PLAN.md",
            "ls -la runs",
        ]:
            with self.subTest(command=command):
                self.assertAllowed(command)


if __name__ == "__main__":
    unittest.main()
