import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth.models import Group
from django.db import connections
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import TextContent, ToolAnnotations
from pytest_django.fixtures import SettingsWrapper

from clx.app.exceptions import ApplicationError
from clx.app.models import User
from clx.app.services.health import CHECKS
from clx.mcp.server import mcp
from clx.mcp.tools.base import TOOLS, MCPTool, ToolInputs
from clx.mcp.utils import current_user


def run_async(main: Callable[[], Awaitable[Any]]) -> Any:
    async def run() -> Any:
        try:
            return await main()
        finally:
            await sync_to_async(connections.close_all)()

    return asyncio.run(run())


def run_client(coro: Callable[[Client[Any]], Awaitable[Any]]) -> Any:
    async def main() -> Any:
        async with Client(mcp) as client:
            return await coro(client)

    return run_async(main)


def list_tool_names() -> list[str]:
    async def names(client: Client[Any]) -> list[str]:
        return [tool.name for tool in await client.list_tools()]

    names_: list[str] = run_client(names)
    return names_


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    async def call(client: Client[Any]) -> str:
        result = await client.call_tool(name, arguments or {})
        content = result.content[0]
        assert isinstance(content, TextContent)
        return content.text

    text: str = run_client(call)
    return text


def with_token_subject(
    monkeypatch: pytest.MonkeyPatch,
    subject: str | None,
    scopes: tuple[str, ...] = ("demo:read", "demo:write"),
) -> None:
    monkeypatch.setattr(
        "clx.mcp.utils.get_access_token",
        lambda: SimpleNamespace(subject=subject, scopes=list(scopes)),
    )


def as_user(monkeypatch: pytest.MonkeyPatch, user: User) -> None:
    with_token_subject(monkeypatch, str(user.pk))


@pytest.fixture
def extra_tools() -> Iterator[None]:
    class EchoInputs(ToolInputs):
        message: str
        times: int = 1

    class EchoTool(MCPTool):
        """Echo a message."""

        name = "echo"
        inputs = EchoInputs

        async def __call__(self, arguments: dict[str, Any]) -> dict[str, str]:
            times = arguments.get("times", 1)
            return {"echo": arguments["message"] * times}

    class BoomTool(MCPTool):
        """Always fail."""

        name = "boom"

        async def __call__(self, arguments: dict[str, Any]) -> None:
            raise ApplicationError("nope")

    yield

    TOOLS.pop("echo", None)
    TOOLS.pop("boom", None)


@pytest.fixture
def admin(monkeypatch: pytest.MonkeyPatch) -> User:
    user = User.objects.create_user("admin@example.com")
    user.groups.add(Group.objects.get(name="Admin"))
    as_user(monkeypatch, user)
    return user


def test_tools_are_registered_by_importing_the_server() -> None:
    assert "health" in TOOLS
    assert "admin_status" in TOOLS


def test_ungated_tool_is_listed_without_a_user() -> None:
    assert "health" in list_tool_names()


def test_gated_tool_is_hidden_without_a_user() -> None:
    assert "admin_status" not in list_tool_names()


def test_gated_tool_is_denied_without_a_user() -> None:
    with pytest.raises(ToolError, match="Permission denied"):
        call_tool("admin_status")


@pytest.mark.django_db(transaction=True)
def test_gated_tool_is_listed_with_permission(admin: User) -> None:
    assert "admin_status" in list_tool_names()


@pytest.mark.django_db(transaction=True)
def test_gated_tool_is_callable_with_permission(admin: User) -> None:
    result = json.loads(call_tool("admin_status", {"query": "hi"}))

    assert result["query"] == "hi"


@pytest.mark.django_db(transaction=True)
def test_gated_tool_is_hidden_without_the_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_user(monkeypatch, User.objects.create_user("plain@example.com"))

    assert "admin_status" not in list_tool_names()


@pytest.mark.django_db(transaction=True)
def test_gated_tool_is_denied_without_the_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_user(monkeypatch, User.objects.create_user("plain@example.com"))

    with pytest.raises(ToolError, match="Permission denied"):
        call_tool("admin_status")


def test_unknown_arguments_are_rejected() -> None:
    with pytest.raises(ToolError, match="Additional properties"):
        call_tool("health", {"bogus": 1})


@pytest.mark.django_db(transaction=True)
def test_health_checks_only_the_named_services() -> None:
    assert json.loads(call_tool("health", {"services": ["postgres"]})) == {
        "postgres": True
    }


@pytest.mark.django_db(transaction=True)
def test_health_checks_everything_by_default() -> None:
    assert set(json.loads(call_tool("health"))) == set(CHECKS)


def test_health_rejects_unknown_service_names() -> None:
    with pytest.raises(ToolError, match="is not one of"):
        call_tool("health", {"services": ["bogus"]})


