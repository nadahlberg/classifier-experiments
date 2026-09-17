import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from clx.app.exceptions import ApplicationError
from clx.app.models import TOKEN_PREFIX, ApiToken, User
from clx.app.permissions import API_SCOPES

ID_BYTES = 9
SECRET_BYTES = 32
DEFAULT_LIFETIME_DAYS = 30


@dataclass(frozen=True)
class MintedToken:
    token: ApiToken
    plaintext: str


def api_token_hash(secret: str) -> str:
    """Hash a token secret for storage and comparison."""
    return hashlib.sha256(secret.encode()).hexdigest()


def api_token_split(plaintext: str) -> tuple[str, str] | None:
    """Split a presented token into its lookup id and secret."""
    parts = plaintext.split("_", 2)
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return None
    if not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


@transaction.atomic
def api_token_create(
    *,
    user: User,
    name: str,
    scopes: list[str],
    lifetime_days: int = DEFAULT_LIFETIME_DAYS,
) -> MintedToken:
    """Mint a token, returning the plaintext that is never stored."""
    name = name.strip()
    if not name:
        raise ApplicationError("Token name is required")

    unknown = set(scopes) - set(API_SCOPES)
    if unknown:
        raise ApplicationError(f"Unknown scopes: {', '.join(sorted(unknown))}")

    maximum = settings.API_TOKEN_MAX_LIFETIME_DAYS
    if not 1 <= lifetime_days <= maximum:
        raise ApplicationError(
            f"lifetime_days must be between 1 and {maximum}"
        )

    token_id = secrets.token_hex(ID_BYTES)
    secret = secrets.token_urlsafe(SECRET_BYTES)
    token = ApiToken(
        user=user,
        name=name,
        token_id=token_id,
        token_hash=api_token_hash(secret),
        scopes=sorted(set(scopes)),
        expires_at=timezone.now() + timedelta(days=lifetime_days),
    )
    token.full_clean()
    token.save()
    return MintedToken(
        token=token, plaintext=f"{TOKEN_PREFIX}_{token_id}_{secret}"
    )


def api_token_revoke(*, user: User, token_id: str) -> ApiToken:
    """Revoke a token, keeping the row so its name stays resolvable."""
    token = ApiToken.objects.filter(user=user, id=token_id).first()
    if token is None:
        raise ApplicationError("Token not found")
    if token.is_revoked:
        raise ApplicationError("Token is already revoked")
    token.revoked_at = timezone.now()
    token.full_clean()
    token.save(update_fields=["revoked_at", "updated_at"])
    return token


@transaction.atomic
def api_token_rotate(*, user: User, token_id: str) -> MintedToken:
    """Revoke a token and mint a replacement with the same name and scopes."""
    existing = ApiToken.objects.filter(user=user, id=token_id).first()
    if existing is None:
        raise ApplicationError("Token not found")

    remaining = existing.expires_at - timezone.now()
    lifetime_days = max(
        1, min(remaining.days, settings.API_TOKEN_MAX_LIFETIME_DAYS)
    )
    if not existing.is_revoked:
        existing.revoked_at = timezone.now()
        existing.full_clean()
        existing.save(update_fields=["revoked_at", "updated_at"])

    return api_token_create(
        user=user,
        name=existing.name,
        scopes=list(existing.scopes),
        lifetime_days=lifetime_days,
    )


def api_token_touch(*, token: ApiToken) -> None:
    """Record that a token was used, at most once per touch interval."""
    now = timezone.now()
    interval = timedelta(seconds=settings.API_TOKEN_TOUCH_SECONDS)
    if token.last_used_at and now - token.last_used_at < interval:
        return
    token.last_used_at = now
    ApiToken.objects.filter(pk=token.pk).update(
        last_used_at=now, updated_at=now
    )
