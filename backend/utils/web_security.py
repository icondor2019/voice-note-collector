from __future__ import annotations

import hmac
import secrets
from typing import Optional

from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from configuration.settings import settings


ACCESS_COOKIE = "vnc_access_token"
REFRESH_COOKIE = "vnc_refresh_token"
CSRF_COOKIE = "vnc_csrf_token"


def cookie_secure() -> bool:
    if settings.WEB_COOKIE_SECURE is not None:
        return settings.WEB_COOKIE_SECURE
    return settings.ENVIRONMENT == "prod"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_csrf_cookie(
    request: Request, response: Response, token: Optional[str] = None
) -> str:
    token = token or request.cookies.get(CSRF_COOKIE) or new_csrf_token()
    response.set_cookie(
        CSRF_COOKIE,
        token,
        secure=cookie_secure(),
        httponly=False,
        samesite="lax",
        path="/",
    )
    return token


def validate_csrf(request: Request, submitted_token: Optional[str]) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE)
    if (
        not cookie_token
        or not submitted_token
        or not hmac.compare_digest(cookie_token, submitted_token)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid request")


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    common = {
        "secure": cookie_secure(),
        "httponly": True,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(ACCESS_COOKIE, access_token, max_age=3600, **common)
    response.set_cookie(REFRESH_COOKIE, refresh_token, max_age=60 * 60 * 24 * 30, **common)


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=cookie_secure(), httponly=True, samesite="lax")
    response.delete_cookie(REFRESH_COOKIE, path="/", secure=cookie_secure(), httponly=True, samesite="lax")


def apply_security_headers(response: Response) -> None:
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        apply_security_headers(response)
        return response
