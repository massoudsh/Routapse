import hmac

from fastapi import Header, HTTPException

from .config import settings


def _check(expected: str, authorization: str | None):
    if not expected:
        return
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(401, "invalid or missing bearer token")


def admin_auth(authorization: str | None = Header(None)):
    _check(settings.admin_token, authorization)


def gateway_auth(authorization: str | None = Header(None)):
    _check(settings.gateway_key, authorization)
