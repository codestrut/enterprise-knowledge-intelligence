"""Short-lived HMAC access tokens tied to an existing refresh-session family."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from uuid import UUID

from src.auth.service import AuthenticatedPrincipal


ACCESS_TOKEN_SECRET_ENV = "EKIP_ACCESS_TOKEN_SECRET"
ACCESS_TOKEN_TTL = timedelta(minutes=10)
_ISSUER = "ekip"
_TOKEN_PART_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class AccessTokenError(ValueError):
    """Invalid or expired access token without echoing token contents."""


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    membership_id: UUID
    organisation_id: UUID
    family_id: UUID
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class IssuedAccessToken:
    token: str
    expires_at: datetime


def _secret(secret: str | bytes | None = None) -> bytes:
    value = secret if secret is not None else os.environ.get(ACCESS_TOKEN_SECRET_ENV)
    if isinstance(value, str):
        value = value.encode("utf-8")
    if not isinstance(value, bytes) or len(value) < 32:
        raise RuntimeError(f"{ACCESS_TOKEN_SECRET_ENV} must contain at least 32 bytes.")
    return value


def validate_signing_key_configuration() -> None:
    """Raise RuntimeError unless the configured signing key is usable; never echoes the key."""
    _secret()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    if not _TOKEN_PART_RE.fullmatch(value):
        raise AccessTokenError("Invalid access token.")
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError):
        raise AccessTokenError("Invalid access token.") from None


def issue_access_token(
    principal: AuthenticatedPrincipal,
    family_id: UUID,
    *,
    secret: str | bytes | None = None,
    now: datetime | None = None,
) -> IssuedAccessToken:
    current = datetime.now(UTC) if now is None else now
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Access token timestamps must be timezone-aware.")
    current = current.astimezone(UTC)
    expiry = current + ACCESS_TOKEN_TTL
    payload = {
        "exp": int(expiry.timestamp()),
        "family": str(family_id),
        "iat": int(current.timestamp()),
        "iss": _ISSUER,
        "membership": str(principal.membership_id),
        "org": str(principal.organisation_id),
        "sub": str(principal.user_id),
        "typ": "access",
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(_secret(secret), body.encode("ascii"), hashlib.sha256).digest()
    return IssuedAccessToken(f"{body}.{_b64encode(signature)}", expiry)


def decode_access_token(
    token: object,
    *,
    secret: str | bytes | None = None,
    now: datetime | None = None,
) -> AccessTokenClaims:
    if not isinstance(token, str) or len(token) > 2048 or token.count(".") != 1:
        raise AccessTokenError("Invalid access token.")
    body, encoded_signature = token.split(".", 1)
    if not _TOKEN_PART_RE.fullmatch(body):
        raise AccessTokenError("Invalid access token.")
    raw_signature = _b64decode(encoded_signature)
    expected = hmac.new(_secret(secret), body.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(raw_signature, expected):
        raise AccessTokenError("Invalid access token.")
    try:
        payload = json.loads(_b64decode(body))
        if not isinstance(payload, dict) or set(payload) != {
            "exp", "family", "iat", "iss", "membership", "org", "sub", "typ"
        }:
            raise ValueError
        if payload["iss"] != _ISSUER or payload["typ"] != "access":
            raise ValueError
        if type(payload["exp"]) is not int or type(payload["iat"]) is not int:
            raise ValueError
        claims = AccessTokenClaims(
            user_id=UUID(payload["sub"]),
            membership_id=UUID(payload["membership"]),
            organisation_id=UUID(payload["org"]),
            family_id=UUID(payload["family"]),
            issued_at=datetime.fromtimestamp(payload["iat"], UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise AccessTokenError("Invalid access token.") from None
    current = datetime.now(UTC) if now is None else now
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Access token timestamps must be timezone-aware.")
    current = current.astimezone(UTC)
    if claims.issued_at > current + timedelta(seconds=60) or claims.expires_at <= current:
        raise AccessTokenError("Invalid or expired access token.")
    if claims.expires_at - claims.issued_at > ACCESS_TOKEN_TTL + timedelta(seconds=1):
        raise AccessTokenError("Invalid access token.")
    return claims
