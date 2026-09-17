"""The chat engine: pluggable agents, streamed turns, and their bookkeeping.

Everything here fakes litellm at the module seam
(`clx.app.services.demo.litellm`) and captures published events by
faking the redis client behind `_publish`, so no test talks to a model
provider or to redis while `_publish` itself still runs. The SSE relay
tests fake the redis module inside `api/demos.py` the same way; only the
database is real.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.db import connections
from django.utils import timezone

from clx.app.agents import AGENTS, Agent, Tool, ToolOutput
from clx.app.agents import demo as demo_agent_module
from clx.app.agents.demo import CheckWeather, DemoAgent
from clx.app.api import demos as demos_api
from clx.app.cache import demo_chat_cancel_cache_key
from clx.app.exceptions import ApplicationError
from clx.app.models import DemoChatMessage, DemoChatThread, User
from clx.app.selectors.demo import (
    demo_chat_thread_context_tokens,
    demo_chat_thread_get,
    demo_chat_thread_list,
    demo_chat_thread_snapshot,
)
from clx.app.services import demo as demo_service

pytestmark = pytest.mark.django_db


class JsonStateAgent(Agent):
    """Registered without a state template, to pin the JSON fallback."""

    name = "test_json_state"
    model = "openai/test"


class FakeLLM:
    """A litellm stand-in: queued responses, recorded calls, fixed cost."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[Any] = []
        self.cost = 0.0123
        self.error: Exception | None = None

    def completion(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        response = self.responses.pop(0)
        if kwargs.get("stream"):
            return iter(response)
        return response

    def completion_cost(self, **kwargs: Any) -> float:
        return self.cost


@pytest.fixture(autouse=True)
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture published events instead of talking to redis."""
    published: list[dict[str, Any]] = []

    class RecordingRedis:
        def publish(self, channel: str, payload: str) -> None:
            published.append(json.loads(payload))

    monkeypatch.setattr(
        demo_service, "_redis_client", lambda: RecordingRedis()
    )
    return published


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    """Swap litellm for the fake and make the flush loop run every chunk."""
    fake = FakeLLM()
    monkeypatch.setattr(demo_service, "litellm", fake)
    monkeypatch.setattr(demo_service, "FLUSH_INTERVAL_SECONDS", 0)
    return fake


def run_async(main: Callable[[], Awaitable[Any]]) -> Any:
    async def run() -> Any:
        try:
            return await main()
        finally:
            await sync_to_async(connections.close_all)()

    return asyncio.run(run())


def make_thread(
    user: User, status: str = DemoChatThread.Status.PENDING
) -> DemoChatThread:
    """A thread whose turn is queued, which is what a worker may claim."""
    thread = DemoChatThread(user=user, agent="demo", status=status)
    thread.full_clean()
    thread.save()
    return thread


def add_message(
    thread: DemoChatThread, data: dict[str, Any], **kwargs: Any
) -> DemoChatMessage:
    return demo_service.demo_chat_message_create(
        thread=thread, data=data, **kwargs
    )


def text_chunk(text: str) -> SimpleNamespace:
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def tool_chunk(
    call_id: str, name: str, arguments: str, index: int = 0
) -> SimpleNamespace:
    call = SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    delta = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def usage_chunk(prompt: int = 10, completion: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion
        ),
    )


def plain_response(
    content: str, prompt: int = 10, completion: int = 5
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion
        ),
    )


class FakePubSub:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.channel = ""
        self.messages = messages

    async def subscribe(self, channel: str) -> None:
        self.channel = channel

    async def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        return self.messages.pop(0) if self.messages else None

    async def aclose(self) -> None:
        pass


class FakeRedis:
    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        self.pubsub_instance = FakePubSub(messages or [])

    def pubsub(self) -> FakePubSub:
        return self.pubsub_instance

    async def aclose(self) -> None:
        pass


def install_fake_redis(
    monkeypatch: pytest.MonkeyPatch, client: FakeRedis
) -> None:
    monkeypatch.setattr(
        demos_api,
        "redis",
        SimpleNamespace(
            asyncio=SimpleNamespace(
                Redis=SimpleNamespace(from_url=lambda url: client)
            )
        ),
    )


def backdate_thread(thread: DemoChatThread) -> None:
    """Age the liveness clock past the cutoff, as if the worker died."""
    DemoChatThread.objects.filter(id=thread.id).update(
        touched_at=timezone.now()
        - timedelta(seconds=demo_service.TURN_STALE_SECONDS + 1)
    )
    thread.refresh_from_db()


def test_defining_an_agent_registers_it_and_requires_a_docstring() -> None:
    """Subclassing is registration, and a docstring is the price of entry.

    The celery task can only reach an agent through the AGENTS registry,
    so an agent that fails to register is a thread that can never run.
    Registration happens in __init_subclass__, which is also where a
    missing docstring must fail — at import, not at first use.
    """
    assert AGENTS["demo"] is DemoAgent
    assert AGENTS["test_json_state"] is JsonStateAgent

    with pytest.raises(TypeError):
        type("Undocumented", (Agent,), {"name": "test_undocumented"})

    assert "test_undocumented" not in AGENTS


def test_tool_schemas_use_the_declared_snake_case_name_and_docstring() -> None:
    """The schema's name is the `name` ClassVar, never the class name.

    The litigant portal derived tool names from the class name, so its
    prompts said `query_document` while the schema said `QueryDocument`.
    The explicit snake_case ClassVar exists to make that mismatch
    impossible; this fails if get_schema ever falls back to __name__.
    """
    schema = CheckWeather.get_schema()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "check_weather"
    assert schema["function"]["description"].startswith(
        "Check the current weather"
    )
    properties = schema["function"]["parameters"]["properties"]
    assert "location" in properties

    with pytest.raises(TypeError):
        type("Undocumented", (Tool,), {"name": "test_undocumented_tool"})


def test_render_data_and_interrupted_never_reach_the_model_projection(
    user: User,
) -> None:
    """Frontend-only keys are stripped before a completion request.

    One store, two projections: the row keeps render payloads and UI
    markers, the API call gets a whitelist. If the whitelist ever loosens,
    every future request ships render HTML data to the provider and the
    provider rejects unknown keys — this pins the strict projection.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})
    add_message(
        thread,
        {
            "role": "assistant",
            "content": "checking",
            "interrupted": True,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "check_weather",
                        "arguments": '{"location": "Paris"}',
                    },
                }
            ],
        },
    )
    add_message(
        thread,
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "check_weather",
            "content": "72",
            "render_data": {"location": "Paris", "temp_f": 72},
        },
    )

    messages = demo_service._messages_for_llm(thread, system_prompt="sys")

    dumped = json.dumps(messages)
    assert "render_data" not in dumped
    assert "interrupted" not in dumped
    assert [m["role"] for m in messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]


