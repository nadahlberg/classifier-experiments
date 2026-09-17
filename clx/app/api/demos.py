import uuid
from typing import Any, cast

from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    JsonResponse,
)
from django.utils.formats import date_format
from django.utils.text import Truncator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

from clx.app.api.utils import (
    PUBLIC,
    SESSION,
    TOKEN,
    Auth,
    api_auth,
    decode_cursor,
    encode_cursor,
    frame_self,
    parse_body,
    parse_float,
    parse_int,
)
from clx.app.exceptions import ApplicationError
from clx.app.models import (
    DemoDocket,
    DemoJob,
    DemoUpload,
    User,
)
from clx.app.permissions import MANAGE_ADMIN, MANAGE_DEVELOPER
from clx.app.selectors.demo import (
    DEMO_DOCKET_SEARCH_LIMIT,
    DEMO_DOCKET_SORTS,
    demo_docket_facet_options,
    demo_docket_search,
    demo_heartbeat_read,
    demo_job_list,
    demo_upload_get,
    demo_upload_list,
)
from clx.app.services.demo import (
    demo_docket_import,
    demo_job_cancel,
    demo_job_delete,
    demo_job_run,
    demo_job_run_batch,
    demo_upload_create_batch,
    demo_upload_delete,
)


@require_GET
@api_auth(SESSION)
def heartbeat(request: HttpRequest) -> JsonResponse:
    """The last time the scheduled heartbeat task ran."""
    return JsonResponse({"last_run": demo_heartbeat_read()})


@require_GET
@api_auth(SESSION)
def job_list(request: HttpRequest) -> JsonResponse:
    """List the caller's demo jobs with their subtasks."""
    jobs = demo_job_list(user=cast("User", request.user))
    return JsonResponse(
        {
            "jobs": [
                _job(job, children=list(job.children.all())) for job in jobs
            ]
        }
    )


@require_POST
@api_auth(SESSION)
def job_run(request: HttpRequest) -> JsonResponse:
    """Queue a demo job, optionally delayed by delay_seconds."""
    body = parse_body(request)
    job = demo_job_run(
        user=cast("User", request.user),
        delay_seconds=parse_int(body, "delay_seconds", default=0),
    )
    return JsonResponse(_job(job), status=201)


@require_POST
@api_auth(SESSION)
def job_run_batch(request: HttpRequest) -> JsonResponse:
    """Queue a parent demo job with subtask_count subtasks."""
    body = parse_body(request)
    job = demo_job_run_batch(
        user=cast("User", request.user),
        subtask_count=parse_int(body, "subtask_count", default=5),
        fail_rate=parse_float(body, "fail_rate", default=0.0),
    )
    return JsonResponse(_job(job), status=201)


@require_POST
@api_auth(SESSION)
def job_cancel(request: HttpRequest, job_id: uuid.UUID) -> JsonResponse:
    """Cancel one of the caller's running demo jobs."""
    job = demo_job_cancel(user=cast("User", request.user), job_id=str(job_id))
    return JsonResponse(_job(job))


@require_http_methods(["DELETE"])
@api_auth(SESSION)
def job_delete(request: HttpRequest, job_id: uuid.UUID) -> JsonResponse:
    """Delete one of the caller's demo jobs along with its subtasks."""
    demo_job_delete(user=cast("User", request.user), job_id=str(job_id))
    return JsonResponse({"deleted": True})


@require_POST
@api_auth(SESSION)
def docket_import(request: HttpRequest) -> JsonResponse:
    """Drop the demo docket tables and reimport the packaged sample."""
    return JsonResponse(demo_docket_import())


DOCKET_PREVIEW_PARTIES = 4


@require_GET
@api_auth(SESSION)
def docket_facet_options(request: HttpRequest) -> JsonResponse:
    """The facet options for the docket search sidebar."""
    return JsonResponse({"facets": demo_docket_facet_options()})


