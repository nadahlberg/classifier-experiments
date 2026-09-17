from django.conf import settings
from django.db import models
from django.utils import timezone

from clx.app.models.base import BaseModel

TOKEN_PREFIX = "pat"


class ApiToken(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    name = models.CharField(max_length=100)
    token_id = models.CharField(max_length=32, unique=True, db_index=True)
    token_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_expired(self) -> bool:
        """Whether the token is past its expiry."""
        return self.expires_at <= timezone.now()

    @property
    def is_revoked(self) -> bool:
        """Whether the token has been revoked."""
        return self.revoked_at is not None

    @property
    def is_active(self) -> bool:
        """Whether the token may still authenticate a request."""
        return not self.is_revoked and not self.is_expired
