from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from loguru import logger
from supabase import create_async_client
from supabase.lib.client_options import AsyncClientOptions

from configuration.settings import settings


@dataclass(frozen=True)
class WebSession:
    email: str
    access_token: str
    refresh_token: str
    refreshed: bool = False


class WebAuthError(Exception):
    pass


class WebAuthService:
    @staticmethod
    def _local_bypass_enabled() -> bool:
        """Allow UI preview only when explicitly enabled outside production."""
        return bool(settings.WEB_AUTH_DISABLED) and settings.ENVIRONMENT.casefold() not in {
            "prod",
            "production",
        }

    async def _client(self) -> Any:
        if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
            raise WebAuthError("Web authentication is not configured")
        options = AsyncClientOptions(auto_refresh_token=False, persist_session=False)
        return await create_async_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_ANON_KEY,
            options=options,
        )

    @staticmethod
    def _allowed(email: Optional[str]) -> bool:
        allowed = (settings.WEB_ALLOWED_EMAIL or "").strip().casefold()
        return bool(allowed and email and email.strip().casefold() == allowed)

    async def sign_in(self, email: str, password: str) -> WebSession:
        if self._local_bypass_enabled():
            logger.warning("web.auth.local_bypass.enabled")
            return WebSession(
                email=email.strip() or "local-preview@example.com",
                access_token="local-preview-access",
                refresh_token="local-preview-refresh",
            )
        try:
            client = await self._client()
            auth = await client.auth.sign_in_with_password(
                {"email": email.strip(), "password": password}
            )
            user = auth.user
            session = auth.session
            if not user or not session or not self._allowed(user.email):
                if session:
                    await client.auth.sign_out()
                raise WebAuthError("Invalid credentials")
            return WebSession(
                email=user.email or email,
                access_token=session.access_token,
                refresh_token=session.refresh_token,
            )
        except WebAuthError as exc:
            logger.warning("web.auth.sign_in.rejected reason={}", str(exc)[:240])
            raise
        except Exception as exc:
            logger.warning(
                "web.auth.sign_in.failed error_type={} error_message={}",
                type(exc).__name__,
                str(exc)[:240],
            )
            raise WebAuthError("Invalid credentials") from exc

    async def validate_session(
        self, access_token: Optional[str], refresh_token: Optional[str]
    ) -> WebSession:
        if self._local_bypass_enabled():
            if access_token == "local-preview-access" and refresh_token == "local-preview-refresh":
                return WebSession(
                    email=settings.WEB_ALLOWED_EMAIL or "local-preview@example.com",
                    access_token=access_token,
                    refresh_token=refresh_token,
                )
            raise WebAuthError("Authentication required")
        if not access_token or not refresh_token:
            raise WebAuthError("Authentication required")
        client = await self._client()
        try:
            response = await client.auth.get_user(access_token)
            user = response.user if response else None
            if not user or not self._allowed(user.email):
                raise WebAuthError("Authentication required")
            return WebSession(user.email or "", access_token, refresh_token)
        except WebAuthError:
            raise
        except Exception:
            try:
                refreshed = await client.auth.refresh_session(refresh_token)
                user = refreshed.user
                session = refreshed.session
                if not user or not session or not self._allowed(user.email):
                    raise WebAuthError("Authentication required")
                return WebSession(
                    user.email or "",
                    session.access_token,
                    session.refresh_token,
                    refreshed=True,
                )
            except WebAuthError:
                raise
            except Exception as exc:
                raise WebAuthError("Authentication required") from exc

    async def sign_out(self, access_token: Optional[str], refresh_token: Optional[str]) -> None:
        if not access_token or not refresh_token:
            return
        try:
            client = await self._client()
            await client.auth.set_session(access_token, refresh_token)
            await client.auth.sign_out()
        except Exception:
            logger.warning("web.auth.sign_out.remote_failed")
