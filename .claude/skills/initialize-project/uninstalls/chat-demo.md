# Uninstall the chat demo

Removes the streaming chat demo and the agent framework end to end:
the `agents/` package, the chat models, the turn and title tasks, the
SSE endpoints, the chat page, and the litellm dependency. The feature
is large and touches every layer, so start from
`grep -rni "chat\|agents\|litellm\|openai" clx/` and follow what
you find rather than trusting the list below to be complete. **This
removes models: run the migration reset afterwards.**

Keep two things the feature built but the machinery owns:

- The async-view support in `clx/app/api/utils/decorators.py` and
  its tests in `clx/app/tests/test_api_authentication.py` /
  `urls_api_auth.py` — `api_auth` wrapping coroutine views is generic
  machinery that outlives its one SSE consumer.
- The `three_panel` layout — other pages use it.

## Remove whole files

1. The whole `clx/app/agents/` package.
2. `clx/app/templates/pages/demos/chat.html` and the whole
   `clx/app/templates/cotton/demos/chat/` directory.
3. `clx/app/tests/test_demo_chat.py`.

## Shared-file edits

4. `clx/app/models/demo.py`: delete `DemoChatThread` and
   `DemoChatMessage` (and their re-exports in
   `clx/app/models/__init__.py`).
5. `clx/app/services/demo.py`: delete the chat block — the whole
   tail of the file from `TITLE_MODEL` down (`demo_chat_message_create`,
   `demo_chat_message_send`, `demo_chat_turn_run`,
   `demo_chat_turn_cancel`, `demo_chat_thread_rename`,
   `demo_chat_thread_delete`, `demo_chat_thread_state_update`,
   `demo_chat_thread_compact`, `demo_chat_thread_title_generate`,
   `_TurnLost`, and every `_`-prefixed helper and constant below them).
6. `clx/app/selectors/demo.py`: delete the `demo_chat_*` selectors
   and their private helpers (`_serialize_call`, `_parse_arguments`).
7. `clx/app/tasks/demo.py`: delete `demo_chat_turn_run_task` and
   `demo_chat_thread_title_generate_task` (and their re-exports in
   `clx/app/tasks/__init__.py`).
8. `clx/app/api/demos.py`: delete the chat endpoints and helpers —
   `chat_thread_list`, `chat_message_send`, `chat_thread_events`,
   `chat_turn_cancel`, `chat_thread_rename`, `chat_thread_delete`,
   `_thread`, `_event_stream`, `_snapshot`, `_sse`, and the `CHAT_*`
   constants; in `clx/app/urls.py`, the six `chat/threads/`
   entries in `demos_api_patterns` and the `path("chat/", ...)` entry
   in `demos_view_patterns`.
9. The `chat` view in `clx/app/views/demos.py`.
10. `clx/app/cache.py`: delete `DEMO_CHAT_CANCEL_CACHE_TTL`,
    `demo_chat_cancel_cache_key`, and `demo_chat_events_channel`.
11. `clx/settings.py`: delete `OPENAI_API_KEY`;
    `docker-compose.yml`: the `OPENAI_API_KEY` env on the django and
    celery services; README: the `OPENAI_API_KEY` row in the
    Environment table. (Nothing in `infra/` names it —
    `deploy_secrets.py` passes secrets through generically.)
12. The Chat tile in `clx/app/templates/pages/demos/index.html`.
13. `pyproject.toml`: the `litellm` dependency and `"litellm.*"` in
    the mypy overrides; then `uv lock`.

14. The agents entries in the pattern checks and the explorer:
    in `clx/app/checks/imports.py`, the `"agents"` rows of
    `LAYER_PACKAGES` and `ALLOWED_IMPORTS`, the `"agents"` member in
    the `selectors` and `services` rows, and `"agents"` in
    `DECLARED_APP_MODULES`; in `clx/app/checks/calls.py`,
    `clx.app.agents` in `READ_LAYERS`; in
    `clx/app/selectors/codebase.py`, `build_agents`,
    `build_agent_tool`, and their call in `build()`; in
    `cotton/admin/codebase/explorer.html`, the `agent` and
    `agent-tool` rows of `CODEBASE_LAYERS` and the `agent` key in
    `CODEBASE_GROUP_RANK`; in `clx/app/tests/test_codebase.py`,
    `test_inventory_covers_every_registered_agent_and_tool`.

After the deletions, prune the now-unused imports in every touched
module — ruff flags them in the verify suite.

Delete the "## Agents" section of CLAUDE.md and the `agents/` line in
its app-structure tree, then grep CLAUDE.md for `chat` and `agent` to
catch stragglers. Run the migration reset and the verify suite.
