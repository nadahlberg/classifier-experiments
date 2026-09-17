from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from django.views.generic import RedirectView, TemplateView
from oauth2_provider import urls as oauth2_urls

from clx.app.api import admin as admin_api
from clx.app.api import demos as demos_api
from clx.app.api import health, tokens, users
from clx.app.views import admin, demos, main

main_view_patterns = [
    path("", main.index, name="index"),
    path("profile/", main.profile, name="profile"),
]

demos_view_patterns = [
    path("", demos.index, name="demos"),
    path("card/", demos.card, name="demos-card"),
    path("celery/", demos.celery, name="demos-celery"),
    path("uploads/", demos.uploads, name="demos-uploads"),
    path("card-grid/", demos.card_grid, name="demos-card-grid"),
    path("content/", demos.content, name="demos-content"),
    path("markdown/", demos.markdown, name="demos-markdown"),
    path("components/", demos.components, name="demos-components"),
    path("dashboard/", demos.dashboard, name="demos-dashboard"),
    path("api/", demos.api, name="demos-api"),
    path("search/", demos.search, name="demos-search"),
]

admin_view_patterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="admin-settings"),
        name="admin",
    ),
    path("settings/", admin.settings, name="admin-settings"),
    path("users/", admin.users, name="admin-users"),
    path("codebase/", admin.codebase, name="admin-codebase"),
]

pwa_patterns = [
    path(
        "sw.js",
        TemplateView.as_view(
            template_name="pages/sw.js",
            content_type="application/javascript",
        ),
        name="service-worker",
    ),
    path(
        "manifest.webmanifest",
        TemplateView.as_view(
            template_name="pages/manifest.webmanifest",
            content_type="application/manifest+json",
        ),
        name="manifest",
    ),
]

oauth_metadata_patterns = oauth2_urls.metadata_urlpatterns

oauth_patterns = oauth2_urls.base_urlpatterns + oauth2_urls.dcr_urlpatterns

admin_api_patterns = [
    path(
        "settings/",
        admin_api.settings_update,
        name="admin-settings-update",
    ),
    path("users/", admin_api.user_list, name="admin-user-list"),
    path(
        "users/level/",
        admin_api.user_level_update,
        name="admin-user-level",
    ),
]

health_api_patterns = [
    path("", health.health, name="health"),
]

users_api_patterns = [
    path("me/", users.me_update, name="users-me"),
    path("me/delete/", users.me_delete, name="users-me-delete"),
]

demos_api_patterns = [
    path("heartbeat/", demos_api.heartbeat, name="demos-heartbeat"),
    path("jobs/", demos_api.job_list, name="demos-jobs"),
    path("jobs/run/", demos_api.job_run, name="demos-job-run"),
    path(
        "jobs/run-batch/", demos_api.job_run_batch, name="demos-job-run-batch"
    ),
    path("jobs/<uuid:job_id>/", demos_api.job_delete, name="demos-job-delete"),
    path(
        "jobs/<uuid:job_id>/cancel/",
        demos_api.job_cancel,
        name="demos-job-cancel",
    ),
    path("dockets/", demos_api.docket_search, name="demos-docket-search"),
    path(
        "dockets/facets/",
        demos_api.docket_facet_options,
        name="demos-docket-facets",
    ),
    path(
        "dockets/import/",
        demos_api.docket_import,
        name="demos-docket-import",
    ),
    path("uploads/", demos_api.upload_list, name="demos-upload-list"),
    path(
        "uploads/create/", demos_api.upload_create, name="demos-upload-create"
    ),
    path(
        "uploads/<uuid:upload_id>/",
        demos_api.upload_delete,
        name="demos-upload-delete",
    ),
    path(
        "uploads/<uuid:upload_id>/file/",
        demos_api.upload_file,
        name="demos-upload-file",
    ),
    path(
        "uploads/<uuid:upload_id>/download/",
        demos_api.upload_download,
        name="demos-upload-download",
    ),
    path("auth/public/", demos_api.auth_public, name="demos-auth-public"),
    path(
        "auth/session/", demos_api.auth_session_only, name="demos-auth-session"
    ),
    path("auth/token/", demos_api.auth_token_only, name="demos-auth-token"),
    path(
        "auth/either/",
        demos_api.auth_session_or_token,
        name="demos-auth-either",
    ),
    path(
        "auth/scoped-read/",
        demos_api.auth_scoped_read,
        name="demos-auth-scoped-read",
    ),
    path(
        "auth/scoped-write/",
        demos_api.auth_scoped_write,
        name="demos-auth-scoped-write",
    ),
    path(
        "auth/scoped-both/",
        demos_api.auth_scoped_both,
        name="demos-auth-scoped-both",
    ),
    path("auth/admin/", demos_api.auth_admin_only, name="demos-auth-admin"),
    path(
        "auth/developer/",
        demos_api.auth_developer_scoped,
        name="demos-auth-developer",
    ),
    path("auth/burst/", demos_api.auth_burst, name="demos-auth-burst"),
]

tokens_api_patterns = [
    path("", tokens.token_list, name="tokens-list"),
    path("create/", tokens.token_create, name="tokens-create"),
    path(
        "<uuid:token_id>/revoke/",
        tokens.token_revoke,
        name="tokens-revoke",
    ),
    path(
        "<uuid:token_id>/rotate/",
        tokens.token_rotate,
        name="tokens-rotate",
    ),
]

urlpatterns = [
    *main_view_patterns,
    path("demos/", include(demos_view_patterns)),
    path("admin/", include(admin_view_patterns)),
    *pwa_patterns,
    *oauth_metadata_patterns,
    path("accounts/", include("allauth.urls")),
    path("o/", include((oauth_patterns, "oauth2_provider"))),
    path("api/health/", include(health_api_patterns)),
    path("api/admin/", include(admin_api_patterns)),
    path("api/demos/", include(demos_api_patterns)),
    path("api/tokens/", include(tokens_api_patterns)),
    path("api/users/", include(users_api_patterns)),
    *static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT / "public",
    ),
    *staticfiles_urlpatterns(),
]