@pytest.mark.django_db(transaction=True)
def test_admin_status_returns_the_calling_user(admin: User) -> None:
    result = json.loads(call_tool("admin_status", {"query": "hi"}))

    assert result["user"] == {
        "id": str(admin.pk),
        "email": admin.email,
        "is_staff": False,
    }


@pytest.mark.django_db(transaction=True)
def test_admin_status_requires_a_query(admin: User) -> None:
    with pytest.raises(ToolError, match="query"):
        call_tool("admin_status", {})


@pytest.mark.django_db(transaction=True)
def test_whoami_reports_the_user_and_the_tokens_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User.objects.create_user("token@example.com")
    as_user(monkeypatch, user)

    result = json.loads(call_tool("auth_whoami"))

    assert result["user"] == user.email
    assert result["scopes"] == ["demo:read", "demo:write"]


@pytest.mark.django_db(transaction=True)
def test_a_scoped_tool_requires_its_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """required_scopes is the tool-level scopes=, in the API's vocabulary.

    A token granted demo:read alone reads and does not write, exactly as it
    would over HTTP -- there is no MCP-only scope for a client to request,
    and no tool a scope check silently skips.
    """
    user = User.objects.create_user("token@example.com")
    with_token_subject(monkeypatch, str(user.pk), scopes=("demo:read",))

    allowed = json.loads(call_tool("auth_scoped_read"))
    assert allowed["user"] == user.email

    with pytest.raises(ToolError, match="missing scopes: demo:write"):
        call_tool("auth_scoped_write")


@pytest.mark.django_db(transaction=True)
def test_an_always_listed_tool_is_listed_but_still_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the hide/enforce split, on purpose.

    admin_status demonstrates the default -- a gated tool hidden from
    callers who cannot use it. auth_admin_gated opts out of the hiding with
    always_listed, so every caller sees it and the call check alone rejects.
    Both shapes stay exercised, and neither is ever the only guard.
    """
    as_user(monkeypatch, User.objects.create_user("plain@example.com"))

    assert "auth_admin_gated" in list_tool_names()
    with pytest.raises(ToolError, match="Permission denied"):
        call_tool("auth_admin_gated")


@pytest.mark.django_db(transaction=True)
def test_the_always_listed_tool_answers_a_permitted_caller(
    admin: User,
) -> None:
    result = json.loads(call_tool("auth_admin_gated"))

    assert result["user"] == admin.email


@pytest.mark.django_db(transaction=True)
def test_a_tools_burst_rate_binds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool can carry its own burst budget, like an endpoint's rate=."""
    as_user(monkeypatch, User.objects.create_user("token@example.com"))

    for _ in range(5):
        call_tool("auth_burst")

    with pytest.raises(ToolError, match="Rate limit exceeded"):
        call_tool("auth_burst")


@pytest.mark.django_db(transaction=True)
def test_tool_calls_are_charged_to_the_scope_buckets(
    monkeypatch: pytest.MonkeyPatch,
    settings: SettingsWrapper,
) -> None:
    """MCP traffic spends the same per-scope budgets as HTTP token traffic.

    The middleware charges every authenticated call through
    rate_limit_consume, keyed on user and scope -- so draining a scope here
    drains it for the user's HTTP tokens too, and the aggregate ceiling
    stays aggregate. The companion test on the HTTP side
    (test_the_scope_budget_is_shared_with_mcp_tool_calls) proves the buckets
    are literally the same ones.
    """
    settings.API_RATE_LIMIT_PER_SCOPE = {"demo:read": 1}
    as_user(monkeypatch, User.objects.create_user("token@example.com"))

    call_tool("auth_scoped_read")

    with pytest.raises(ToolError, match="Rate limit exceeded"):
        call_tool("auth_scoped_read")


def test_the_advertised_resource_metadata_names_the_scopes() -> None:
    """A client learns which scopes to request by walking RFC 9728.

    The 401 a bare call gets names a metadata URL at the *root* of the
    site, which is why main.py mounts the auth provider's routes on the
    parent Starlette (with trailing-slash twins -- the advertised URL ends
    in one, and the catch-all Django mount would otherwise swallow it as a
    404). This walks the chain a real client walks: the 401, the URL it
    advertises, and the scopes_supported found there, which must be the
    API's own vocabulary because that is what the consent screen grants
    and the tools check.
    """
    import httpx

    from clx.app.permissions import API_SCOPES
    from clx.main import application

    async def walk() -> None:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:8000"
        ) as web:
            unauth = await web.post("/mcp/", json={})
            assert unauth.status_code == 401
            header = unauth.headers["www-authenticate"]
            url = header.split('resource_metadata="')[1].split('"')[0]

            metadata = await web.get(url)
            assert metadata.status_code == 200
            assert metadata.json()["scopes_supported"] == sorted(API_SCOPES)

    run_async(walk)


