"""Guard against a deploy that silently empties the app-env Secret.

`app_secrets()` reads the app's secrets out of `ALL_SECRETS`, a JSON blob
CI builds from the repository secrets. Nothing else supplies it, so any
run outside CI -- a local `pulumi up`, a misconfigured workflow -- sees an
empty value.

Without a guard that is not an error: the function returns `{}`, Pulumi
diffs the `app-env` Secret down to nothing, and the update wipes every
runtime secret the app has. The deploy "succeeds" and the app comes back
up with no database URL, no Sentry DSN and no signing key.

So an empty result must fail the update instead. Previews are exempt --
they mutate nothing, and a local `pulumi preview` is the normal way to
check a plan without CI's secrets in the environment.
"""

import json

import pytest

from infra.deploy_secrets import INFRA_ONLY_SECRETS, app_secrets


@pytest.fixture
def update(monkeypatch):
    """Run as a real update, where an empty result would do damage."""
    monkeypatch.setattr("pulumi.runtime.is_dry_run", lambda: False)


@pytest.fixture
def preview(monkeypatch):
    """Run as a preview, which changes nothing and so may come up empty."""
    monkeypatch.setattr("pulumi.runtime.is_dry_run", lambda: True)


def test_unset_all_secrets_blocks_an_update(update, monkeypatch):
    """The case this guard exists for: a local `pulumi up`.

    ALL_SECRETS is only ever set by CI. Unset, every app secret would be
    stripped from app-env, so the update must not proceed.
    """
    monkeypatch.delenv("ALL_SECRETS", raising=False)

    with pytest.raises(ValueError, match="would empty"):
        app_secrets()


def test_unset_all_secrets_allows_a_preview(preview, monkeypatch):
    """A preview writes nothing, so it must stay usable without CI's env.

    If this raised, `pulumi preview` would be impossible to run locally
    and the guard would cost more than it saves.
    """
    monkeypatch.delenv("ALL_SECRETS", raising=False)

    assert app_secrets() == {}


def test_only_infra_keys_blocks_an_update(update, monkeypatch):
    """Present-but-useless is as destructive as absent.

    Every key in INFRA_ONLY_SECRETS is filtered out before the result is
    built, so a payload of nothing but those keys still empties app-env.
    Checking the filtered result rather than the raw variable is what
    catches this.
    """
    payload = dict.fromkeys(INFRA_ONLY_SECRETS, "x")
    monkeypatch.setenv("ALL_SECRETS", json.dumps(payload))

    with pytest.raises(ValueError, match="would empty"):
        app_secrets()


def test_invalid_json_blocks_an_update(update, monkeypatch):
    """Unparseable input must not degrade quietly into an empty secret.

    It warns and moves on, so without the guard a truncated or malformed
    ALL_SECRETS would wipe app-env exactly as an unset one would.
    """
    monkeypatch.setenv("ALL_SECRETS", '{"truncated": ')

    with pytest.raises(ValueError, match="would empty"):
        app_secrets()


def test_real_secrets_pass_through_with_infra_keys_removed(
    update, monkeypatch
):
    """The normal CI path: app secrets survive, infra-only ones do not.

    The infra credentials share the same blob but have no business in the
    app's environment, and the guard must not be so eager that it blocks
    a legitimate update.
    """
    monkeypatch.setenv(
        "ALL_SECRETS",
        json.dumps(
            {
                "SENTRY_DSN": "https://sentry.example/1",
                "SECRET_KEY": "s3cret",
                "EMPTY": "",
                "DIGITALOCEAN_TOKEN": "dop_v1_x",
            }
        ),
    )

    assert app_secrets() == {
        "SENTRY_DSN": "https://sentry.example/1",
        "SECRET_KEY": "s3cret",
    }