def test_turn_persists_usage_and_cost_and_streams_offset_deltas(
    user: User, llm: FakeLLM, events: list[dict[str, Any]]
) -> None:
    """Real usage lands on the assistant row; deltas carry offsets.

    Both token sides come from the stream's usage chunk — the litigant
    portal only recorded completion tokens, which undercounts spend, and
    that bug is deliberately not ported. Offsets let a client that saw a
    snapshot mid-stream drop the deltas it already has.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})
    llm.responses = [
        [text_chunk("Hello"), text_chunk(" there"), usage_chunk(11, 7)]
    ]

    demo_service.demo_chat_turn_run(str(thread.id))

    row = thread.messages.get(kind="chat", data__role="assistant")
    assert row.data["content"] == "Hello there"
    assert (row.input_tokens, row.output_tokens) == (11, 7)
    assert row.cost == pytest.approx(0.0123)

    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.IDLE

    deltas = [e for e in events if e["type"] == "content_delta"]
    assert [d["offset"] for d in deltas] == [0, 5]
    assert [d["text"] for d in deltas] == ["Hello", " there"]
    assert any(e["type"] == "usage" for e in events)
    statuses = [e["status"] for e in events if e["type"] == "status"]
    assert statuses == ["running", "idle"]


def test_the_weather_tool_updates_state_and_refreshes_the_prompt(
    user: User,
    llm: FakeLLM,
    events: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The demo tool round-trip: state, render payload, prompt refresh.

    check_weather appends to recent_locations and asks for a prompt
    refresh, so the second model call's system prompt must already name
    the city. The tool's cards render server-side from its declared
    templates — no tool-specific frontend code exists to compensate.
    """
    monkeypatch.setattr(demo_agent_module, "CALL_CARD_DELAY_SECONDS", 0)
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "Weather in Paris?"})
    llm.responses = [
        [
            tool_chunk("c1", "check_weather", '{"location": "Paris"}'),
            usage_chunk(),
        ],
        [text_chunk("It is 72 in Paris."), usage_chunk()],
    ]

    demo_service.demo_chat_turn_run(str(thread.id))

    thread.refresh_from_db()
    assert thread.state == {"recent_locations": ["Paris"]}
    assert thread.status == DemoChatThread.Status.IDLE

    tool_row = thread.messages.get(data__role="tool")
    assert tool_row.data["content"] == "It is 72 degrees in Paris."
    assert tool_row.data["render_data"] == {
        "location": "Paris",
        "temp_f": 72,
    }

    snapshot = demo_chat_thread_snapshot(thread=thread)
    tool_payload = next(m for m in snapshot["messages"] if m["role"] == "tool")
    assert tool_payload["render_mode"] == "custom"
    assert "Paris" in tool_payload["render_html"]
    assert "Paris" in snapshot["state_html"]

    assert "Paris" in llm.calls[1]["messages"][0]["content"]
    assert any(e["type"] == "state" for e in events)