@require_GET
@api_auth(SESSION)
def docket_search(request: HttpRequest) -> JsonResponse:
    """Search one page of demo dockets, with facets and a next cursor."""
    sort = str(request.GET.get("sort", "relevance"))
    if sort not in DEMO_DOCKET_SORTS:
        raise ApplicationError(
            f"sort must be one of: {', '.join(DEMO_DOCKET_SORTS)}"
        )
    after = None
    token = str(request.GET.get("cursor", ""))
    if token:
        payload = decode_cursor(token)
        if payload.get("sort") != sort:
            raise ApplicationError("Cursor does not match the requested sort")
        after = payload.get("after")
        if not isinstance(after, list):
            raise ApplicationError("Invalid cursor")
    results = demo_docket_search(
        query=str(request.GET.get("q", "")),
        jurisdiction=str(request.GET.get("jurisdiction", "")),
        jury_demand=str(request.GET.get("jury_demand", "")),
        sort=sort,
        after=after,
        limit=parse_int(
            request.GET, "limit", default=DEMO_DOCKET_SEARCH_LIMIT
        ),
    )
    return JsonResponse(
        {
            "results": [_docket_hit(docket) for docket in results.dockets],
            "total": results.total,
            "facets": results.facets,
            "page_size": results.limit,
            "next": (
                encode_cursor({"sort": sort, "after": results.next_after})
                if results.next_after
                else ""
            ),
        }
    )


def _docket_hit(docket: DemoDocket) -> dict[str, Any]:
    parties = list(docket.parties.all())
    names = [party.name for party in parties[:DOCKET_PREVIEW_PARTIES]]
    extra_parties = len(parties) - len(names)
    entries = cast("list[Any]", docket.first_entries)  # type: ignore[attr-defined]
    more_entries = cast("int", docket.entry_count) - len(entries)  # type: ignore[attr-defined]
    return {
        "id": docket.docket_id,
        "case_name": docket.case_name,
        "court": docket.court_id.upper(),
        "docket_number": docket.docket_number,
        "filed_label": date_format(docket.date_filed, "M j, Y"),
        "jurisdiction": docket.jurisdiction,
        "is_terminated": docket.date_terminated is not None,
        "parties_label": ", ".join(names)
        + (f" +{extra_parties} more" if extra_parties > 0 else ""),
        "entries": [
            {
                "filed_label": date_format(entry.date_filed, "M j, Y"),
                "number": entry.document_number,
                "description": Truncator(entry.description).chars(240),
            }
            for entry in entries
        ],
        "more_entries_label": (
            f"{more_entries} more entries" if more_entries > 0 else ""
        ),
    }


@require_GET
@api_auth(SESSION)
def upload_list(request: HttpRequest) -> JsonResponse:
    """List the caller's uploads."""
    uploads = demo_upload_list(user=cast("User", request.user))
    return JsonResponse({"uploads": [_upload(u) for u in uploads]})


@require_POST
@api_auth(SESSION)
def upload_create(request: HttpRequest) -> JsonResponse:
    """Store the multipart files sent under the files field."""
    uploads = demo_upload_create_batch(
        user=cast("User", request.user),
        files=request.FILES.getlist("files"),
    )
    return JsonResponse({"uploads": [_upload(u) for u in uploads]}, status=201)


@require_http_methods(["DELETE"])
@api_auth(SESSION)
def upload_delete(request: HttpRequest, upload_id: uuid.UUID) -> JsonResponse:
    """Delete one of the caller's uploads and its stored file."""
    demo_upload_delete(
        user=cast("User", request.user), upload_id=str(upload_id)
    )
    return JsonResponse({"deleted": True})


@require_GET
@frame_self
@xframe_options_sameorigin
@api_auth(SESSION)
def upload_file(request: HttpRequest, upload_id: uuid.UUID) -> FileResponse:
    """Stream an upload inline, for previews."""
    return _stream(request, upload_id, as_attachment=False)


@require_GET
@api_auth(SESSION)
def upload_download(
    request: HttpRequest, upload_id: uuid.UUID
) -> FileResponse:
    """Stream an upload as an attachment download."""
    return _stream(request, upload_id, as_attachment=True)


def _stream(
    request: HttpRequest, upload_id: uuid.UUID, *, as_attachment: bool
) -> FileResponse:
    upload = demo_upload_get(
        user=cast("User", request.user), upload_id=str(upload_id)
    )
    if upload is None:
        raise Http404
    return FileResponse(
        upload.file.open("rb"),
        as_attachment=as_attachment,
        filename=upload.name,
        content_type=upload.content_type or None,
    )


