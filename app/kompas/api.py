"""Warstwa HTTP aplikacji Kompas Kompetencji (`/api/...`) — kontrakt REST oczekiwany przez front Angular."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from app.kompas import auth as auth_mod
from app.kompas import reference as ref
from app.kompas.auth import PUBLIC_AUTH_PATHS, unauthorized
from app.kompas.errors import ApiError
from app.kompas.router import RouteContext, Router
from app.kompas.routes import auth, cases, knowledge, notifications, people, recruitment, session
from app.kompas.store import get_store
from app.kompas.workspace import DEFAULT_WORKSPACE, Workspace, valid_workspace_id

log = logging.getLogger("kompas.api")

WORKSPACE_HEADER = "x-kompas-workspace"
WORKSPACE_COOKIE = "kompas_ws"

app_router = Router()
for module in (auth, session, knowledge, cases, people, notifications, recruitment):
    module.register(app_router)

router = APIRouter()


def _workspace_id(request: Request) -> str:
    return (valid_workspace_id(request.headers.get(WORKSPACE_HEADER))
            or valid_workspace_id(request.cookies.get(WORKSPACE_COOKIE))
            or DEFAULT_WORKSPACE)


def _error(status: int, body: dict) -> JSONResponse:
    return JSONResponse(body, status_code=status)


def handle(method: str, path: str, query: dict[str, str], body, workspace_id: str,
           authorization: str | None = None, *, require_auth: bool = True):
    route_path = "/" + path.strip("/")
    matched = app_router.match(method, route_path)
    if not matched:
        raise ApiError(404, "not-found", f"Brak endpointu {method} {route_path}.")
    route, params = matched
    public = (method.upper(), route_path) in PUBLIC_AUTH_PATHS
    user_id = auth_mod.parse_bearer(authorization)
    if require_auth and not public and not user_id:
        raise unauthorized()

    ws = Workspace(workspace_id, get_store())
    if user_id:
        # Nie zapisuj tu całego stanu. Równoległy odczyt ze starym sessionUserId
        # nadpisywałby właśnie dodanego pracownika albo sprawę.
        user = ref.user(user_id)
    else:
        # Publiczne trasy (login / lista kont) — kontekst użytkownika workspace tylko pomocniczo.
        user = ws.session_user()

    result = route.handler(RouteContext(params=params, query=query, body=body, ws=ws, user=user))
    ws.commit()
    return result


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def dispatch(path: str, request: Request) -> Response:
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        return _error(400, {"code": "bad-request", "message": "Nieprawidłowy JSON w treści żądania."})
    try:
        result = await run_in_threadpool(
            handle, request.method, "/" + path.strip("/"), dict(request.query_params), body,
            _workspace_id(request), request.headers.get("authorization"),
        )
    except ApiError as e:
        return _error(e.status, e.body)
    except Exception:  # noqa: BLE001
        log.exception("unhandled error in %s /%s", request.method, path)
        return _error(500, {"code": "internal", "message": "Wewnętrzny błąd serwera."})
    return Response(json.dumps(result, ensure_ascii=False), media_type="application/json")
