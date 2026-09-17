import os
from pathlib import Path
from typing import Any

import sentry_sdk
from csp.constants import NONE, SELF
from django.core.management.utils import get_random_secret_key

from clx.app.permissions import API_SCOPES

BASE_DIR = Path(__file__).resolve().parent


def getenv_list(name: str) -> list[str]:
    """Parse a comma-separated environment variable, dropping empties."""
    return [v for v in os.getenv(name, "").split(",") if v]


SECRET_KEY = os.getenv("SECRET_KEY", get_random_secret_key())
DEBUG = os.getenv("DEBUG", "off") == "on"
ALLOWED_HOSTS = getenv_list("ALLOWED_HOSTS")
DOMAIN = os.getenv("DOMAIN", "")


INSTALLED_APPS = [
    "clx.app",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "corsheaders",
    "django_cotton.apps.SimpleAppConfig",
    "django_ratelimit",
    "oauth2_provider",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "clx.app.middleware.ApiErrorMiddleware",
]

CORS_ALLOWED_ORIGINS = getenv_list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = [f"https://{DOMAIN}"] if DOMAIN else []

USE_S3 = os.getenv("USE_S3", "off") == "on"

s3_endpoint = os.getenv("AWS_S3_ENDPOINT_URL", "").rstrip("/")
public_bucket = os.getenv("AWS_PUBLIC_BUCKET", "")
static_sources = (
    [f"{s3_endpoint}/{public_bucket}/"]
    if USE_S3 and s3_endpoint and public_bucket
    else []
)

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [SELF],
        "script-src": [SELF, *static_sources],
        "style-src": [SELF, *static_sources],
        "img-src": [SELF, "blob:", *static_sources],
        "media-src": [SELF, "blob:"],
        "font-src": [SELF],
        "connect-src": [SELF],
        "frame-src": [SELF],
        "worker-src": [SELF],
        "manifest-src": [SELF],
        "object-src": [NONE],
        "base-uri": [SELF],
        "frame-ancestors": [NONE],
    },
}

ROOT_URLCONF = "clx.app.urls"

template_loaders = [
    "django_cotton.cotton_loader.Loader",
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "app" / "templates",
            BASE_DIR / "app" / "template_overrides",
        ],
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "clx.app.context_processors.site_config",
            ],
            "builtins": [
                "django_cotton.templatetags.cotton",
                "clx.app.templatetags.scripts",
            ],
            "loaders": (
                template_loaders
                if DEBUG
                else [
                    (
                        "django.template.loaders.cached.Loader",
                        template_loaders,
                    )
                ]
            ),
        },
    },
]

AUTH_USER_MODEL = "app.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None

LOGIN_REDIRECT_URL = "/demos/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"

OAUTH2_PROVIDER = {
    "PKCE_REQUIRED": True,
    "DCR_ENABLED": True,
    "DCR_REGISTRATION_PERMISSION_CLASSES": (
        "oauth2_provider.dcr.AllowAllDCRPermission",
    ),
    "SCOPES": dict(API_SCOPES),
    "DEFAULT_SCOPES": ["demo:read", "profile:read"],
    "ALLOWED_REDIRECT_URI_SCHEMES": ["https", "http"],
}

DEV_USER_EMAIL = os.getenv("DEV_USER_EMAIL", "")
DEV_USER_PASSWORD = os.getenv("DEV_USER_PASSWORD", "")

POSTMARK_SERVER_TOKEN = os.getenv("POSTMARK_SERVER_TOKEN", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "webmaster@localhost")

if POSTMARK_SERVER_TOKEN:
    EMAIL_BACKEND = "anymail.backends.postmark.EmailBackend"
    ANYMAIL = {"POSTMARK_SERVER_TOKEN": POSTMARK_SERVER_TOKEN}
    ACCOUNT_EMAIL_VERIFICATION = "mandatory"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    ACCOUNT_EMAIL_VERIFICATION = "optional"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "clx"),
        "USER": os.getenv("POSTGRES_USER", "postgres"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "postgres"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
ELASTICSEARCH_INDEX_PREFIX = "search"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

CELERY_BROKER_URL = REDIS_URL
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    "demo-heartbeat": {
        "task": "clx.app.tasks.demo.demo_heartbeat_task",
        "schedule": 30.0,
    },
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR.parent / "media"

if USE_S3:
    s3_defaults = {
        "endpoint_url": os.getenv("AWS_S3_ENDPOINT_URL"),
        "region_name": os.getenv("AWS_S3_REGION_NAME"),
    }
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **s3_defaults,
                "bucket_name": os.environ["AWS_PUBLIC_BUCKET"],
                "default_acl": "public-read",
                "querystring_auth": False,
            },
        },
        "private": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **s3_defaults,
                "bucket_name": os.environ["AWS_PRIVATE_BUCKET"],
                "default_acl": "private",
            },
        },
        "staticfiles": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **s3_defaults,
                "bucket_name": os.environ["AWS_PUBLIC_BUCKET"],
                "location": "static",
                "default_acl": "public-read",
                "querystring_auth": False,
            },
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {
                "location": MEDIA_ROOT / "public",
                "base_url": MEDIA_URL,
            },
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {
                "location": MEDIA_ROOT / "private",
            },
        },
        "staticfiles": {
            "BACKEND": (
                "django.contrib.staticfiles.storage.StaticFilesStorage"
            ),
        },
    }

API_TOKEN_MAX_LIFETIME_DAYS = 90
API_TOKEN_TOUCH_SECONDS = 60
API_RATE_LIMIT_PER_USER = 2000
API_RATE_LIMIT_PER_SESSION = 10000
API_RATE_LIMIT_PER_SCOPE_DEFAULT = 200
API_RATE_LIMIT_PER_SCOPE = {
    "demo:read": 1000,
    "demo:write": 100,
    "profile:read": 500,
}
API_RATE_LIMIT_WINDOW_SECONDS = 3600
API_RATE_LIMIT_FAIL_OPEN = True

RATELIMIT_FAIL_OPEN = API_RATE_LIMIT_FAIL_OPEN
RATELIMIT_CACHE_PREFIX = "api-rl:"
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.W001"]

DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

SENTRY_DSN = os.getenv("SENTRY_DSN", "")
SENTRY_TRACES_SAMPLE_RATE = 1.0

SENTRY_SCRUBBED_HEADERS = {
    "authorization",
    "cookie",
    "idempotency-key",
    "x-csrftoken",
}


def scrub_sentry_event(event: Any, hint: Any) -> Any:
    """Strip credential-bearing headers before an event leaves the process."""
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            for name in list(headers):
                if name.lower() in SENTRY_SCRUBBED_HEADERS:
                    headers[name] = "[Filtered]"
        request.pop("cookies", None)
    return event


if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=True,
        enable_logs=True,
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        before_send=scrub_sentry_event,
        before_send_transaction=scrub_sentry_event,
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