def test_tool_errors_become_tool_results_and_the_turn_continues(
    user: User, llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crashing tool feeds the model an error string, not the user a 500.

    The model is the one that can react to a failed tool — apologize,
    retry differently — so the exception is logged and folded into the
    tool result. If _execute_tool ever lets exceptions escape, the whole
    turn dies and the thread sticks in failed instead.
    """

    def boom(self: CheckWeather, *, thread_id: str) -> ToolOutput:
        raise RuntimeError("tool exploded")

    monkeypatch.setattr(CheckWeather, "__call__", boom)
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "Weather in Paris?"})
    llm.responses = [
        [
            tool_chunk("c1", "check_weather", '{"location": "Paris"}'),
            usage_chunk(),
        ],
        [text_chunk("Sorry, that failed."), usage_chunk()],
    ]

    demo_service.demo_chat_turn_run(str(thread.id))

    tool_row = thread.messages.get(data__role="tool")
    assert tool_row.data["content"].startswith("Error:")

    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.IDLE
    assert len(llm.calls) == 2


def test_cancel_stops_the_stream_and_keeps_the_partial_text(
    user: User, llm: FakeLLM
) -> None:
    """Cancellation is cooperative and loses nothing already streamed.

    The flag is checked at every flush, so the worker winds down within
    a chunk or two; the partial text persists with an interrupted marker
    and the thread returns to idle, ready for the next message.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})

    def stream() -> Any:
        yield text_chunk("Hel")
        cache.set(demo_chat_cancel_cache_key(str(thread.id)), True, timeout=60)
        yield text_chunk("lo")
        yield text_chunk(" world")

    llm.responses = [stream()]

    demo_service.demo_chat_turn_run(str(thread.id))

    row = thread.messages.get(kind="chat", data__role="assistant")
    assert row.data["content"] == "Hello"
    assert row.data["interrupted"] is True

    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.IDLE
    assert len(llm.calls) == 1


def test_cancel_between_tools_closes_out_unanswered_calls(
    user: User, llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every tool_call gets a tool result even when the turn is cancelled.

    A provider rejects an assistant message whose tool_calls have no
    matching tool responses, so abandoning the loop mid-tools would brick
    the thread's history. Cancelled calls get a synthetic result row that
    the UI skips rendering.
    """

    def cancel_and_answer(self: CheckWeather, *, thread_id: str) -> ToolOutput:
        cache.set(demo_chat_cancel_cache_key(thread_id), True, timeout=60)
        return ToolOutput(result="ok")

    monkeypatch.setattr(CheckWeather, "__call__", cancel_and_answer)
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "Paris and Oslo?"})
    llm.responses = [
        [
            tool_chunk("c1", "check_weather", '{"location": "Paris"}'),
            tool_chunk("c2", "check_weather", '{"location": "Oslo"}', 1),
            usage_chunk(),
        ]
    ]

    demo_service.demo_chat_turn_run(str(thread.id))

    messages = demo_service._messages_for_llm(thread, system_prompt="s")
    assistant = next(
        m for m in messages if m["role"] == "assistant" and "tool_calls" in m
    )
    result_ids = {m["tool_call_id"] for m in messages if m["role"] == "tool"}
    assert {c["id"] for c in assistant["tool_calls"]} == {"c1", "c2"}
    assert result_ids == {"c1", "c2"}

    cancelled = thread.messages.get(data__tool_call_id="c2")
    assert cancelled.data["content"] == "Cancelled by the user."

    snapshot = demo_chat_thread_snapshot(thread=thread)
    cancelled_payload = next(
        m for m in snapshot["messages"] if m.get("tool_call_id") == "c2"
    )
    assert cancelled_payload["render_mode"] == "skip"

    assistant_row = thread.messages.get(kind="chat", data__role="assistant")
    assert assistant_row.data["interrupted"] is True

    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.IDLE


def test_turn_failure_marks_the_thread_failed_without_leaking_the_exception(
    user: User, llm: FakeLLM, events: list[dict[str, Any]]
) -> None:
    """Unexpected errors log server-side; clients get only a status.

    The litigant portal ships str(exception) to the browser in its error
    frame. Here the exception text must never appear in any published
    event or snapshot payload — the UI renders a generic card off the
    failed status, and the details live in the logs.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})
    llm.error = RuntimeError("secret connection detail")

    demo_service.demo_chat_turn_run(str(thread.id))

    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.FAILED

    assert "secret connection detail" not in json.dumps(events)
    snapshot = demo_chat_thread_snapshot(thread=thread)
    assert "secret connection detail" not in json.dumps(snapshot)
    statuses = [e["status"] for e in events if e["type"] == "status"]
    assert statuses[-1] == "failed"