def test_input_schema_is_derived_from_pydantic(extra_tools: None) -> None:
    schema = TOOLS["echo"].input_schema

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["message"]
    assert schema["properties"]["times"]["type"] == "integer"


def test_declared_inputs_are_validated(extra_tools: None) -> None:
    with pytest.raises(ToolError, match="times"):
        call_tool("echo", {"message": "hi", "times": "lots"})


def test_declared_inputs_are_passed_through(extra_tools: None) -> None:
    assert json.loads(call_tool("echo", {"message": "hi", "times": 2})) == {
        "echo": "hihi"
    }


def test_application_error_becomes_a_tool_error(extra_tools: None) -> None:
    with pytest.raises(ToolError, match="nope"):
        call_tool("boom")


def test_a_tool_may_not_assume_a_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gated tool only runs after the middleware has resolved a user, but
    that guarantee lives two modules away and mypy cannot see it.

    AdminStatusTool is the file people copy for their first tool. Copy it
    without required_perms and current_user() returns None, so the example
    handles it rather than teaching `user.pk` on a maybe-None.
    """
    monkeypatch.setattr("clx.mcp.utils.get_access_token", lambda: None)

    with pytest.raises(ApplicationError, match="No authenticated user"):
        run_async(lambda: TOOLS["admin_status"]({"query": "hi"}))


def test_current_user_is_none_without_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("clx.mcp.utils.get_access_token", lambda: None)

    assert run_async(current_user) is None


@pytest.mark.django_db(transaction=True)
def test_current_user_resolves_the_token_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User.objects.create_user("token@example.com")
    with_token_subject(monkeypatch, str(user.pk))

    assert run_async(current_user).pk == user.pk


@pytest.mark.django_db(transaction=True)
def test_current_user_ignores_inactive_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User.objects.create_user("gone@example.com", is_active=False)
    with_token_subject(monkeypatch, str(user.pk))

    assert run_async(current_user) is None


@pytest.mark.django_db(transaction=True)
def test_the_verifier_rejects_a_token_without_an_application() -> None:
    """DOT allows application to be null; fastmcp's AccessToken does not.

    The consent flow always attaches an application, but a token row
    created by hand need not carry one, and dereferencing client_id off
    None raised before the token could be judged -- a 500 on every request
    presenting it. The verifier treats such a token as invalid instead,
    turning nothing legitimate away.
    """
    from datetime import timedelta

    from django.utils import timezone
    from oauth2_provider.models import get_access_token_model

    from clx.mcp.auth import DjangoTokenVerifier

    user = User.objects.create_user("appless@example.com")
    get_access_token_model().objects.create(
        user=user,
        token="appless",
        expires=timezone.now() + timedelta(hours=1),
        scope="demo:read",
    )

    verdict = run_async(lambda: DjangoTokenVerifier().verify_token("appless"))

    assert verdict is None


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_every_tool_declares_all_annotations(name: str) -> None:
    annotations = TOOLS[name].annotations

    assert annotations is not None, f"{name} declares no annotations"

    missing = [
        field
        for field in ToolAnnotations.model_fields
        if getattr(annotations, field) is None
    ]

    assert not missing, f"{name} is missing annotations: {missing}"


def test_a_tool_must_have_a_docstring() -> None:
    with pytest.raises(TypeError, match="docstring"):

        class Undocumented(MCPTool):
            name = "undocumented"


def test_the_mcp_sdk_is_not_shadowed_by_this_package() -> None:
    """`clx/mcp/` shadows the installed `mcp` SDK whenever `clx/`
    lands on sys.path.

    It normally does not, because production runs
    `uvicorn clx.main:application` from the repo root. But pytest-django
    looks for `manage.py` and prepends its directory, and ours lives at
    `clx/manage.py` -- hence `django_find_project = false` in the pytest
    config. Without it, `from fastmcp import Client` dies with
    "FastMCP client support is not installed", which reads like a missing
    dependency rather than a name collision.
    """
    import mcp.client

    assert "site-packages" in mcp.client.__file__


def test_main_configures_django_before_importing_the_mcp_server() -> None:
    """`create_application()` is a function so that `get_asgi_application()`
    runs before `clx.mcp.server` is imported.

    Everything under `clx/mcp/` is free to import models, DOT and the
    tool modules at module level because of that ordering. Import the server
    above that call instead and the whole layer raises AppRegistryNotReady,
    which no in-process test can catch once Django is already configured --
    so this one imports it in a fresh interpreter.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "DJANGO_SETTINGS_MODULE"
    }
    result = subprocess.run(
        [sys.executable, "-c", "import clx.main"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
