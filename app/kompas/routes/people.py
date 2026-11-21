from __future__ import annotations

from app.domain.dates import format_pl
from app.domain.text import fold
from app.kompas import reference as ref
from app.kompas.access import can_see_case
from app.kompas.cases import compute_deadlines, summarize_case
from app.kompas.errors import forbidden
from app.kompas.router import RouteContext, Router
from app.kompas.workspace import Workspace


def _can_see_employee(ws: Workspace, user: dict, employee: dict) -> bool:
    return ("hr" in user["roles"] or employee["supervisorId"] == user["id"]
            or any(c["employee"]["id"] == employee["id"] and (c.get("headOfUnit") or {}).get("id") == user["id"]
                   for c in ws.cases))


def _list_item(ws: Workspace, employee: dict) -> dict:
    position = ref.position(employee["positionId"])
    unit = ref.org_unit(employee["orgUnitId"])
    active = next((c for c in ws.cases if c["employee"]["id"] == employee["id"] and c["status"] == "w-toku"), None)
    summary = summarize_case(active, ws.today) if active else None
    path = "first" if employee["employment"]["basis"] == "pierwsza-umowa" else "periodic"
    next_start = None if active else compute_deadlines(employee, path)["preliminaryDueDate"]
    item = {
        "id": employee["id"], "fullName": employee["fullName"], "positionTitle": position["title"],
        "positionCode": position["code"], "orgUnitCode": unit["code"], "orgUnitName": unit["name"],
        "supervisor": ref.person_ref(ref.user(employee["supervisorId"])), "status": employee["status"],
        "employedSince": employee["employment"]["since"], "suggestedPath": path,
    }
    if employee.get("previousAssessment"):
        item["previousAssessment"] = employee["previousAssessment"]
    if active:
        item["activeCaseId"] = active["id"]
    if summary:
        item["nextAction"] = {"label": summary["nextActionLabel"],
                              **({"dueDate": summary["nextActionDue"]} if summary.get("nextActionDue") else {})}
    elif next_start:
        item["nextAction"] = {"label": f"Uruchom nowy cykl — część I do {format_pl(next_start)}", "dueDate": next_start}
    return item


def _pl_key(name: str) -> str:
    return fold(name).lower()


def _employees(ctx: RouteContext) -> list[dict]:
    visible = [e for e in ref.employees() if _can_see_employee(ctx.ws, ctx.user, e)]
    return sorted((_list_item(ctx.ws, e) for e in visible), key=lambda i: _pl_key(i["fullName"]))


def _employee(ctx: RouteContext) -> dict:
    employee = ref.employee(ctx.params["employeeId"])
    if not _can_see_employee(ctx.ws, ctx.user, employee):
        raise forbidden("Dane pracownika są dostępne dla przełożonego i kadr.")
    cases = [summarize_case(c, ctx.ws.today) for c in ctx.ws.cases
             if c["employee"]["id"] == employee["id"] and can_see_case(c, ctx.user)]
    return {"employee": _list_item(ctx.ws, employee), "position": ref.position(employee["positionId"]),
            "cases": sorted(cases, key=lambda s: s["dueDate"], reverse=True)}


def _users(ctx: RouteContext) -> list[dict]:
    role = ctx.query.get("role")
    return [ref.person_ref(u) for u in ref.users() if not role or role in u["roles"]]


def register(router: Router) -> None:
    (router
     .get("/employees", _employees)
     .get("/employees/:employeeId", _employee)
     .get("/users", _users))