def test_compaction_triggers_at_the_threshold_and_cuts_the_projection(
    user: User, llm: FakeLLM
) -> None:
    """Past the threshold, the model sees the summary instead of history.

    The trigger reads real usage — the last assistant row's input_tokens —
    never an estimate. The summary rides in as a system-prompt suffix, so
    no message-role alternation rule can object, and the UI keeps showing
    the full history while the projection starts after the compaction row.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "first question"})
    add_message(
        thread,
        {"role": "assistant", "content": "old answer"},
        input_tokens=150_000,
        output_tokens=10,
    )
    add_message(thread, {"role": "user", "content": "second question"})
    llm.responses = [
        plain_response("summary text", 500, 50),
        [text_chunk("fresh answer"), usage_chunk()],
    ]

    demo_service.demo_chat_turn_run(str(thread.id))

    compaction = thread.messages.get(kind="compaction")
    assert compaction.data["content"] == "summary text"
    assert (compaction.input_tokens, compaction.output_tokens) == (500, 50)
    assert compaction.cost == pytest.approx(0.0123)

    compact_input = json.dumps(llm.calls[0]["messages"])
    assert "old answer" in compact_input
    assert "second question" not in compact_input
    assert llm.calls[0]["model"] == demo_service.COMPACTION_MODEL

    system = llm.calls[1]["messages"][0]["content"]
    assert "summary text" in system
    assert "<conversation_summary>" in system
    rest = json.dumps(llm.calls[1]["messages"][1:])
    assert "old answer" not in rest
    assert "second question" in rest

    snapshot = json.dumps(demo_chat_thread_snapshot(thread=thread)["messages"])
    assert "old answer" in snapshot
    assert "summary text" in snapshot


def test_context_tokens_reset_after_a_compaction(user: User) -> None:
    """The token bar reads the newest call since the last compaction.

    Without the cutoff, the pre-compaction assistant row would keep the
    reading above the threshold and every turn would compact again. The
    bar dropping to zero right after a compaction is the same rule seen
    from the UI.
    """
    thread = make_thread(user)
    add_message(
        thread,
        {"role": "assistant", "content": "big"},
        input_tokens=150_000,
    )
    assert demo_chat_thread_context_tokens(thread=thread) == 150_000

    add_message(
        thread,
        {"role": "meta", "content": "summary"},
        kind=DemoChatMessage.Kind.COMPACTION,
    )
    assert demo_chat_thread_context_tokens(thread=thread) == 0

    add_message(
        thread,
        {"role": "assistant", "content": "small"},
        input_tokens=1234,
    )
    assert demo_chat_thread_context_tokens(thread=thread) == 1234


def test_title_is_generated_once_and_never_overwrites_a_rename(
    user: User, llm: FakeLLM, events: list[dict[str, Any]]
) -> None:
    """Titles come from the first user message; a manual rename outranks.

    The generator books its spend on a meta row so thread totals stay
    honest, and it no-ops whenever a title already exists — which is what
    protects a rename that lands while the task is still queued.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "Weather in Paris?"})
    llm.responses = [plain_response("Paris Weather Check", 3, 2)]

    demo_service.demo_chat_thread_title_generate(str(thread.id))

    thread.refresh_from_db()
    assert thread.title == "Paris Weather Check"
    meta = thread.messages.get(kind="meta")
    assert (meta.input_tokens, meta.output_tokens) == (3, 2)
    assert meta.cost == pytest.approx(0.0123)
    assert any(e["type"] == "title" for e in events)

    demo_service.demo_chat_thread_rename(
        user=user, thread_id=str(thread.id), title="Mine"
    )
    demo_service.demo_chat_thread_title_generate(str(thread.id))

    thread.refresh_from_db()
    assert thread.title == "Mine"
    assert len(llm.calls) == 1


