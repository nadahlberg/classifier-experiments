# initialize-project progress

## Decisions

All filled at the interview, except the fork point (finalize) and the
secrets outcome (configure).

- mode: existing — remotes exist; the old code lives in `archive/` (user chose this name over `references/`; `archive/` is committed, not gitignored, and excluded from lint, tests, image builds, and the rename the same way `references/` would be). Work on branch `initialize-project` off `main` (PR #1, the archive move, was merged by the user).
- installs: none needed (docker 27.4.0 daemon up, uv 0.9.5, gh authenticated as nadahlberg)
- slug: clx
- display name: Classifier Experiments
- keep/drop:
  - Chat demo: drop
  - Admin Codebase tab: drop
  - API tokens: keep
  - Uploads demo: keep
  - Elasticsearch: keep
  - Celery: keep
  - MCP server: keep
  - PWA: keep
  - Sentry: keep
  - Email verification: keep
  - Admin surface: keep
  - infra / Pulumi: keep
  - Layout demos: drop
  - reset-database workflow: drop
- github: nadahlberg/classifier-experiments, public (unchanged)
- branch rules: apply
- secrets: walk through at configure (none set as of interview; outcome recorded there)
- autodeploy: on
- merge method: merge commit
- fork point: — (marker `.template-rev` present: 82dcfbe8ba544171c440c9c76f60ed60cf6965a6, https://github.com/nadahlberg/clx.git; recorded at finalize)

## Stages

- [x] 1. Interview
- [x] 2. Prerequisites
- [x] 3. Rename
- [x] 4. Boot and verify
- [ ] 5. Strip (one box added per dropped feature)
  - [x] chat-demo
  - [x] admin-codebase-tab
  - [ ] layout-demos
- [ ] 6. Finalize
- [ ] 7. Configure the repo
- [ ] 8. Publish
