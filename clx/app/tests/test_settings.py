import importlib
from types import ModuleType

import pytest

import clx.settings


def reload_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> ModuleType:
    """Re-execute settings.py under a given environment.

    Django's Settings object copies the module's uppercase attributes into
    itself at setup, so reloading the module afterwards rebinds only the
    module's own globals and leaves django.conf.settings alone.
    """
    for name in ("ALLOWED_HOSTS", "CORS_ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return importlib.reload(clx.settings)


@pytest.mark.parametrize("setting", ["ALLOWED_HOSTS", "CORS_ALLOWED_ORIGINS"])
def test_an_unset_comma_separated_setting_parses_to_an_empty_list(
    monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    """A bare "".split(",") yields [""], not [].

    Django matches no host against the empty string, so with DEBUG off and
    ALLOWED_HOSTS unset every request 400s. DEBUG on ignores ALLOWED_HOSTS
    entirely, which is why the mistake survives until deploy. This fails if
    either setting drops the filtering.
    """
    settings = reload_settings(monkeypatch)

    assert getattr(settings, setting) == []


@pytest.mark.parametrize("setting", ["ALLOWED_HOSTS", "CORS_ALLOWED_ORIGINS"])
def test_a_comma_separated_setting_keeps_its_entries_and_drops_blanks(
    monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    """Filtering empties must not cost the values themselves.

    The trailing comma stands in for the hand-edited env var that produced
    the empty entry in the first place.
    """
    settings = reload_settings(
        monkeypatch, **{setting: "a.example,b.example,"}
    )

    assert getattr(settings, setting) == ["a.example", "b.example"]