def test_title_generation_falls_back_to_truncation_on_failure(
    user: User, llm: FakeLLM
) -> None:
    """A dead model API still leaves the history readable.

    The fallback is the first message truncated — never an empty row in
    the history panel, and never an exception out of the task.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "x" * 200})
    llm.error = RuntimeError("model down")

    demo_service.demo_chat_thread_title_generate(str(thread.id))

    thread.refresh_from_db()
    assert thread.title == "x" * demo_service.TITLE_FALLBACK_MAX_CHARS


def test_send_rejects_unknown_agents_and_busy_threads(user: User) -> None:
    """Send validates the registry key and refuses to double-run a turn.

    The agent name is data crossing the API, so it is validated against
    AGENTS at the boundary; and one thread runs one turn at a time, so a
    send while pending or running is a 400, not a queued surprise.
    """
    with pytest.raises(ApplicationError):
        demo_service.demo_chat_message_send(
            user=user, message="hi", agent="nope"
        )
    with pytest.raises(ApplicationError):
        demo_service.demo_chat_message_send(
            user=user, message="   ", agent="demo"
        )

    thread = demo_service.demo_chat_message_send(
        user=user, message="hi", agent="demo"
    )
    assert thread.status == DemoChatThread.Status.PENDING
    assert thread.messages.get(data__role="user").data["content"] == "hi"

    with pytest.raises(ApplicationError):
        demo_service.demo_chat_message_send(
            user=user, message="again", thread_id=str(thread.id)
        )


def test_threads_are_scoped_to_their_owner(
    user: User, other_user: User
) -> None:
    """Every read and mutation filters on the owning user.

    The id is a UUID but not a secret — it travels through URLs and
    events — so possession of an id must grant nothing.
    """
    thread = demo_service.demo_chat_message_send(
        user=user, message="hi", agent="demo"
    )

    assert demo_chat_thread_list(user=other_user) == []
    assert (
        demo_chat_thread_get(user=other_user, thread_id=str(thread.id)) is None
    )
    assert demo_chat_thread_get(user=user, thread_id=str(thread.id)) == thread

    with pytest.raises(ApplicationError):
        demo_service.demo_chat_thread_rename(
            user=other_user, thread_id=str(thread.id), title="x"
        )
    with pytest.raises(ApplicationError):
        demo_service.demo_chat_turn_cancel(
            user=other_user, thread_id=str(thread.id)
        )
    with pytest.raises(ApplicationError):
        demo_service.demo_chat_thread_delete(
            user=other_user, thread_id=str(thread.id)
        )
    assert DemoChatThread.objects.filter(id=thread.id).exists()


def test_delete_publishes_a_deleted_event(
    user: User, events: list[dict[str, Any]]
) -> None:
    """Deleting a thread tells live viewers to let go of it.

    Another tab streaming the thread would otherwise hold its SSE
    connection open forever, pinging a channel nothing will publish to
    again. The deleted event is what makes such a tab disconnect, and it
    is published after the row is gone so a viewer that reacts by
    refetching sees the thread absent rather than briefly resurrected.
    """
    thread = demo_service.demo_chat_message_send(
        user=user, message="hi", agent="demo"
    )
    events.clear()

    demo_service.demo_chat_thread_delete(user=user, thread_id=str(thread.id))

    assert not DemoChatThread.objects.filter(id=thread.id).exists()
    assert events == [{"type": "deleted"}]


def test_snapshot_renders_state_with_the_agent_template_and_falls_back_to_json(
    user: User,
) -> None:
    """State rendering is the tool-card directive applied to the panel.

    An agent that declares state_template gets server-rendered HTML; one
    that does not gets state_html None, which the page renders as a JSON
    dump. The fallback existing is what lets a new agent ship with no
    frontend work at all.
    """
    thread = make_thread(user)
    thread.state = {"recent_locations": ["Paris"]}
    thread.save(update_fields=["state"])

    snapshot = demo_chat_thread_snapshot(thread=thread)
    assert "Paris" in snapshot["state_html"]

    bare = DemoChatThread(user=user, agent="test_json_state", state={"a": 1})
    bare.full_clean()
    bare.save()

    fallback = demo_chat_thread_snapshot(thread=bare)
    assert fallback["state_html"] is None
    assert fallback["state"] == {"a": 1}


@pytest.mark.django_db(transaction=True)
def test_sse_sends_a_snapshot_first_and_then_relays(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay subscribes, snapshots, then forwards — in that order.

    Subscribing before reading the snapshot is what closes the gap a
    just-published event could fall into; a client therefore only ever
    needs offset deduplication, never a refetch. Quiet stretches yield
    SSE comments so proxies keep the connection open.

    transaction=True because the generator reads the database through
    sync_to_async on another connection, the same reason the MCP tests
    need it.
    """
    fake_redis = FakeRedis(
        [
            {
                "type": "message",
                "data": json.dumps(
                    {"type": "status", "status": "running"}
                ).encode(),
            }
        ]
    )
    install_fake_redis(monkeypatch, fake_redis)

    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})

    async def main() -> tuple[str, str, str]:
        stream = demos_api._event_stream(str(thread.id))
        first = await anext(stream)
        second = await anext(stream)
        third = await anext(stream)
        await stream.aclose()
        return first, second, third

    first, second, third = run_async(main)

    snapshot = json.loads(first.removeprefix("data: "))
    assert snapshot["type"] == "snapshot"
    assert snapshot["thread"]["id"] == str(thread.id)
    assert snapshot["messages"][0]["content"] == "hi"
    assert (
        fake_redis.pubsub_instance.channel == f"demo_chat_events:{thread.id}"
    )

    relayed = json.loads(second.removeprefix("data: "))
    assert relayed == {"type": "status", "status": "running"}

    assert third == ": ping\n\n"


