import re
from pathlib import Path

import pytest
from django.contrib.auth.models import Group
from django.core.files.storage import Storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from clx.app.services.demo import demo_upload_create_batch
from clx.app.services.user import user_create
from clx.app.tests.test_settings import reload_settings
from clx.app.urls import (
    admin_view_patterns,
    demos_view_patterns,
    main_view_patterns,
)

ALPINE = Path(__file__).parent.parent / "static" / "js" / "alpine.min.js"


@pytest.mark.django_db
def test_csp_header_is_strict(client: Client) -> None:
    """Scripts are allowed only from ourselves — no nonce, no
    unsafe-inline, no unsafe-eval — which is the whole point of running the
    Alpine CSP build.

    form-action is deliberately absent: Chrome enforces it against the
    redirect target of a form submission, and the OAuth authorize form 302s
    to the client's redirect URI after POST, so any form-action value we
    could write here would break MCP client authorization.
    """
    response = client.get("/", secure=True)
    policy = response.headers["Content-Security-Policy"]

    assert "default-src 'self'" in policy
    assert "script-src 'self'" in policy
    assert "nonce-" not in policy
    assert "unsafe-inline" not in policy
    assert "unsafe-eval" not in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "form-action" not in policy


@pytest.mark.django_db
def test_no_page_renders_an_inline_script(client: Client) -> None:
    """script-src 'self' with no nonce blocks every inline script outright,
    so a page that renders one silently loses that behaviour. The page list
    is derived from the view pattern lists, so a new page joins this check
    by existing — and a new view domain must join the list below, which the
    length assertion cannot catch, so it is worth remembering. The user
    joins the Developer group so permission-gated pages render instead of
    redirecting, and the client follows redirects because some routed names
    (the bare admin route) are redirects to a default tab, whose body is
    what needs checking.

    json_script data blocks pass: CSP governs execution, and a script
    element with a non-JavaScript type is never executed, which is why
    json_script is Django's documented way to hand request-time context
    to JavaScript under a strict policy. The codebase explorer embeds its
    inventory that way, so the guard allows inert data blocks while still
    failing on anything the browser would try to run.
    """
    patterns = [
        *main_view_patterns,
        *demos_view_patterns,
        *admin_view_patterns,
    ]
    pages = [reverse(pattern.name) for pattern in patterns if pattern.name]
    assert len(pages) == len(patterns)

    user = user_create(email="csp@example.com")
    user.groups.add(Group.objects.get(name="Developer"))
    client.force_login(user)
    for page in pages:
        response = client.get(page, secure=True, follow=True)
        assert response.status_code == 200, page

        tags = re.findall(r"<script\b[^>]*>", response.content.decode())
        assert tags, page
        for tag in tags:
            assert " src=" in tag or 'type="application/json"' in tag, (
                page,
                tag,
            )


@pytest.mark.django_db
def test_upload_inline_stream_relaxes_frame_ancestors_to_self(
    memory_storage: Storage,
) -> None:
    """Preview cards frame the inline stream from our own pages, and the
    global frame-ancestors 'none' would blank every preview iframe. The
    inline stream swaps just that directive to 'self'; the download response
    keeps 'none' because nothing legitimate ever frames a download.
    """
    user = user_create(email="framer@example.com")
    (upload,) = demo_upload_create_batch(
        user=user,
        files=[SimpleUploadedFile("page.html", b"<p>hi</p>", "text/html")],
    )
    client = Client()
    client.force_login(user)

    inline = client.get(f"/api/demos/uploads/{upload.id}/file/", secure=True)
    download = client.get(
        f"/api/demos/uploads/{upload.id}/download/", secure=True
    )

    assert (
        "frame-ancestors 'self'" in inline.headers["Content-Security-Policy"]
    )
    assert (
        "frame-ancestors 'none'" in download.headers["Content-Security-Policy"]
    )


def test_vendored_alpine_is_the_csp_build() -> None:
    """The strict policy rests on the vendored Alpine being the CSP-friendly
    build. The standard build compiles every directive expression with the
    Function constructor, which needs unsafe-eval and turns any HTML
    injection into code execution through the framework — swapping it back in
    would silently defeat the policy. The CSP build identifies itself by the
    runtime error message it prints for unsupported expressions; the standard
    build has no such string.
    """
    assert "CSP-friendly build" in ALPINE.read_text()


S3_ENV = {
    "USE_S3": "on",
    "AWS_S3_ENDPOINT_URL": "https://nyc3.digitaloceanspaces.com",
    "AWS_PUBLIC_BUCKET": "bucket-public",
    "AWS_PRIVATE_BUCKET": "bucket-private",
}
BUCKET = "https://nyc3.digitaloceanspaces.com/bucket-public/"


@pytest.mark.parametrize("directive", ["script-src", "style-src", "img-src"])
def test_s3_static_is_an_allowed_source(
    monkeypatch: pytest.MonkeyPatch, directive: str
) -> None:
    """With USE_S3 on, collectstatic serves from the bucket, not from us.

    'self' is the page's own origin, so every stylesheet, script and icon
    then comes from a cross-origin host and the policy blocks all of it —
    the site renders unstyled with no JavaScript. Only these three
    directives are involved because static holds only css, js and images;
    uploads live in the private bucket and stream through our own views,
    so they stay same-origin.
    """
    settings = reload_settings(monkeypatch, **S3_ENV)

    assert BUCKET in settings.CONTENT_SECURITY_POLICY["DIRECTIVES"][directive]


def test_s3_static_source_is_scoped_to_the_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The source must carry the bucket path, not just the Spaces host.

    Spaces puts every tenant's bucket on one regional host, so a bare
    https://nyc3.digitaloceanspaces.com would let any other customer's
    bucket in that region load scripts into our pages. The trailing slash
    is what makes CSP treat the value as a path prefix rather than an
    exact URL.
    """
    settings = reload_settings(monkeypatch, **S3_ENV)
    sources = settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]["script-src"]

    assert "https://nyc3.digitaloceanspaces.com" not in sources
    assert all(not s.endswith("digitaloceanspaces.com") for s in sources)
    assert BUCKET.endswith("/")


def test_no_remote_source_without_s3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local runs serve static themselves and must stay strictly same-origin.

    Carrying a bucket into the local policy would widen it for no reason
    and hide a broken cross-origin load until deploy.
    """
    monkeypatch.delenv("USE_S3", raising=False)
    settings = reload_settings(monkeypatch)
    directives = settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]

    assert directives["script-src"] == ["'self'"]
    assert directives["style-src"] == ["'self'"]
    assert directives["img-src"] == ["'self'", "blob:"]
