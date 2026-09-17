---
name: spec
description: Grill the user from a vague feature idea into a spec detailed enough that the implementation writes itself, then file it as a GitHub issue. Use when the user wants to spec out a feature, flesh out a big idea into an issue, or asks to be grilled.
argument-hint: [the feature idea, however vague]
---

# Grill a vague idea into a spec issue

`$ARGUMENTS` is the idea, however vague. The point of this skill is to
take a feature too large to one-shot as a prompt and, through rounds of
questions, settle every decision it contains — so that the GitHub issue
you file at the end works as the entire spec: a later session should be
able to implement it without asking a single question or making a single
silent assumption. The grilling is the compiler; the issue is the
artifact.

Map the feature as a **design tree**: every decision branches into the
decisions that hang off it.

## Before the first round

Read the code the idea touches, before asking anything. The repo answers
most questions about the *current* state — what exists, what pattern the
codebase already uses for this kind of thing — and a question the code
answers is a wasted round-trip. First-round questions should already be
grounded: "the uploads demo streams through Django; should this do the
same or serve redirects?" beats "how should files be served?".

## The rounds

Work the tree in **rounds**. The **frontier** is every decision whose
prerequisites are already settled: the questions you can ask *now*
without guessing at answers you haven't heard yet. Ask the whole
frontier in one round: number each question and give your recommended
answer. Then wait for the user's answers before the next round.

Write the round out in the text format below first — the full round
stays in context that way — then, when the AskUserQuestion tool is
available, collect the answers through it: one entry per question, the
recommended answer as the first option labeled "(Recommended)", and
the other serious contenders as the remaining options — the tool adds
"Other" for free-text itself. A round larger than the tool's
four-question limit goes out as consecutive calls. A question with no
enumerable options (a name, a URL) stays text-only; without the tool,
the text format is the whole round.

Format each question like so:

```
❓ **Q1 — <question title>**: <question body, possibly multiple
paragraphs, including the choices if it has discrete options>

➡️ <your recommended answer>
```

Recommendations should lean on the patterns this codebase already has —
CLAUDE.md is the pattern book, and the recommended answer is usually
"the way this repo already does it", so the user's fast path through a
round is accepting recommendations and typing real answers only where
they disagree. A question whose answer depends on another question still
open in this round belongs to a *later* round, not this one.

Each round the user answers reshapes the tree: settled decisions push
the frontier outward and unblock questions that depended on them.
Recompute the frontier and ask the next round.

Finding *facts* is your job, never the user's. When a frontier question
needs a fact from the environment, dispatch a subagent to find it; don't
ask the user for anything you could look up yourself. Don't block on it:
a running exploration is an unsettled prerequisite, so only the
questions downstream of it wait for the subagent to report; ask the rest
of the frontier now. The *decisions* are the user's: put each to them
and wait.

The grilling is done when the frontier is empty: every branch of the
design tree visited, nothing left silently assumed.

## The issue

Draft the issue in the conversation, ask once for corrections, then file
it with `gh issue create` and report the number — a later session picks
it up through shipit's issue flow (branch `<N>-...`, PR body
`Fixes #<N>`). No AI attributions anywhere in the issue.

The bar for the body: someone with this codebase but no access to this
conversation implements the feature without asking a question. Sections:

- **Problem** — what the user gets, from their perspective. Short.
- **Decisions** — the settled tree: each question that shaped the
  design and the chosen answer, with the why wherever a future reader
  might relitigate it.
- **Shape** — the touch list in this repo's own vocabulary: models and
  their fields, services and selectors by their `<entity>_<action>`
  names with signatures, endpoints with routes, methods, auth posture,
  scopes and response shapes, tasks and beat entries, pages, layouts,
  components and stores, permissions, cache keys, index contracts.
  Signatures and small schema sketches are welcome — this issue is
  consumed soon, not archived, so precision beats durability.
- **Tests** — the rules worth pinning, named the way this repo names
  tests: after the rule they enforce.
- **Out of scope** — what was deliberately cut, so nobody helpfully
  adds it back.

There is no "Open questions" section. The grilling ends when there are
none.
