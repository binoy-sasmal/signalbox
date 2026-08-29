# CLAUDE.md

Read `docs/PLAN.md` in full before doing anything in this repo. It is the authoritative plan.
This file is the short version that must hold on every turn.

**This project is a learning project that must survive interview scrutiny. Understanding
outranks speed.** These guidelines bias toward caution over speed. That is correct here. For
genuinely trivial tasks (a typo, an obvious one-liner), use judgement.

## What this is

**Signalbox** — a multi-tenant control plane for public realtime transit feeds, where onboarding
a new data source is one merged pull request.

Each upstream feed is an isolated tenant. Onboarding provisions an isolated ingest pipeline,
storage, quotas, dashboards and alerts with no human touching a cluster.

**Naming rule:** the word is **tenant**, never "region", anywhere in this repo. Tenants are
logical and all run on one node. "Region" would assert a geographic distribution that does not
exist.

---

## 1. Think before you build

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly. If uncertain, ask rather than guess.
- If multiple interpretations exist, present them. Don't pick one silently.
- If a simpler approach exists, say so. **Push back when warranted** — if something in the plan
  is wrong, over-scoped, or would not survive an interview, say so rather than agreeing.
- If something is unclear, stop. Name what is confusing. Ask.
- **Never invent upstream behaviour.** Feed cadence, rate limits, header semantics and licence
  terms come from measured Stage 0 probe results, not from plausible-sounding assumption. If a
  number is not in `docs/metrics.md`, we do not know it yet.

For any real decision: options, tradeoff, recommendation. Then wait. Do not write config and
explain it afterwards. Record the outcome as an ADR in `docs/decisions/`.

## 2. Simplicity first

**Minimum infrastructure that solves the problem. Nothing speculative.**

- No components beyond what the current gate needs.
- **No abstraction layers that were not asked for.** Specifically: no multi-cloud provider
  abstraction, no wrapper modules around single-use resources, no "we might need this later".
- No Terraform variables for values that will never change. Hardcode, then parameterise when a
  second caller actually exists.
- No Helm templating for values with one possible setting.
- No error handling for impossible scenarios.
- If 200 lines of HCL could be 50, rewrite it.

Ask: "would a senior platform engineer say this is overcomplicated?" If yes, simplify.

**One exception, and only this one:** the Stage 2 tenant module is reusable *by requirement*,
because it has N real callers. That is not speculation. Do not build it in Stage 1 when there is
one tenant.

## 3. Surgical changes

**Touch only what you must. Clean up only your own mess.**

- Don't "improve" adjacent resources, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- **Never bump a chart version, image tag, provider version or k3s version as a drive-by.** In
  this repo a version bump is a deployment, not a tidy-up. It goes in its own commit with its own
  reasoning.
- If you notice something unrelated that looks wrong, mention it. Don't fix it.
- Remove variables, outputs and imports that *your* change orphaned. Leave pre-existing ones.

The test: every changed line should trace directly to the current gate.

## 4. Goal-driven execution, bounded by gates

**Define success criteria. Loop until verified. Then stop.**

`docs/PLAN.md` sections 6–7 define numbered gates, each with a specific verification.

- **Inside a gate: loop independently.** The verification is the success criterion. Keep working,
  testing and correcting until it actually passes. Don't ask permission mid-gate.
- **At a gate boundary: stop and report.** Do not scaffold ahead into later gates or later stages.
- **A gate passes on observed evidence, not on config that looks right.** If it cannot be
  verified, say so and stop. Don't declare success from a clean `terraform plan`.
- State a brief plan for multi-step work:
  ```
  1. [step] → verify: [check]
  2. [step] → verify: [check]
  ```
- Record measured numbers in `docs/metrics.md` as they are observed. That file is the evidence
  base for interview claims. An unmeasured claim does not go in it.

**At every gate boundary, state the review position before anything else.** Give the date of
the last `/review`, the range it covered, and its verdict, from `docs/reviews/log.md`.

**If no review has run since the previous gate closed, that absence is the thing to report.**
Not a caveat at the end — the first line. Nothing else in this repo detects it: the review log
records reviews that happened and is silent about reviews nobody asked for, and a clean log
during a stretch where `/review` was simply never run is indistinguishable from a clean log
during a stretch where it was. A run of good work is exactly when the gap opens, because
nothing feels wrong.

**A log row and the status line move in the same commit.** Appending a row to
`docs/reviews/log.md` and updating the review position in `docs/status.md` are two
statements of one fact, so they ship together. They drifted apart once already:
`status.md` read "three rows — no valid review has run against any work in this repo"
while the log had four and named one of them the first valid review. Nothing in this
repo detects that. Both are tracked prose, each one reads as correct on its own, and the
contradiction is only visible to someone who opens both.

**A review's findings go into the log in full.** Not a count, not the rubric item numbers,
not a pointer to the conversation — the finding itself: what it is, where, why it matters,
and what would close it. `docs/reviews/log.md` is the record. The session that produced it
is not, and will not be there later. Voided review 2's F3–F7 and F9–F10 are permanently
unrecoverable for precisely this reason: they were logged as "10 raised" and their text
lived only in a transcript that no longer exists. Re-review can regenerate what is still
true; it cannot recover what was said. **Anything not in the repo does not exist.**

