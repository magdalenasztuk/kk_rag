from __future__ import annotations

from app.kompas import auth as auth_mod
from app.kompas.auth import unauthorized
from app.kompas.router import RouteContext, Router
from app.kompas.routes.session import session_info


def _login(ctx: RouteContext) -> dict:
    body = ctx.json()
    result = auth_mod.authenticate(str(body.get("login") or ""), str(body.get("password") or ""))
    ctx.ws.state["sessionUserId"] = result["user"]["id"]
    ctx.ws.touch()
    return result


def _me(ctx: RouteContext) -> dict:
    return session_info(ctx.ws, ctx.user)


def _logout(ctx: RouteContext) -> dict:
    return {"ok": True}


def _accounts(_ctx: RouteContext) -> dict:
    return {"accounts": auth_mod.account_hints()}


def register(router: Router) -> None:
    (router
     .post("/auth/login", _login)
     .post("/auth/logout", _logout)
     .get("/auth/me", _me)
     .get("/auth/accounts", _accounts))
