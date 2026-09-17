---
name: check-branch-rules
description: Check whether main has branch protection (required CI checks, no force pushes or deletion, PRs required) and offer to set up whatever is missing
---

# Check branch rules

Check the repo's rulesets and classic protection for main:

```sh
gh ruleset list
gh api repos/{owner}/{repo}/branches/main/protection
```

Report which of these three rules are in place and which are missing:

1. Required status checks: `pre-commit`, `migrations`, `mypy`, `test`.
2. Force pushes and branch deletion blocked on main.
3. Pull request required before merging.

If anything is missing, ask the user whether to set it, then create one
ruleset covering the missing rules via
`gh api repos/{owner}/{repo}/rulesets -X POST`. Never require approvals.
