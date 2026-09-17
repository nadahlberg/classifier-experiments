---
name: document-codebase
description: Write or extend a codebase wiki, using the bundled lint_docs.py to find what is undocumented and to verify every citation still resolves, then build_docs.py to publish the pages with GitHub permalinks. Use when asked to document the codebase, write a wiki page, explain how part of the system works in docs, or fix stale documentation references.
argument-hint: [docs-dir]
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash]
---

# Documenting a codebase

The goal is a coherent wiki that explains this codebase to a person who has
not read it. Not an API reference — the reader can read signatures. The wiki
records what the source cannot: why a boundary exists, which of two
similar-looking things is the real entry point, what breaks when a rule is
ignored.

A page holds one subject. A wiki of twenty short pages a person would
actually read is better than one of six pages holding three subjects each —
prefer more pages, shorter pages, and as much directory structure as the
subjects need.

`scripts/lint_docs.py`, bundled with this skill, indexes every definition
and every in-package call or reference, gives each a twelve-character id, and
checks the wiki against that index. Use it to find work and to verify the
result; deciding what to write stays with you.

An id is two halves: the first six characters identify the symbol, the last
six hash its code. So a symbol whose body changes keeps its identity and
gets a new id — which is how the linter can tell *changed* from *deleted*,
and tell you which page to revisit. Reformatting does not count as a change;
the hash is taken over the parsed structure, not the raw text.

## Arguments

`$ARGUMENTS` is the docs directory. Default to `docs` when empty.
Create it if it does not exist. Everywhere below, `<docs>` means that path
and `<skill-dir>` is the directory holding this SKILL.md.

The wiki is two trees. **Sources live in `<docs>/.src`** — that is where
every page is written and edited, and where the `sym:` citations live.
`build_docs.py` mirrors `.src` into `<docs>`, replacing each citation with
a GitHub permalink so the built pages read anywhere. Never edit a built
page by hand; the next build overwrites it. If `<docs>` has pages but no
`.src` yet, first `git mv` the pages into `.src`, then build.

Run every command from the repository root; the script treats the working
directory as the root and finds packages by looking for a top-level
`__init__.py`. Pass `--package <path>` to override that, repeatably.

## The loop

Each pass is open-ended: read the state of the wiki, decide what it most
needs, do that, verify, report, stop.

**A pass writes a little and may reshape a lot.** A page or two of new
writing is a normal pass. So is splitting a page that has grown a second
subject, merging two that were always one, rewriting a page whose premise a
CHANGED entry has invalidated, renaming and resequencing pages so the wiki
reads in a sensible order, or bringing older pages up to the language
standard below — any of those can be the whole of a pass, and reshaping is
as much the work as writing is. Writing many pages in one batch produces
pages that restate the index, so decide what the finished wiki should look
like and take the single step that moves it there.

### 1. Orient

```sh
python <skill-dir>/scripts/lint_docs.py lint --docs <docs>
```

Read it top to bottom and clear the first two sections before writing
anything new.

**CHANGED** — the symbol still exists, but its code is different from when
the page was written. Each entry prints the symbol's current location and
the citing line's text, so triage starts from the lint output: read the
current source, read what the page claims, and decide whether the claim
still holds. Update the prose if it does not, then swap the old id for the
new one. Never swap the id alone: that silences the warning without
checking it, which is the one thing this section exists to prevent.

**REMOVED** — the symbol is gone. Delete or rewrite whatever depended on it;
a paragraph explaining code that no longer exists is worse than no paragraph.

Only then look at coverage and the by-module counts.

### 2. Choose the page

```sh
python <skill-dir>/scripts/lint_docs.py list --uncovered --module <prefix> --docs <docs>
python <skill-dir>/scripts/lint_docs.py list --uncovered --kind def --docs <docs>
python <skill-dir>/scripts/lint_docs.py show <id> --docs <docs>
```

`list` prints each symbol with its location and, for anything a packed
citation could absorb, the nearest owner as `covered by sym:<id>+`. `show`
expands one id — location, enclosing symbols, everything its own `+` would
cover, and every page that cites it; a stale id resolves to the current
symbol by its identity half, so it also traces CHANGED entries.

Pick a **subject a person would recognise** — "how a request becomes a
response", "authentication", "how background work is scheduled". Then read
the actual source for that subject. The index tells you what exists; only the
source tells you why.

**Choose by coherence; use the counts only to break ties.** Ask first
whether the page would make sense read start to finish by someone who
opened it on its own. Among subjects that are equally coherent, let the
by-module counts point you at the denser one. The counts decide order,
never content — everything gets covered eventually, so they only decide
what comes first.

A module is rarely a subject on its own, and a set of unrelated leftover
symbols never is. One page that follows a single path through four modules
is usually better than four pages that each describe one module — because
the path is the subject, not because consolidating is a goal.

Before writing, decide which of the three kinds under **Page kinds** the
page is. When the repo describes its own architecture — a pattern book, a
contributing guide, a listing of its layers — derive the mechanism and
feature lists from that description; invent them only where the repo is
silent.