@pytest.mark.django_db(transaction=True)
def test_sse_snapshot_closes_its_database_connections(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay must not pin a postgres connection per open stream.

    The snapshot is the stream's only database work, but the connection
    it opens lives on the sync executor thread and Django only closes
    connections when the request finishes — which for an SSE response is
    when the stream ends, potentially hours later. Left open, every
    viewing chat tab holds a postgres connection for its whole lifetime,
    which exhausts max_connections long before request volume would. So
    _snapshot closes what it opened before the relay loop starts; this
    checks the executor thread holds no open connection once the
    snapshot event has been yielded.
    """
    install_fake_redis(monkeypatch, FakeRedis())
    thread = make_thread(user)

    async def main() -> list[str]:
        stream = demos_api._event_stream(str(thread.id))
        await anext(stream)
        open_aliases = await sync_to_async(
            lambda: [
                alias
                for alias in connections
                if connections[alias].connection is not None
            ]
        )()
        await stream.aclose()
        return open_aliases

    assert run_async(main) == []


def test_publish_swallows_redis_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redis blip must never strand a send or fail a healthy turn.

    demo_chat_message_send registers the message publish and the turn-task
    queueing as consecutive on_commit callbacks, and Django skips the
    remaining callbacks when an earlier one raises — so a publish that
    could raise would commit a PENDING thread whose turn task was never
    queued. Mid-turn the same trade holds: the row is already written,
    and a viewer who missed an event rebuilds from the snapshot on
    reconnect. Events are advisory, the database is authoritative, so
    publish failures log and are swallowed.
    """

    class ExplodingRedis:
        def publish(self, channel: str, payload: str) -> None:
            raise ConnectionError("redis down")

    monkeypatch.setattr(
        demo_service, "_redis_client", lambda: ExplodingRedis()
    )

    demo_service._publish("thread-id", {"type": "status", "status": "idle"})


def test_send_reclaims_a_thread_whose_turn_died(user: User) -> None:
    """A worker killed mid-turn must not brick its thread.

    Only the worker that set PENDING/RUNNING ever clears it, so a
    SIGKILL (a deploy, an OOM) would otherwise leave the status busy
    forever and every send would 400. The claim treats a busy status as
    real only while the turn keeps freshening updated_at; past
    TURN_STALE_SECONDS of silence the send takes the thread over. The
    claim is a single conditional UPDATE rather than check-then-save so
    two concurrent sends cannot both pass it — the second one matches
    zero rows and raises.
    """
    thread = demo_service.demo_chat_message_send(
        user=user, message="hi", agent="demo"
    )
    with pytest.raises(ApplicationError):
        demo_service.demo_chat_message_send(
            user=user, message="again", thread_id=str(thread.id)
        )

    DemoChatThread.objects.filter(id=thread.id).update(
        status=DemoChatThread.Status.RUNNING
    )
    backdate_thread(thread)

    reclaimed = demo_service.demo_chat_message_send(
        user=user, message="again", thread_id=str(thread.id)
    )

    assert reclaimed.status == DemoChatThread.Status.PENDING
    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.PENDING
    assert thread.updated_at > timezone.now() - timedelta(minutes=1)


def test_cancel_returns_a_dead_turn_to_idle(
    user: User, events: list[dict[str, Any]]
) -> None:
    """Stop on a dead turn unblocks the thread instead of doing nothing.

    The composer's only affordance while a thread is busy is Stop. On a
    live turn the cache flag is enough — the worker sees it within a
    flush. When the worker is gone, nothing will ever read the flag or
    clear the status, so cancel finishes a stale turn itself, and the
    published status event is what flips an open page back to a usable
    composer. A fresh busy status is left alone: the worker owns it.
    """
    thread = make_thread(user)
    DemoChatThread.objects.filter(id=thread.id).update(
        status=DemoChatThread.Status.RUNNING
    )
    thread.refresh_from_db()

    demo_service.demo_chat_turn_cancel(user=user, thread_id=str(thread.id))
    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.RUNNING

    backdate_thread(thread)
    demo_service.demo_chat_turn_cancel(user=user, thread_id=str(thread.id))

    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.IDLE
    statuses = [e["status"] for e in events if e["type"] == "status"]
    assert statuses[-1] == "idle"


def test_streaming_freshens_the_liveness_clock(
    user: User, llm: FakeLLM
) -> None:
    """A live turn keeps touched_at moving so it can never be reclaimed.

    The stale-turn claim reads touched_at as a liveness signal, and
    model calls can legitimately outlast any fixed turn timeout —
    max_steps slow completions back to back. So the worker proves
    liveness by touching the clock at every flush and after every tool;
    without the touch, a long healthy turn would go stale mid-stream,
    a send would reclaim the thread, and two workers would interleave
    rows on it. This drives one stream over a backdated thread and
    checks the flush moved the clock.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})
    backdate_thread(thread)
    stale_touched_at = thread.touched_at
    llm.responses = [[text_chunk("Hello"), usage_chunk()]]

    demo_service._stream_completion(thread, DemoAgent(), "sys", thread.turn)

    thread.refresh_from_db()
    assert thread.touched_at > stale_touched_at
    assert thread.touched_at > timezone.now() - timedelta(minutes=1)


def test_unanswered_tool_calls_are_closed_out_in_the_projection(
    user: User,
) -> None:
    """History a dead turn left mid-tools must still project API-valid.

    The assistant row persists its tool_calls before any tool row is
    written, so a worker death between the two leaves calls with no
    responses — and a provider rejects that history on every later
    request, which would brick the thread permanently. The projection
    synthesizes an interrupted result for each unanswered call, placed
    where the real row would have sat, so the next turn and a
    compaction both get a valid message list. Nothing is written back:
    the repair is read-side and idempotent.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "Paris and Oslo?"})
    add_message(
        thread,
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "check_weather",
                        "arguments": '{"location": "Paris"}',
                    },
                },
                {
                    "id": "c2",
                    "type": "function",
                    "function": {
                        "name": "check_weather",
                        "arguments": '{"location": "Oslo"}',
                    },
                },
            ],
        },
    )
    add_message(
        thread,
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "check_weather",
            "content": "72",
        },
    )
    add_message(thread, {"role": "user", "content": "still there?"})

    messages = demo_service._messages_for_llm(thread, system_prompt="s")

    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "tool", "tool", "user"]
    synthetic = messages[4]
    assert synthetic["tool_call_id"] == "c2"
    assert synthetic["name"] == "check_weather"
    assert "Interrupted" in synthetic["content"]


