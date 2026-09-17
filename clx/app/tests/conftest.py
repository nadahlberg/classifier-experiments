import secrets
from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.cache import caches
from django.core.files.storage import InMemoryStorage, Storage
from django.utils import timezone
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
)
from pytest_django.fixtures import SettingsWrapper

from clx.app.models import DemoUpload, User
from clx.app.search import search_client
from clx.app.services.api_token import MintedToken, api_token_create
from clx.app.services.user import user_create


@pytest.fixture(autouse=True)
def local_cache(settings: SettingsWrapper) -> None:
    """Give every test an empty in-memory cache.

    Two reasons, and either one on its own would be enough. CI runs no
    redis, and the site name reaches every rendered page through a cached
    selector, so the default backend would turn most of this suite into a
    connection error. And a cache that outlives the test outlives the
    transaction the test's rows were rolled back with, so a value cached
    from one test would be served to the next one — the config selector
    would hand out a site name whose row no longer exists.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    caches["default"].clear()


@pytest.fixture
def search_index(settings: SettingsWrapper) -> Iterator[str]:
    """Point index names at a test prefix, dropping its indices afterwards.

    Dev and the tests share one elasticsearch — the compose service
    locally, the service container in CI — and index names carry no
    equivalent of pytest-django's test_ database, so without this prefix a
    test's alias swap would replace the dev index out from under the
    running site. Cleanup resolves the wildcard to concrete names first
    because ES ships with action.destructive_requires_name, which rejects
    wildcard deletes; resolving also sweeps up strays from crashed runs.
    """
    settings.ELASTICSEARCH_INDEX_PREFIX = "test-search"
    yield "test-search"
    client = search_client()
    names = list(client.indices.get(index="test-search-*"))
    if names:
        client.indices.delete(index=",".join(names))


@pytest.fixture
def memory_storage(monkeypatch: pytest.MonkeyPatch) -> Storage:
    """Give DemoUpload.file an in-memory storage for the test.

    A FileField's callable storage is evaluated once, when the model class
    is loaded — overriding the STORAGES setting later does not reach the
    already-bound field. Patching the field's storage attribute is what
    actually redirects writes, and it is why this fixture exists instead of
    a settings override: with the setting alone, tests would silently write
    real files into media/private.
    """
    storage = InMemoryStorage()
    field = DemoUpload._meta.get_field("file")
    monkeypatch.setattr(field, "storage", storage)
    return storage


@pytest.fixture
def user() -> User:
    """A plain account, in no group and holding no permissions."""
    return user_create(email="api@example.com")


@pytest.fixture
def other_user() -> User:
    """A second account, for checking one caller cannot affect another."""
    return user_create(email="other@example.com")


@pytest.fixture
def admin_user() -> User:
    """An account in the Admin group, so it holds app.manage_admin."""
    account = user_create(email="admin@example.com")
    account.groups.add(Group.objects.get(name="Admin"))
    return account


@pytest.fixture
def mint() -> Callable[..., MintedToken]:
    """Mint a token, carrying both demo scopes unless told otherwise."""

    def _mint(
        user: User, *, scopes: list[str] | None = None, days: int = 30
    ) -> MintedToken:
        return api_token_create(
            user=user,
            name="test token",
            scopes=(
                scopes if scopes is not None else ["demo:read", "demo:write"]
            ),
            lifetime_days=days,
        )

    return _mint


@pytest.fixture
def token_auth() -> Callable[[str], dict[str, str]]:
    """Build the Authorization header for a minted token's plaintext."""

    def _token_auth(plaintext: str) -> dict[str, str]:
        return {"Authorization": f"Token {plaintext}"}

    return _token_auth


@pytest.fixture
def grant() -> Callable[..., str]:
    """Grant an OAuth access token the way the consent flow would.

    Returns the opaque token string a client presents as
    `Authorization: Bearer ...`. Carries both demo scopes unless told
    otherwise, mirroring the mint fixture.
    """

    def _grant(
        user: User,
        *,
        scope: str = "demo:read demo:write",
        expires_in: int = 3600,
    ) -> str:
        application = get_application_model().objects.create(
            name="Test Client",
            client_type="confidential",
            authorization_grant_type="authorization-code",
        )
        token = secrets.token_urlsafe(24)
        get_access_token_model().objects.create(
            user=user,
            application=application,
            token=token,
            expires=timezone.now() + timedelta(seconds=expires_in),
            scope=scope,
        )
        return token

    return _grant


@pytest.fixture
def bearer_auth() -> Callable[[str], dict[str, str]]:
    """Build the Authorization header for an OAuth access token."""

    def _bearer_auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _bearer_auth
