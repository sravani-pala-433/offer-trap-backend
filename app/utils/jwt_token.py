import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.settings import settings


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/admin/token")


class InvalidTokenError(ValueError):
    pass


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _secret() -> bytes:
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY is not configured")
    secret = settings.secret_key.get_secret_value()
    if len(secret) < 32:
        raise RuntimeError("SECRET_KEY must contain at least 32 characters")
    return secret.encode("utf-8")


def create_access_token(username: str) -> tuple[str, int]:
    issued_at = int(time.time())
    expires_at = issued_at + settings.access_token_expire_minutes * 60
    header = _base64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _base64url(
        json.dumps(
            {"sub": username, "role": "admin", "iat": issued_at, "exp": expires_at},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _base64url(hmac.new(_secret(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}", expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(_decode_base64url(header_part))
        if not isinstance(header, dict) or header.get("alg") != "HS256" or header.get("typ") != "JWT":
            raise InvalidTokenError("Unsupported token algorithm")

        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected_signature = _base64url(
            hmac.new(_secret(), signing_input, hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature_part, expected_signature):
            raise InvalidTokenError("Invalid token signature")

        payload = json.loads(_decode_base64url(payload_part))
        if not isinstance(payload, dict):
            raise InvalidTokenError("Invalid token payload")
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise InvalidTokenError("Token has expired")
        if payload.get("role") != "admin" or not payload.get("sub"):
            raise InvalidTokenError("Invalid admin token")
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise InvalidTokenError("Invalid token") from error


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def get_current_admin(token: str = Depends(oauth2_scheme)) -> str:
    try:
        username = str(decode_access_token(token)["sub"])
        if not settings.admin_username or not hmac.compare_digest(
            username.encode("utf-8"), settings.admin_username.encode("utf-8")
        ):
            raise InvalidTokenError("Administrator account has changed")
        return username
    except (InvalidTokenError, RuntimeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired administrator session.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
