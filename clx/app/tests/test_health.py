import json
from pathlib import Path
from typing import Any, NoReturn
from urllib.error import URLError

import pytest
from django.conf import settings
from django.test import Client, override_settings
from django.urls import re_path
from django.views.static import serve

from clx.app.services import health
from clx.app.services.health import CHECKS, health_check_services

# Routes /media/ to Django's serve view, the same routes static() adds to
# the real urlconf under DEBUG. Tests run with DEBUG off, so the real
# urlconf has no media routes; the served-storage test below points
# ROOT_URLCONF at this module to get them back.
urlpatterns = [
    re_path(
        r"^media/(?P<path>.*)$",
        serve,
        {"document_root": settings.MEDIA_ROOT / "public"},
    ),
]


@pytest.mark.django_db
def test_the_api_reports_every_service_the_service_layer_knows_about(
    client: Client,
) -> None:
    """The set of services and how each one is probed lives in
    services.health, not in the interfaces that expose it.

    Both the API endpoint and the MCP health tool call health_check_services, so
    they cannot report different services. This fails if either one goes
    back to composing the dict itself.
    """
    response = client.get("/api/health/", secure=True)

    assert set(response.json()["services"]) == set(CHECKS)


@pytest.mark.django_db
def test_named_services_are_checked_and_others_are_not() -> None:
    assert health_check_services(["postgres"]) == {"postgres": True}


@pytest.mark.django_db
def test_a_down_service_fails_the_probe_with_a_503(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Kubernetes readiness probe and the compose healthcheck read only
    the HTTP status code — neither parses the body, so a "status": false
    field in a 200 response is invisible to both. The endpoint has to say
    503 for a down service to ever fail a probe.

    (urllib.request.urlopen, which the compose healthcheck uses, raises
    HTTPError on a 503, so the same status code serves both probes.)
    """
    monkeypatch.setitem(CHECKS, "postgres", lambda: False)

    response = client.get("/api/health/?services=postgres", secure=True)

    assert response.status_code == 503
    assert response.json()["status"] is False


@pytest.mark.django_db
def test_the_probe_gates_on_the_services_it_names(client: Client) -> None:
    """The probes pass ?services= naming what actually gates web traffic.

    In particular they omit celery: without this filter, a crash-looping
    worker would 503 every web pod's readiness probe and turn a
    background-job outage into a full site outage. This also pins the
    healthy path to a 200, which the bare endpoint cannot do in the test
    environment because no celery worker is running there.
    """
    response = client.get("/api/health/?services=postgres", secure=True)

    assert response.status_code == 200
    assert response.json() == {
        "status": True,
        "services": {"postgres": True},
    }


@pytest.mark.django_db
def test_a_writable_but_unserved_storage_fails_the_probe() -> None:
    """FileSystemStorage saves and deletes happily even when nothing serves
    the files over HTTP — the DEBUG=off + USE_S3=off trap from issue #21,
    where every upload 404s while /api/health/ stays green. Tests run with
    DEBUG off, so the media routes static() would add are absent here,
    exactly like that broken deployment: the write succeeds but the file's
    /media/ URL resolves to nothing. This fails if health_check_storage goes back
    to a save/delete-only probe.
    """
    assert health_check_services(["public_storage"]) == {
        "public_storage": False
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="clx.app.tests.test_health")
def test_a_storage_whose_url_is_routed_passes_the_probe() -> None:
    """With this module's urlpatterns routing /media/, the same storage
    config that fails the test above passes: what the probe checks is
    whether the saved file's URL is actually served, not anything about
    the backend itself.
    """
    assert health_check_services(["public_storage"]) == {
        "public_storage": True
    }


@pytest.mark.django_db
def test_private_storage_is_probed_for_writability_only() -> None:
    """Nothing in this app serves private files over HTTP — no view streams
    them, and the private FileSystemStorage backend's .url() is a lie
    anyway (with no base_url configured Django falls back to MEDIA_URL,
    which serves the public location where its files don't live). So the
    private probe's whole contract is save/delete. It must stay that way:
    dev compose gates the web container's healthcheck on private_storage,
    and a URL requirement would keep every dev stack permanently
    unhealthy. This fails, here where no /media/ route exists, if the
    private check is ever flipped to served=True.
    """
    assert health_check_services(["private_storage"]) == {
        "private_storage": True
    }


def absolute_url_storages(location: Path) -> dict[str, Any]:
    """A STORAGES config whose default alias returns absolute URLs, so the
    urlopen branch of the probe runs without needing S3 in the tests.
    """
    return {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {
                "location": location,
                "base_url": "https://cdn.example/media/",
            },
        },
    }


@pytest.mark.django_db
def test_an_unfetchable_absolute_storage_url_fails_the_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """S3 backends return absolute URLs, which no urlconf can vouch for —
    the probe has to actually GET them so a wrong ACL or an unreachable
    bucket shows up. An absolute base_url makes FileSystemStorage produce
    such URLs without needing S3 in the test; the stub proves the fetch
    happens, and its failure must fail the probe rather than the probe
    trusting that a URL merely exists.
    """
    fetched = []

    def failing_urlopen(url: str, timeout: float) -> NoReturn:
        fetched.append(url)
        raise URLError("unreachable")

    monkeypatch.setattr(health, "urlopen", failing_urlopen)

    with override_settings(STORAGES=absolute_url_storages(tmp_path)):
        assert health_check_services(["public_storage"]) == {
            "public_storage": False
        }
    assert fetched == ["https://cdn.example/media/health_check"]


@pytest.mark.django_db
def test_a_fetchable_absolute_storage_url_passes_the_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The healthy mirror of the test above: when the GET succeeds with a
    200, the probe passes.
    """

    class OkResponse:
        status = 200

        def __enter__(self) -> "OkResponse":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(health, "urlopen", lambda url, timeout: OkResponse())

    with override_settings(STORAGES=absolute_url_storages(tmp_path)):
        assert health_check_services(["public_storage"]) == {
            "public_storage": True
        }


def elasticsearch_health_response(status: str) -> Any:
    """A urlopen-shaped stub returning a cluster-health body."""

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"status": status}).encode()

    return Response()


