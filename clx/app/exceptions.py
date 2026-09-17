from typing import Any


class ApplicationError(Exception):
    def __init__(
        self, message: str, extra: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra or {}


class AuthenticationError(ApplicationError):
    status_code = 401


class PermissionDeniedError(ApplicationError):
    status_code = 403


class RateLimitError(ApplicationError):
    status_code = 429

    def __init__(
        self,
        message: str,
        extra: dict[str, Any] | None = None,
        retry_after: int = 0,
    ) -> None:
        super().__init__(message, extra)
        self.retry_after = retry_after
