from django.db.models import QuerySet

from clx.app.models import ApiToken, User


def api_token_list(*, user: User) -> QuerySet[ApiToken]:
    """List a user's tokens, newest first."""
    return ApiToken.objects.filter(user=user)


def api_token_get(*, token_id: str) -> ApiToken | None:
    """Look up a token by its public id, with the owner attached."""
    return (
        ApiToken.objects.select_related("user")
        .filter(token_id=token_id)
        .first()
    )