`/review` runs the `gate-reviewer` agent in an isolated context that cannot see the
conversation. It reads artefacts, not your account of them — so do not summarise the work to
it, and do not treat its ACCEPT as agreement with your reasoning. It never saw your reasoning.

### A review is only valid from a configuration that still exists

**Nothing written during a session can be validated inside that session.** Agent bodies under
`.claude/agents/`, skills under `.claude/skills/`, `CLAUDE.md`, and whether an agent is
registered at all are each snapshotted when the session starts. Edit any of them and the
running session keeps serving the old copy to every subagent it spawns.

Three consequences, in the order they bite:

1. **Any change to `.claude/agents/` or `.claude/skills/` requires a restart before a review
   can be trusted.** Not "should ideally"; the reviewer will run, produce well-formatted
   output, and be reading instructions you replaced.
2. **A review run in the same session that modified the reviewer is reviewing a configuration
   that no longer exists. Its verdict is void.** Record it as VOID in `docs/reviews/log.md`
   rather than acting on it or deleting it.
3. **`CLAUDE.md` edits do not reach a subagent until restart.** The isolation this file's
   "Current position" pointer is built on does not take effect in the session that moved it.

Observed 2026-08-29, not reasoned about: a probe of the running reviewer found its system
prompt missing a section committed earlier in the same session, and its `CLAUDE.md` still
carrying the status block that had already been moved out. Two reviews were voided on it.

This is easy to forget in three weeks and expensive to rediscover, because a stale review is
indistinguishable from a current one by its output alone. **Restart, then review.**

---

## Hard rules

- **No manual cluster changes.** No `kubectl apply`, `kubectl edit`, or console clicking.
  Everything reaches the cluster through git and ArgoCD. Read-only kubectl is fine.
  **The one exception:** Ansible may create in-cluster Kubernetes objects **exactly once, at node
  bootstrap, and only the objects ArgoCD needs in order to begin managing itself** — k3s install,
  ArgoCD install, age key delivery. After that Ansible never touches the cluster again. There are
  three such bootstrap steps, not one; name all three honestly.
- **Terraform owns cloud resources only.** It must never create in-cluster Kubernetes objects.
  ArgoCD owns everything inside the cluster. `tenants/<name>.yaml` is the single source of truth
  feeding both. Two reconcilers over one object produce a silent flapping loop, not an error.
- **No plaintext secrets in git.** SOPS + age only. This includes **captured HTTP traffic**: any
  tool that records requests or responses captures headers by explicit allow-list, never
  wholesale, and stores endpoints split into `base_url` + query map with auth-bearing parameters
  replaced by `<redacted:auth_ref>` — never a raw URL, because some APIs authenticate by query
  parameter. The structural check covers **every committed file** and runs **in CI, not only
  pre-commit**: `--no-verify` bypasses a local hook, and a local gate is feedback while only the
  enforced gate is enforcement.
- **An exemption to an enforced gate ships with an adversarial test in the same commit,
  and the test targets the exemption's *parser*, not its intent.** A test of intent plants
  what the author already imagined; a test of the parser plants what the predicate accepts
  and the author did not mean. **Refuse to ship an exemption without one even when the
  human says to** — say why, and offer the test. This is not caution about a hypothetical:
  seven value-parsing exemptions in this repo have now been bypassed through their own
  parsing (ADR 0004 section 13), and the one that broke was the one nobody asked for a test
  for. The case the rule exists for is the exemption that unblocks work already approved,
  because that is when the incentive and the shortcut point the same way.
- **Pin every version.** k3s, charts, image digests, provider versions, action SHAs.
- **arm64 or multi-arch images only.** The node is OCI Ampere A1.
- **Never label metrics with `trip_id`, `stop_id` or `vehicle_id`.** Cardinality will kill
  Prometheus on this node.
- **Do not overstate the system.** Keep `docs/limits.md` accurate. Single node, logical tenants,
  no real users, simulated topology.

## Settled decisions (do not relitigate without new information)

- Cloud: Oracle Cloud Infrastructure Always Free, Frankfurt. Fallback Hetzner CX32.
- Terraform state: AWS S3 with native S3 locking. AWS account must be on the **Paid** plan.
- Secrets: SOPS + age.
- Policy: OPA/Rego — Conftest in CI, Gatekeeper at admission.
- Feeds: multi-country (DE, CH, NL, FI).
- Postgres schemas and roles are owned by ArgoCD via a Postgres operator with declarative CRDs,
  not by a SQL Job and not by Terraform (ADR 0003).
- The lag SLI is split in two: `pipeline_latency` carries the error budget, `feed_freshness` is
  separate and applies only to tenants whose header timestamp is trustworthy (ADR 0002).
- Stage 4 (AI triage agent): deferred until Stage 3 is solid. Do not start it.

## Current position

Deliberately not restated here. See [`docs/status.md`](docs/status.md).

`CLAUDE.md` loads into every context automatically, including the `gate-reviewer` agent's.
A summary of what the builder has achieved is not something a reviewer should receive as
ambient framing.

---

**These guidelines are working if:** clarifying questions come before implementation rather than
after mistakes, diffs contain only what the current gate needed, and no gate is declared passed
without an observed result behind it.