def _upload(upload: DemoUpload) -> dict[str, Any]:
    return {
        "id": str(upload.id),
        "name": upload.name,
        "size": upload.size,
        "content_type": upload.content_type,
        "created_at": _iso(upload.created_at),
    }


def _job(
    job: DemoJob, children: list[DemoJob] | None = None
) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "name": job.name,
        "status": job.status,
        "scheduled_for": _iso(job.scheduled_for),
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "children": [_job(child) for child in children or []],
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


AUTH_BURST_LIMIT = 5
AUTH_BURST_WINDOW_SECONDS = 60


def _auth_whoami(request: HttpRequest, note: str) -> dict[str, Any]:
    auth = cast("Auth", request.auth)  # type: ignore[attr-defined]
    return {
        "note": note,
        "user": auth.user.email,
        "auth_method": auth.method,
        "token_name": auth.token.name if auth.token else None,
        "client": auth.client,
        "scopes": list(auth.scopes),
    }


@require_GET
@api_auth(PUBLIC)
def auth_public(request: HttpRequest) -> JsonResponse:
    """Open endpoint: no credentials, callable by anyone."""
    return JsonResponse(
        {"note": "No authentication required.", "auth_method": None}
    )


@require_GET
@api_auth(SESSION)
def auth_session_only(request: HttpRequest) -> JsonResponse:
    """Session cookie only; an API token is rejected here."""
    return JsonResponse(_auth_whoami(request, "Session cookie only."))


@require_GET
@api_auth(TOKEN)
def auth_token_only(request: HttpRequest) -> JsonResponse:
    """API token only; a logged-in browser session is rejected here."""
    return JsonResponse(_auth_whoami(request, "API token only."))


@require_GET
@api_auth(SESSION, TOKEN)
def auth_session_or_token(request: HttpRequest) -> JsonResponse:
    """Either method is accepted, resolved by the authenticator chain."""
    return JsonResponse(_auth_whoami(request, "Session cookie or API token."))


@require_GET
@api_auth(SESSION, TOKEN, scopes=["demo:read"])
def auth_scoped_read(request: HttpRequest) -> JsonResponse:
    """Requires the demo:read scope when called with a token."""
    return JsonResponse(_auth_whoami(request, "Requires scope demo:read."))


@require_POST
@api_auth(SESSION, TOKEN, scopes=["demo:write"])
def auth_scoped_write(request: HttpRequest) -> JsonResponse:
    """Requires the demo:write scope when called with a token."""
    return JsonResponse(_auth_whoami(request, "Requires scope demo:write."))


@require_POST
@api_auth(SESSION, TOKEN, scopes=["demo:read", "demo:write"])
def auth_scoped_both(request: HttpRequest) -> JsonResponse:
    """Requires both scopes, and counts against both scope budgets."""
    return JsonResponse(
        _auth_whoami(request, "Requires demo:read and demo:write.")
    )


@require_GET
@api_auth(SESSION, TOKEN, perms=[MANAGE_ADMIN])
def auth_admin_only(request: HttpRequest) -> JsonResponse:
    """Requires the app.manage_admin permission, session or token."""
    return JsonResponse(_auth_whoami(request, "Requires manage_admin."))


@require_GET
@api_auth(SESSION, TOKEN, perms=[MANAGE_DEVELOPER], scopes=["demo:read"])
def auth_developer_scoped(request: HttpRequest) -> JsonResponse:
    """Requires manage_developer and, for a token, the demo:read scope."""
    return JsonResponse(
        _auth_whoami(request, "Requires manage_developer + demo:read.")
    )


@require_GET
@api_auth(SESSION, TOKEN, rate=(AUTH_BURST_LIMIT, AUTH_BURST_WINDOW_SECONDS))
def auth_burst(request: HttpRequest) -> JsonResponse:
    """Tightly rate limited so a 429 is easy to provoke."""
    payload = _auth_whoami(
        request, f"{AUTH_BURST_LIMIT} per {AUTH_BURST_WINDOW_SECONDS}s."
    )
    return JsonResponse(payload)
