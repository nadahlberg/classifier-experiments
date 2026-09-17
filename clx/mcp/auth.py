from asgiref.sync import sync_to_async
from fastmcp.server.auth import AccessToken, TokenVerifier

from clx.app.selectors.oauth_token import oauth_token_get


class DjangoTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        return await sync_to_async(self._verify)(token)

    def _verify(self, token: str) -> AccessToken | None:
        access = oauth_token_get(token=token)
        if access is None or access.application is None:
            return None
        if not access.is_valid():
            return None

        return AccessToken(
            token=token,
            client_id=access.application.client_id,
            scopes=access.scope.split(),
            expires_at=int(access.expires.timestamp()),
            subject=str(access.user_id),
        )