def test_content_delta_offsets_count_utf16_units_like_the_browser(
    user: User, llm: FakeLLM, events: list[dict[str, Any]]
) -> None:
    """An offset is an index into a JavaScript string, not a Python one.

    The client appends a delta only when its offset equals the text it
    already holds (`content.length` in chat.html), and JavaScript counts
    UTF-16 code units while Python counts code points. An emoji is one
    code point and two code units, so a Python `len()` offset would run
    one short for the rest of the message: every later delta would fail
    the equality check and be dropped, freezing the bubble mid-sentence
    until the end-of-turn message event repaired it. A cheerful weather
    agent emits emoji routinely, so this is the common path, not an edge.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})
    llm.responses = [
        [text_chunk("Sunny \U0001f600"), text_chunk(" today"), usage_chunk()]
    ]

    demo_service.demo_chat_turn_run(str(thread.id))

    deltas = [e for e in events if e["type"] == "content_delta"]
    assert [d["offset"] for d in deltas] == [0, 8]
    assert len("Sunny \U0001f600") == 7


def test_only_one_worker_can_claim_a_queued_turn(
    user: User, llm: FakeLLM
) -> None:
    """The turn runs once however many times its task is delivered.

    Celery redelivers on worker loss, and the stale-turn reclaim can
    queue a second task while the first is still in the broker. Both
    deliveries hit demo_chat_turn_run, so the right to run is a guarded
    claim on the pending status rather than the mere existence of a
    thread — otherwise two turns stream onto one conversation and
    interleave their rows.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})
    llm.responses = [[text_chunk("Hello"), usage_chunk()]]

    demo_service.demo_chat_turn_run(str(thread.id))
    demo_service.demo_chat_turn_run(str(thread.id))

    assert len(llm.calls) == 1
    assert thread.messages.filter(data__role="assistant").count() == 1


def test_a_reclaimed_turn_stops_instead_of_finishing_the_new_one(
    user: User, llm: FakeLLM, events: list[dict[str, Any]]
) -> None:
    """A worker that lost the thread mid-stream must not write its status.

    A worker blocked past TURN_STALE_SECONDS inside one model call gets
    its thread reclaimed and handed to a second worker. The first is not
    dead — it wakes up and carries on — so without an ownership check it
    would finish a turn it no longer owns, flipping the live turn's
    status to idle and inviting a third turn to start on top of it. Every
    claim rotates the thread's turn token, so the touch at each flush is
    also the ownership probe: once it matches nothing, this worker's
    remaining writes are somebody else's business.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})

    def hijacked() -> Any:
        yield text_chunk("Half ")
        DemoChatThread.objects.filter(id=thread.id).update(
            turn=uuid4(), status=DemoChatThread.Status.RUNNING
        )
        yield text_chunk("written")
        yield usage_chunk()

    llm.responses = [hijacked()]

    demo_service.demo_chat_turn_run(str(thread.id))

    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.RUNNING
    assert "idle" not in [e["status"] for e in events if e["type"] == "status"]


def test_a_cancelled_turn_does_not_run_when_its_task_arrives_late(
    user: User, llm: FakeLLM
) -> None:
    """Cancelling a queued turn survives the cancel flag's own expiry.

    The flag is a cache entry with a ten-minute TTL, and a backlogged
    broker can deliver the task after it expires. Cancel finishes the
    stale turn to idle, so the claim is what turns the late delivery
    away: if the worker only consulted the flag, the user would watch a
    turn they explicitly stopped start streaming and spending minutes
    later.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})
    backdate_thread(thread)

    demo_service.demo_chat_turn_cancel(user=user, thread_id=str(thread.id))

    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.IDLE

    cache.delete(demo_chat_cancel_cache_key(str(thread.id)))
    llm.responses = [[text_chunk("late"), usage_chunk()]]

    demo_service.demo_chat_turn_run(str(thread.id))

    assert llm.calls == []
    assert not thread.messages.filter(data__role="assistant").exists()


