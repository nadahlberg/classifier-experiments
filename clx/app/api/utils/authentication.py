import secrets
from dataclasses import dataclass, field

from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import CsrfViewMiddleware

from clx.app.exceptions import AuthenticationError, PermissionDeniedError
from clx.app.models import ApiToken, User
from clx.app.selectors.api_token import api_token_get
from clx.app.selectors.oauth_token import oauth_token_get
from clx.app.services.api_token import (
    api_token_hash,
    api_token_split,
    api_token_touch,
)

SESSION = "session"
TOKEN = "token"
PUBLIC = "public"

TOKEN_SCHEME = "token"
BEARER_SCHEME = "bearer"


@dataclass(frozen=True)
class Auth:
    user: User
    method: str
    token: ApiToken | None = None
    client: str | None = None
    scopes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_token(self) -> bool:
        """Whether the caller authenticated with a credential, not a session."""
        return self.method == TOKEN


def _unexempt_callback(*args: object, **kwargs: object) -> HttpResponse:
    return HttpResponse()


def _enforce_csrf(request: HttpRequest) -> None:
    check = CsrfViewMiddleware(_unexempt_callback)
    check.process_request(request)
    reason = check.process_view(request, _unexempt_callback, (), {})
    if reason is not None:
        raise PermissionDeniedError("CSRF verification failed")


def authenticate_session(request: HttpRequest) -> Auth | None:
    """Authenticate the session cookie, enforcing CSRF on unsafe methods."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    _enforce_csrf(request)
    return Auth(user=user, method=SESSION)


def _authenticate_api_token(presented: str) -> Auth:
    parts = api_token_split(presented)
    if parts is None:
        raise AuthenticationError("Invalid API token")

    token_id, secret = parts
    token = api_token_get(token_id=token_id)
    if token is None:
        raise AuthenticationError("Invalid API token")
    if not secrets.compare_digest(token.token_hash, api_token_hash(secret)):
        raise AuthenticationError("Invalid API token")
    if token.is_revoked:
        raise AuthenticationError("API token has been revoked")
    if token.is_expired:
        raise AuthenticationError("API token has expired")
    if not token.user.is_active:
        raise AuthenticationError("Invalid API token")

    api_token_touch(token=token)
    return Auth(
        user=token.user,
        method=TOKEN,
        token=token,
        scopes=tuple(token.scopes),
    )


def _authenticate_oauth_token(presented: str) -> Auth:
    if api_token_split(presented) is not None:
        raise AuthenticationError(
            "This is an API token; send it as 'Authorization: Token ...'"
        )

    access = oauth_token_get(token=presented)
    if access is None or not access.is_valid():
        raise AuthenticationError("Invalid bearer token")
    if access.user is None or not access.user.is_active:
        raise AuthenticationError("Invalid bearer token")

    return Auth(
        user=access.user,
        method=TOKEN,
        client=access.application.name if access.application else None,
        scopes=tuple(access.scope.split()),
    )


def authenticate_token(request: HttpRequest) -> Auth | None:
    """Authenticate the Authorization header: Token is an API token, Bearer is OAuth."""
    header = request.headers.get("Authorization", "")
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() == TOKEN_SCHEME:
        return _authenticate_api_token(credentials.strip())
    if scheme.lower() == BEARER_SCHEME:
        return _authenticate_oauth_token(credentials.strip())
    return None


AUTHENTICATORS = {
    SESSION: authenticate_session,
    TOKEN: authenticate_token,
}


def resolve_auth(request: HttpRequest, methods: tuple[str, ...]) -> Auth:
    """Try each allowed method in order and return the first that succeeds."""
    for method in methods:
        auth = AUTHENTICATORS[method](request)
        if auth is not None:
            return auth
    raise AuthenticationError("Authentication required")


def check_scopes(auth: Auth, required: tuple[str, ...]) -> None:
    """Hold a token to its scopes; a session carries the user's full rights."""
    if not required or not auth.is_token:
        return
    missing = set(required) - set(auth.scopes)
    if missing:
        raise PermissionDeniedError(
            f"Token is missing scopes: {', '.join(sorted(missing))}"
        )


def check_perms(auth: Auth, required: tuple[str, ...]) -> None:
    """Hold the caller to the permissions the endpoint declares.

    Unlike scopes, these bind both methods: a permission is a fact about
    the user, not about the credential they arrived with.
    """
    missing = [perm for perm in required if not auth.user.has_perm(perm)]
    if missing:
        raise PermissionDeniedError(
            f"Missing permissions: {', '.join(sorted(missing))}"
        )
