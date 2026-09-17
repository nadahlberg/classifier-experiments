from oauth2_provider.models import AccessToken, get_access_token_model


def oauth_token_get(*, token: str) -> AccessToken | None:
    """Look up an OAuth access token by its opaque value, owner attached."""
    return (
        get_access_token_model()
        .objects.select_related("user", "application")
        .filter(token=token)
        .first()
    )