def test_tool_results_ship_their_text_so_a_failure_is_visible(
    user: User, llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The result card has nothing to show unless the row's text is sent.

    A tool that raises produces an error string and no render_data, and
    a tool with no result template has render_data the default card
    prints as JSON. Serializing only render_data left both rendering as
    an empty `{}` card: the user saw a blank box where the failure
    should be, with the text readable only in the database and in the
    model's own context.
    """

    def boom(self: CheckWeather, *, thread_id: str) -> ToolOutput:
        raise RuntimeError("tool exploded")

    monkeypatch.setattr(CheckWeather, "__call__", boom)
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "Weather in Paris?"})
    llm.responses = [
        [
            tool_chunk("c1", "check_weather", '{"location": "Paris"}'),
            usage_chunk(),
        ],
        [text_chunk("Sorry, that failed."), usage_chunk()],
    ]

    demo_service.demo_chat_turn_run(str(thread.id))

    snapshot = demo_chat_thread_snapshot(thread=thread)
    result = next(m for m in snapshot["messages"] if m["role"] == "tool")
    assert result["content"].startswith("Error:")
    assert result["render_data"] is None


def test_editing_a_thread_does_not_hide_its_dead_turn(
    user: User, events: list[dict[str, Any]]
) -> None:
    """Liveness is the worker's own clock, not the row's mtime.

    A turn is presumed dead once nothing has touched it for
    TURN_STALE_SECONDS, and that is the only way out of a thread whose
    worker was killed mid-turn: cancel force-finishes it and the next
    send reclaims it. While the clock was updated_at, any ordinary write
    to the row re-armed it — renaming a bricked thread bought its dead
    turn another ten minutes, with Stop setting a flag nobody would read
    and every send returning "a response is already in progress". So the
    worker touches a column only the worker writes.
    """
    thread = make_thread(user, status=DemoChatThread.Status.RUNNING)
    backdate_thread(thread)

    demo_service.demo_chat_thread_rename(
        user=user, thread_id=str(thread.id), title="Renamed mid-turn"
    )

    thread.refresh_from_db()
    assert thread.updated_at > demo_service._stale_cutoff()
    assert thread.touched_at < demo_service._stale_cutoff()

    demo_service.demo_chat_turn_cancel(user=user, thread_id=str(thread.id))

    thread.refresh_from_db()
    assert thread.status == DemoChatThread.Status.IDLE
    assert [e["status"] for e in events if e["type"] == "status"] == ["idle"]


def test_each_flush_publishes_the_full_text_as_a_checkpoint(
    user: User, llm: FakeLLM, events: list[dict[str, Any]]
) -> None:
    """Deltas alone cannot repair a client that joined mid-stream.

    A late subscriber is sent a database snapshot, which is only as
    fresh as the last flush, while the deltas covering the gap between
    that flush and its subscribe were published before it was listening
    and redis pub/sub keeps no backlog. Its content is then permanently
    short, so every later delta fails the offset check and is dropped —
    the bubble freezes until the turn ends. The flush therefore
    publishes the whole text it just committed, which is the same
    checkpoint the snapshot reads, so a gap closes within one flush.
    The client only ever takes a checkpoint that is longer than what it
    holds, so a caught-up viewer never rewinds.
    """
    thread = make_thread(user)
    add_message(thread, {"role": "user", "content": "hi"})
    llm.responses = [
        [text_chunk("Hello"), text_chunk(" there"), usage_chunk()]
    ]

    demo_service.demo_chat_turn_run(str(thread.id))

    row = thread.messages.get(kind="chat", data__role="assistant")
    checkpoints = [e for e in events if e["type"] == "content_set"]
    assert [c["text"] for c in checkpoints] == ["Hello", "Hello there"]
    assert {c["message_id"] for c in checkpoints} == {str(row.id)}
