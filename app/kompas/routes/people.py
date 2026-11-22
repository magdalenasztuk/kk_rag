from __future__ import annotations

import copy

from app.domain.dates import format_pl, is_iso_date
from app.domain.text import fold, new_id
from app.kompas import reference as ref
from app.kompas.access import can_see_case
from app.kompas.cases import compute_deadlines, summarize_case
from app.kompas.errors import bad_request, forbidden
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
    visible = [e for e in ctx.ws.employees() if _can_see_employee(ctx.ws, ctx.user, e)]
    return sorted((_list_item(ctx.ws, e) for e in visible), key=lambda i: _pl_key(i["fullName"]))


def _create_employee(ctx: RouteContext) -> dict:
    body = ctx.json()
    user = ctx.user
    first_name = str(body.get("firstName") or "").strip()
    last_name = str(body.get("lastName") or "").strip()
    if not first_name or not last_name:
        raise bad_request("Podaj imię i nazwisko.")
    position_id = str(body.get("positionId") or "").strip()
    if not position_id:
        raise bad_request("Wybierz stanowisko.")
    position = ref.position(position_id)
    is_hr = "hr" in user["roles"]
    supervisor_id = str(body.get("supervisorId") or "").strip() if is_hr else user["id"]
    if not supervisor_id:
        raise bad_request("Wybierz przełożonego.")
    ref.user(supervisor_id)
    if not is_hr and supervisor_id != user["id"]:
        raise forbidden("Przełożony może dodać tylko osoby do swojego zespołu.")
    status = "urzednik-sc" if body.get("status") == "urzednik-sc" else "pracownik-sc"
    basis = "pierwsza-umowa" if body.get("employmentBasis") == "pierwsza-umowa" else "czas-nieokreslony"
    employed_since = str(body.get("employedSince") or "").strip() or ctx.ws.today
    if not is_iso_date(employed_since):
        raise bad_request("Podaj datę zatrudnienia.")
    employee = {
        "id": new_id("e"),
        "firstName": first_name,
        "lastName": last_name,
        "fullName": f"{first_name} {last_name}",
        "positionId": position["id"],
        "orgUnitId": position["orgUnitId"],
        "supervisorId": supervisor_id,
        "status": status,
        "employment": _employment(basis, employed_since),
        "absences": [],
    }
    saved = ctx.ws.save_employee(employee)
    return _list_item(ctx.ws, saved)


def _contract_end(employed_since: str) -> str:
    year, month, day = employed_since.split("-")
    return f"{int(year) + 1}-{month}-{day}"


def _employment(basis: str, employed_since: str) -> dict:
    employment: dict = {"since": employed_since, "basis": basis}
    if basis == "pierwsza-umowa":
        employment["firstContractEnd"] = _contract_end(employed_since)
    return employment


def _can_edit_employee(user: dict, employee: dict) -> bool:
    return "hr" in user["roles"] or employee["supervisorId"] == user["id"]


def _update_employee(ctx: RouteContext) -> dict:
    employee = copy.deepcopy(ctx.ws.employee(ctx.params["employeeId"]))
    if not _can_edit_employee(ctx.user, employee):
        raise forbidden("Umowę zmieniają kadry albo bezpośredni przełożony.")
    body = ctx.json()
    basis = body.get("employmentBasis")
    if basis not in ("pierwsza-umowa", "czas-nieokreslony"):
        raise bad_request("Wybierz rodzaj umowy.")
    employed_since = str(body.get("employedSince") or "").strip()
    if not is_iso_date(employed_since):
        raise bad_request("Podaj datę zatrudnienia.")
    employee["employment"] = _employment(basis, employed_since)
    saved = ctx.ws.save_employee(employee)
    return _list_item(ctx.ws, saved)


def _employee(ctx: RouteContext) -> dict:
    employee = ctx.ws.employee(ctx.params["employeeId"])
    if not _can_see_employee(ctx.ws, ctx.user, employee):
        raise forbidden("Dane pracownika są dostępne dla przełożonego i kadr.")
    cases = [summarize_case(c, ctx.ws.today) for c in ctx.ws.cases
             if c["employee"]["id"] == employee["id"] and can_see_case(c, ctx.user)]
    return {"employee": _list_item(ctx.ws, employee), "position": ref.position(employee["positionId"]),
            "cases": sorted(cases, key=lambda s: s["dueDate"], reverse=True)}


def _positions(ctx: RouteContext) -> list[dict]:
    user = ctx.user
    is_hr = "hr" in user["roles"]
    positions = ref.reference()["positions"] if is_hr else ref.positions_in_unit(user["orgUnitId"])
    return [{
        "id": p["id"], "code": p["code"], "title": p["title"], "orgUnitId": p["orgUnitId"],
        "orgUnitName": ref.org_unit(p["orgUnitId"])["name"],
    } for p in positions]


def _users(ctx: RouteContext) -> list[dict]:
    role = ctx.query.get("role")
    return [ref.person_ref(u) for u in ref.users() if not role or role in u["roles"]]


def register(router: Router) -> None:
    (router
     .get("/employees", _employees)
     .post("/employees", _create_employee)
     .patch("/employees/:employeeId", _update_employee)
     .get("/employees/:employeeId", _employee)
     .get("/positions", _positions)
     .get("/users", _users))
