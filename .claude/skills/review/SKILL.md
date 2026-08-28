---
description: Adversarial project-manager review of the current work against the
  Signalbox gate criteria. Runs in an isolated context that cannot see this
  conversation.
argument-hint: "[git-range | gate-N | blank for uncommitted + HEAD]"
disable-model-invocation: true
context: fork
agent: gate-reviewer
background: false
---

Review this scope of Signalbox work: $ARGUMENTS

If the scope above is empty, review the uncommitted working tree plus the most
recent commit: `git status --short`, `git diff`, `git diff --cached`, and
`git show HEAD`.

Derive the change from git yourself. You have not been told what was done, and you
should not go looking for an account of it.

Apply your standing instructions in full: artefacts only, all ten rubric items,
halt on any escalation condition, and one of the four adjudications at the end.