def test_a_yellow_elasticsearch_cluster_passes_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single-node cluster keeps every replica shard unassigned, so once
    any index exists it reports yellow forever — green never comes. A probe
    that demanded green would mark the deployment permanently unhealthy,
    so yellow has to count as healthy. This also pins where the probe
    looks: _cluster/health under settings.ELASTICSEARCH_URL.
    """
    fetched = []

    def fake_urlopen(url: str, timeout: float) -> Any:
        fetched.append(url)
        return elasticsearch_health_response("yellow")

    monkeypatch.setattr(health, "urlopen", fake_urlopen)

    assert health_check_services(["elasticsearch"]) == {"elasticsearch": True}
    assert fetched == [f"{settings.ELASTICSEARCH_URL}/_cluster/health"]


def test_a_red_elasticsearch_cluster_fails_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_cluster/health answers 200 whatever the color, so reachability
    alone proves nothing — the probe must read the body and fail on red,
    or a cluster that lost its shards would still pass.
    """
    monkeypatch.setattr(
        health,
        "urlopen",
        lambda url, timeout: elasticsearch_health_response("red"),
    )

    assert health_check_services(["elasticsearch"]) == {"elasticsearch": False}


def test_an_unreachable_elasticsearch_fails_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_urlopen(url: str, timeout: float) -> NoReturn:
        raise URLError("unreachable")

    monkeypatch.setattr(health, "urlopen", failing_urlopen)

    assert health_check_services(["elasticsearch"]) == {"elasticsearch": False}


@pytest.mark.django_db
def test_unknown_service_names_are_rejected_not_ignored(
    client: Client,
) -> None:
    """A typo in a probe URL must not produce a passing probe that checks
    nothing (or a 500). ApplicationError renders as a 400 naming the bad
    service, which is what an operator debugging the probe needs to see.
    """
    response = client.get("/api/health/?services=postgrs", secure=True)

    assert response.status_code == 400
    assert "postgrs" in response.json()["message"]


@pytest.mark.django_db
def test_head_is_allowed_and_writes_are_not(client: Client) -> None:
    """HEAD has to work, because monitors use it to skip the body.

    Django's require_GET is require_http_methods(["GET"]) and function views
    get no automatic HEAD-to-GET mapping, so the obvious decorator would
    answer 405 and a HEAD-configured uptime check would report the service
    down. Writes are still refused: this endpoint only reads.

    HEAD is checked for the method being accepted rather than for a
    particular status, since 503 is a correct answer here: the point is
    that it is not 405.
    """
    head = client.head("/api/health/", secure=True)

    assert head.status_code in {200, 503}
    assert client.post("/api/health/", secure=True).status_code == 405
    assert client.delete("/api/health/", secure=True).status_code == 405
