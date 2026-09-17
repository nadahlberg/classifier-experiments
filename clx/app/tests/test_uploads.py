from typing import Any, cast

import pytest
from django.core.files.storage import Storage
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.test import Client

from clx.app.exceptions import ApplicationError
from clx.app.models import DemoUpload, User
from clx.app.services import demo as demo_service
from clx.app.services.user import user_create


@pytest.fixture
def user(memory_storage: Storage) -> User:
    return user_create(email="uploader@example.com")


@pytest.mark.django_db
def test_files_are_namespaced_by_user_then_upload_then_filename(
    user: User,
) -> None:
    """The bucket path is user id / upload id / original filename, so one
    user's objects live under one prefix, every upload gets its own folder,
    and two files with the same name can never collide.
    """
    (upload,) = demo_service.demo_upload_create_batch(
        user=user,
        files=[SimpleUploadedFile("hello.txt", b"hi", "text/plain")],
    )

    assert upload.file.name == f"{user.id}/{upload.id}/hello.txt"


@pytest.mark.django_db
def test_upload_limits_are_enforced_in_the_service(user: User) -> None:
    """The modal enforces limits for feedback, but the service is the real
    gate: too many files or an oversized file rejects the whole batch before
    anything is stored.
    """
    too_many: list[UploadedFile] = [
        SimpleUploadedFile(f"f{i}.txt", b"x", "text/plain")
        for i in range(demo_service.MAX_UPLOAD_FILES + 1)
    ]
    with pytest.raises(ApplicationError):
        demo_service.demo_upload_create_batch(user=user, files=too_many)

    big = SimpleUploadedFile("big.bin", b"x", "application/octet-stream")
    big.size = demo_service.MAX_UPLOAD_SIZE + 1
    with pytest.raises(ApplicationError):
        demo_service.demo_upload_create_batch(user=user, files=[big])

    assert not DemoUpload.objects.exists()


@pytest.mark.django_db
def test_delete_removes_the_row_and_the_stored_object(
    memory_storage: Storage, user: User
) -> None:
    """FileField does not delete storage objects when a row is deleted, so
    the service does it explicitly — otherwise every deleted card would leak
    an orphaned object into the bucket.
    """
    (upload,) = demo_service.demo_upload_create_batch(
        user=user,
        files=[SimpleUploadedFile("gone.txt", b"bye", "text/plain")],
    )
    name = upload.file.name
    assert name
    assert memory_storage.exists(name)

    demo_service.demo_upload_delete(user=user, upload_id=str(upload.id))

    assert not DemoUpload.objects.exists()
    assert not memory_storage.exists(name)


@pytest.mark.django_db
def test_streams_are_scoped_to_the_owner(user: User) -> None:
    """Previews and downloads go through Django precisely so ownership is
    checked per request: another user's valid upload id 404s rather than
    serving their file, and anonymous callers get the standard 401.
    """
    (upload,) = demo_service.demo_upload_create_batch(
        user=user,
        files=[SimpleUploadedFile("mine.txt", b"secret", "text/plain")],
    )

    owner = Client()
    owner.force_login(user)
    inline = owner.get(f"/api/demos/uploads/{upload.id}/file/", secure=True)
    assert inline.status_code == 200
    assert b"".join(cast("Any", inline).streaming_content) == b"secret"
    # The clickjacking middleware stamps DENY on every response, which
    # blocks our own preview iframes; the inline endpoint must relax it
    # to SAMEORIGIN or PDF and HTML previews silently refuse to render.
    assert inline.headers["X-Frame-Options"] == "SAMEORIGIN"

    download = owner.get(
        f"/api/demos/uploads/{upload.id}/download/", secure=True
    )
    assert (
        'attachment; filename="mine.txt"'
        in download.headers["Content-Disposition"]
    )

    stranger = Client()
    stranger.force_login(user_create(email="stranger@example.com"))
    assert (
        stranger.get(
            f"/api/demos/uploads/{upload.id}/file/", secure=True
        ).status_code
        == 404
    )

    assert (
        Client()
        .get(f"/api/demos/uploads/{upload.id}/file/", secure=True)
        .status_code
        == 401
    )


@pytest.mark.django_db
def test_upload_endpoint_stores_the_batch_for_the_caller(user: User) -> None:
    """The multipart endpoint accepts several files under one files field
    and scopes the resulting rows to the session user.
    """
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/demos/uploads/create/",
        {
            "files": [
                SimpleUploadedFile("a.txt", b"a", "text/plain"),
                SimpleUploadedFile("b.png", b"b", "image/png"),
            ]
        },
        secure=True,
    )

    assert response.status_code == 201
    assert DemoUpload.objects.filter(user=user).count() == 2

    listed = client.get("/api/demos/uploads/", secure=True).json()
    assert sorted(u["name"] for u in listed["uploads"]) == ["a.txt", "b.png"]


@pytest.mark.django_db
def test_uploads_page_requires_login(user: User) -> None:
    """Uploads are user-scoped, so the page bounces anonymous visitors."""
    client = Client()
    assert client.get("/demos/uploads/", secure=True).status_code == 302

    client.force_login(user)
    page = client.get("/demos/uploads/", secure=True)
    assert page.status_code == 200
    assert b"Drag files here" in page.content