### 3. Write it

Prose, in the register described under **Language** below, in a page under
`<docs>/.src`. Explain the shape first, then the parts, then the
consequences.

Cite with the `sym:` scheme — the link text is yours, only the id is parsed:

```markdown
The endpoint [`health`](sym:ae9bf8651c40) parses nothing and calls
[`check_services`](sym:ba8c6be9d217), so the two interfaces cannot disagree.
```

Relationships have ids of their own. When the interesting fact is that A
calls B, cite the edge rather than the two ends — that is the claim you are
actually making.

**Never cite a symbol you did not explain.** A citation asserts that the
surrounding sentence says something true and non-obvious about that symbol.
A page that cites forty ids and explains ten is worse than one that cites
ten, because it reports as covered and nobody will revisit it.

### Packing several ids into one claim

Often one honest sentence really is the claim for more than one id. Two forms
say so:

```markdown
A list:     [the two decorators](sym:0977c8254e91,24f1ec03bbc1)
A subtree:  [`login.html`](sym:6e8808ab21e8+)
```

A **list** covers exactly the ids named. A trailing **`+`** covers the symbol
*and everything it owns* — nested definitions, a class's methods and
attributes, a template's blocks, and every edge that symbol is the owner of.

The built permalink points at the **first** id in a list, so lead with the
symbol the sentence is chiefly about.

`+` is for when you have explained something properly and its internals hold
no separate surprise: a template whose structure is identical to its thirteen
siblings, a method whose body is the three attribute reads you just walked
through. The bar is that **a reader who read your paragraph would not be
surprised by anything inside the subtree.** If some part of it would surprise
them, that part has its own claim to make and `+` is the wrong tool.

So `+` widens a claim. It is not a way to avoid making one, and it does not
lower the bar for the parent — a packed citation needs the parent explained
*more* thoroughly than a bare one, because it is now speaking for its
children too. Using `+` to raise the coverage number produces a report of
coverage the wiki does not have.

### 4. Verify

```sh
python <skill-dir>/scripts/lint_docs.py lint --docs <docs>
```

CHANGED and REMOVED must both be empty — the script exits non-zero
otherwise. Report the coverage delta and what is left, in the terms above:
which pages are still unwritten, and anything you are reporting as a finding
about the code. "Left out deliberately" is not one of the options.

### 5. Build

```sh
python <skill-dir>/scripts/build_docs.py --docs <docs>
```

Once lint is clean, build. This mirrors `.src` into `<docs>`, replaces each
citation with a permalink, and prunes built pages whose source is gone. It
refuses to write while any citation is unresolved, and it warns when a
permalinked file has uncommitted changes — permalinks resolve against HEAD,
so pages built before the code is committed point at a commit that does not
contain it. When the warning fires, rebuild after the commit.

## Findings in the code

Documenting means reading source closely, so a pass sometimes turns up
problems in the code itself: a bug, two places that quietly disagree, a
violation of a pattern CLAUDE.md or the surrounding code establishes.
These are findings, not material — never write the wiki around one, and
never document a bug as intended behaviour.

Collect them as you work. When the pass ends, present them to the user as a
short list — what and where, one line each — and for each one propose
either opening an issue or addressing it immediately, with a
recommendation: a trivial, low-risk fix is worth offering to do now;
anything that would widen the pass belongs in an issue. Do not fix any of
it silently mid-pass.

## Language

Write in the register of reference documentation: a reader arrives to look
something up, reads the sentences that answer them, and leaves. Four habits
produce that register:

- **Titles are labels.** A page's H1 uses the same words as its filename
  and as the index entries that link to it, so the reader lands on the
  heading the link named. Section headings are noun phrases naming their
  subject — "The beat schedule", "Storage probes" — so a reader can
  navigate the page from its headings alone.
- **The claim opens the section.** The heading names the subject; the
  first sentence under it states, in plain words, the one thing the
  section establishes about that subject. Everything after supports that
  sentence.
- **Each thing has one name: the code's.** Call a symbol, file, or concept
  what the code calls it, and use that same name at every mention on every
  page. When a group of things needs a collective name the code never
  gives it, use an ordinary description — "the components every layout
  mounts" — and repeat that description wherever the group appears.
- **Sentences state facts.** Each sentence says what something is, why it
  is that way, or what happens when it changes, in words that mean exactly
  what they say. A finished sentence gives the reader everything in one
  reading and reads the same on the second. For example: "The probes
  return `False` instead of raising, because the caller renders results
  and never handles errors."

Hold existing prose to the same standard as new prose: a pass that touches
a page for any reason also brings that page's title, headings, names, and
sentences to this register, the same way it refreshes the page's
citations — language upkeep and citation upkeep are the same maintenance.
When a title and its filename disagree, make them agree, renaming the file
when the filename is the wrong half; update the links that point at it,
and the build prunes outputs whose source moved.

## Page shape

**A page is one subject.** The test: state what the page establishes in a
single sentence with no "and". If you cannot, it is two pages — and
splitting it is better work than polishing it.

