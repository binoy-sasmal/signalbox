# Structural credential gate — the numbers, with the output behind them

Not a gate's evidence: this directory backs claims made *about* the enforced credential
check in [`scripts/probe/check_no_secrets.py`](../../scripts/probe/check_no_secrets.py).
Review 7's F1 and F3. Every file is program output redirected to disk, with the commit it
was taken at in its header.

| File | The claim it stands behind |
|---|---|
| `ungated-scan-874e808.txt` | Disabling the expression exemption raises **10** findings — ADR 0004 §13 |
| `ungated-scan-df63680.txt` | The **7** that 10 corrected does not reproduce; the same method gives **9** |
| `tests-and-scan-72506e4.txt` | `72506e4`'s "56 tests green, 61 scanned 0 skipped" |
| `unmatched-opener-fail-first.txt` | The third intentional-exemption fixture is capable of failing, and closing that gap breaks a real value |

## Why re-run rather than transcribe

Each measurement was taken in a detached `git worktree` at the commit named in the claim,
so the numbers are reproducible by anyone with the repo and no other state. The two ungated
scans required one line of `check_no_secrets.py` to be changed; that change is included as a
`git diff` in each file rather than described.

## What capturing them changed

Two of the three claims survived unchanged and one did not. The 10 and the 56/61 confirm.
The 7 does not reproduce, and ADR 0004 §13's decomposition of how 7 became 10 was wrong in
detail — the change is two additions and one removal, and the removal happened because a
*different* exemption widened. That correction is in the ADR; the reasoning is in
`ungated-scan-df63680.txt`.

This is the argument for F3 in one line: **the numbers that needed capturing were not the
ones that turned out to be wrong, and there was no way to know that without capturing.**
