"""The token service: how a credential is minted, aged and retired.

These cover `services/token.py` rather than the request path -- what the
plaintext is, what is stored, and what happens on rotation and expiry.
"""

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from pytest_django.fixtures import SettingsWrapper

from clx.app.exceptions import ApplicationError
from clx.app.models import ApiToken, User
from clx.app.services.api_token import (
    MintedToken,
    api_token_hash,
    api_token_touch,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("clx.app.tests.urls_api_auth"),
]


def test_plaintext_is_returned_once_and_never_stored(
    user: User, mint: Callable[..., MintedToken]
) -> None:
    """A database leak must not yield working credentials.

    Only the SHA-256 of the secret is persisted, so the plaintext exists
    exactly once, in the creation response. If this ever regresses to
    storing the token itself, the value would be found in the row.
    """
    minted = mint(user)
    stored = ApiToken.objects.get(pk=minted.token.pk)

    assert minted.plaintext.startswith("pat_")
    assert minted.plaintext not in stored.token_hash
    assert stored.token_hash != minted.plaintext
    assert stored.token_id in minted.plaintext


def test_a_secret_containing_an_underscore_still_parses(
    client: Client,
    user: User,
    mint: Callable[..., MintedToken],
    token_auth: Callable[[str], dict[str, str]],
) -> None:
    """The separator also occurs inside the secret, so splitting must bound.

    secrets.token_urlsafe draws from the base64url alphabet, which includes
    the underscore used to separate the token's parts. An unbounded split
    therefore produced four fields for roughly half of all tokens and the
    parse silently failed, giving an intermittent 401 that depended on
    which random bytes came up. The lookup id is hex so it never carries
    one, and the split stops after the id so the secret keeps its own.
    """
    minted = mint(user)
    forced = f"pat_{minted.token.token_id}_a_b"
    minted.token.token_hash = api_token_hash("a_b")
    minted.token.save()

    response = client.get(
        reverse("t-token"), secure=True, headers=token_auth(forced)
    )

    assert "_" not in minted.token.token_id
    assert response.status_code == 200


def test_lifetime_is_capped(
    user: User, settings: SettingsWrapper, mint: Callable[..., MintedToken]
) -> None:
    """The cap is what stops a token from being effectively permanent."""
    settings.API_TOKEN_MAX_LIFETIME_DAYS = 90

    with pytest.raises(ApplicationError, match="between 1 and 90"):
        mint(user, days=91)


def test_rotation_revokes_the_old_token_and_issues_a_new_one(
    client: Client, user: User, mint: Callable[..., MintedToken]
) -> None:
    """Rotation has to invalidate the old secret, or it is only issuance."""
    original = mint(user, scopes=["demo:read"])
    client.force_login(user)

    response = client.post(
        reverse("tokens-rotate", args=[original.token.id]), secure=True
    )
    replacement = response.json()

    original.token.refresh_from_db()
    assert response.status_code == 200
    assert original.token.is_revoked
    assert replacement["plaintext"] != original.plaintext
    assert replacement["token"]["scopes"] == ["demo:read"]


def test_touching_a_token_stays_a_single_query(
    user: User,
    django_assert_num_queries: Any,
    mint: Callable[..., MintedToken],
) -> None:
    """The one write that deliberately skips full_clean, and why.

    Every save() in the project validates before saving (app.E606 enforces
    it), and api_token_revoke does too. This one runs on every
    authenticated request, and full_clean calls validate_unique, which
    issues a SELECT against the unique token_id. That would put a second
    query on the hot path of every API call to save a check on a field the
    service never changes. So the stamp is a queryset .update() — the
    ORM's native narrow write, the same shape demo_job_cancel uses — which
    is also what keeps it out of E606's save() scan without an exemption.

    This fails if the write starts costing more than itself, which is what
    validation here would do.
    """
    minted = mint(user)
    minted.token.last_used_at = None

    with django_assert_num_queries(1):
        api_token_touch(token=minted.token)