**Keep pages short.** A reader should finish one in a few minutes. Length
usually means the page has taken on a second subject, so when a page grows
long, look for the seam instead of trimming sentences. Shorten by moving
the second subject to its own page, never by cutting the non-obvious
explanation — the explanation is the page.

**Kind-mixing is the two-subjects smell in another form.** A feature page
that drifts into explaining the mechanism it rides on, or a mechanism page
that hosts one feature's quirks, is holding two subjects — split it into
two pages, one per kind, linked to each other.

## Structure

### Page kinds

Every page is one of three kinds:

- **Platform** — how the project runs anywhere it runs: local dev, CI,
  deploy, infrastructure, configuration, the toolchain.
- **Mechanisms** — horizontal cross-sections, "how every X works": routing,
  persistence, caching, background work, errors, templates, the auth
  machinery.
- **Features** — vertical stacks, "how Y works end to end": one
  user-recognizable capability traced through every layer it touches.

The README is the fourth thing: orientation, not explanation.

The top of the tree tends toward kind buckets or recognizable subjects, and
loose pages at the root are the smell a reshaping pass fixes — most pages
live in a directory. Directory names stay the subject's own words; the
literal names `platform`, `mechanisms`, and `features` name kinds, never
paths.

### The tree

The wiki is a tree, not a flat list. Nest `<docs>/.src` however the subject
wants — the build mirrors the tree into `<docs>`, so links between pages are
ordinary relative links and survive the build unchanged:

```
docs/.src/
  README.md              the index: what is here, where to start
  request/
    README.md
    lifecycle.md
    errors.md
  mcp/
    README.md
    tools.md
    auth.md
```

- Create a directory at about three pages. Below that, nesting adds a
  level without adding order.
- Every directory gets a short index naming its pages and the order to read
  them in. Someone who lands in a subdirectory should not have to guess.
- `docs/README.md` is the entry point, and the one page whose job is
  orientation rather than explanation. Its index groups entries by kind —
  headings in your own words, every entry under exactly one — and reading
  order lives within each group, not across the whole list. Keep it
  current: readers use it to decide where to go, so every entry must match
  the page it points at.
- Pages link to each other with ordinary relative markdown links. A claim
  explained on another page gets linked, not restated.

## What makes a page good

- **It opens with what it establishes.** A first sentence like "Health
  checks exist once and are exposed three times" tells the reader what the
  page will show; "this module contains four functions" tells them
  nothing the index did not.
- **It explains the non-obvious.** Why the probes swallow their exceptions.
  Why the registry is a dict rather than a list of ifs. Why one layer is
  forbidden from importing another.
- **It says what would break.** Constraints are only useful if the reader
  knows the failure mode.
- **It survives a refactor.** Describe intent, not line numbers.

## What to avoid

- One page per module or per class.
- Restating a signature in English.
- Citing ids, with or without `+`, to raise the coverage number.
- Padding a page with adjacent material because it happens to be uncovered.
  A page is a subject, not a container for whatever is nearby. If a symbol
  only fits by being mentioned in passing, it belongs on another page —
  usually one that does not exist yet, which is what the next pass is for.
- Letting a page keep growing because the subject is "basically related".
- Writing about code you have not read.
- Collecting every setting into one table. A reference table is not a wiki
  page, and it puts each value as far as possible from the thing it affects.

## Configuration counts

Every setting and environment variable earns a mention, once, on the page
where it conceptually belongs — storage settings with storage, OAuth
settings with authentication, `DEBUG` and `ALLOWED_HOSTS` with deployment.

Naming a setting is not documenting it. What a reader needs is the
behaviour at the edges: what the value defaults to, what breaks when it is
unset, which values are mutually exclusive, and which ones silently change
behaviour rather than failing. That is invisible in the name and usually
invisible in the assignment too.

A dedicated configuration page is right only for values with no other home.

## Coverage

**The target is zero uncovered, and nothing is exempt.** Not in one pass — a
wiki grows over many — but every pass closes a real part of the gap, and no
kind of symbol is written off as not needing a home.

The rule is absolute because exemptions compound: "this sort of thing
doesn't need documenting" is a judgement made once and then applied a
hundred times without being re-examined, and it eventually swallows the
cases that genuinely did need documenting.

When a symbol resists, it is one of three things:

- **Its page does not exist yet.** Usually the answer. Write it — a new
  short page beats attaching the symbol to the nearest existing one.
- **It belongs inside a claim you already made.** Pack it in with `+` or a
  list, having checked the surrounding prose really does account for it.
- **Nothing true and non-obvious can be said about it at all.** That is a
  finding about the *code*, not about the wiki: it is dead, misnamed, or in
  the wrong module. Report it, say what should change, and — if the tooling
  is what is wrong — fix the tooling. Do not leave it as a standing
  exception.

Cover things by finding the page where each genuinely belongs, never by
attaching them to the nearest one. Coverage never justifies a citation
without an explanation.

`lint --strict` also exits non-zero while anything is still uncovered. It
reports the end state; it is not a per-pass gate.
