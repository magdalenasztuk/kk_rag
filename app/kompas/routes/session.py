from __future__ import annotations

from app.domain.dates import plural_pl
from app.kompas import reference as ref
from app.kompas.auth import public_user
from app.kompas.router import RouteContext, Router
from app.kompas.workspace import Workspace


def _root_unit(unit: dict) -> dict:
    while unit.get("parentId"):
        unit = ref.org_unit(unit["parentId"])
    return unit


def session_info(ws: Workspace, user: dict) -> dict:
    org_unit = ref.org_unit(user["orgUnitId"])
    return {"user": public_user(user), "orgUnit": org_unit, "office": _root_unit(org_unit), "today": ws.today}


def _account_hint(ws: Workspace, user: dict) -> str:
    if "hr" in user["roles"]:
        return "Kadry · wszystkie procesy, terminy i przypomnienia"
    active = [c for c in ws.cases if c["status"] == "w-toku"]
    as_evaluator = sum(1 for c in active if c["evaluator"]["id"] == user["id"])
    as_head = sum(1 for c in active if (c.get("headOfUnit") or {}).get("id") == user["id"])
    parts = []
    if as_evaluator:
        parts.append(f"Oceniający · {as_evaluator} {plural_pl(as_evaluator, ('ocena', 'oceny', 'ocen'))} w toku")
    if as_head:
        parts.append(f"Kierujący komórką · {as_head} "
                     f"{plural_pl(as_head, ('pierwsza ocena', 'pierwsze oceny', 'pierwszych ocen'))}")
    return " · ".join(parts) or "Przełożony"


def _demo_info(ws: Workspace) -> dict:
    return {
        "scenarioId": ws.state["scenarioId"],
        "today": ws.today,
        "scenarios": [],
        "accounts": [{"id": u["id"], "fullName": u["fullName"], "jobTitle": u["jobTitle"], "roles": u["roles"],
                      "hint": _account_hint(ws, u)} for u in ref.users()],
    }


def _reset(ctx: RouteContext) -> dict:
    ctx.ws.reset("demo")
    return {"landing": "/"}


def register(router: Router) -> None:
    (router
     .get("/session", lambda ctx: session_info(ctx.ws, ctx.user))
     .get("/demo", lambda ctx: _demo_info(ctx.ws))
     .post("/demo/reset", _reset))
