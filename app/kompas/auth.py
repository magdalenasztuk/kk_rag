"""Logowanie login+hasło i tokeny sesji (HMAC) dla kont demonstracyjnych."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone

from app.core.config import settings
from app.kompas import reference as ref
from app.kompas.errors import ApiError

PUBLIC_AUTH_PATHS = frozenset({
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("GET", "/auth/accounts"),
})


def _secret() -> bytes:
    raw = (settings.auth_secret or "").strip() or "kompas-demo-auth-secret"
    return hashlib.sha256(raw.encode()).digest()


def public_user(user: dict) -> dict:
    return {k: v for k, v in user.items() if k != "password"}


def find_by_login(login: str) -> dict | None:
    key = (login or "").strip().lower()
    if not key:
        return None
    return next((u for u in ref.users() if (u.get("login") or "").lower() == key), None)


def account_hints() -> list[dict]:
    return [{"login": u["login"], "fullName": u["fullName"], "jobTitle": u["jobTitle"], "roles": u["roles"],
             "avatarUrl": u.get("avatarUrl")} for u in ref.users() if u.get("login")]


def issue_token(user_id: str) -> tuple[str, str]:
    exp = int(time.time()) + max(1, settings.auth_ttl_hours) * 3600
    payload = f"{user_id}.{exp}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode().rstrip("=")
    expires = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return token, expires


def parse_bearer(header: str | None) -> str | None:
    if not header:
        return None
    kind, _, value = header.partition(" ")
    if kind.lower() != "bearer" or not value.strip():
        return None
    return verify_token(value.strip())


def verify_token(token: str) -> str | None:
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        user_id, exp_s, sig = raw.rsplit(".", 2)
        payload = f"{user_id}.{exp_s}"
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(exp_s) < int(time.time()):
            return None
        ref.user(user_id)  # istnieje
        return user_id
    except (ValueError, TypeError, ApiError):
        return None


def authenticate(login: str, password: str) -> dict:
    user = find_by_login(login)
    if not user or not hmac.compare_digest(user.get("password") or "", password or ""):
        raise ApiError(401, "unauthorized", "Nieprawidłowy login lub hasło.")
    token, expires_at = issue_token(user["id"])
    return {"token": token, "expiresAt": expires_at, "user": public_user(user)}


def unauthorized(message: str = "Wymagane logowanie.") -> ApiError:
    return ApiError(401, "unauthorized", message)
