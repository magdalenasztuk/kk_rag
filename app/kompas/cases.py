"""Tworzenie sprawy, terminy i widok sprawy w listach."""
from __future__ import annotations

from app.domain.dates import diff_in_days, format_pl
from app.domain.deadlines import first_assessment_windows, periodic_due_date, preliminary_meeting_due_date
from app.domain.text import new_id
from app.domain.workflow import case_result, current_step_id, step_label, steps_for


def history_event(at: str, actor: dict, kind: str, summary: str, step_id: str | None = None) -> dict:
    return {"id": new_id("h"), "at": at, "actor": actor, "kind": kind, "summary": summary,
            **({"stepId": step_id} if step_id else {})}


def compute_deadlines(employee: dict, path: str) -> dict:
    if path == "first":
        contract_end = employee["employment"].get("firstContractEnd")
        if not contract_end:
            raise ValueError(f"Pracownik {employee['fullName']} nie ma pierwszej umowy na czas określony.")
        w = first_assessment_windows(employee["employment"]["since"], contract_end)
        return {"dueDate": w["assessmentDeadline"], "baseDueDate": w["assessmentDeadline"],
                "basis": "Najpóźniej miesiąc przed końcem umowy (art. 38 ust. 1 ustawy)", "extensions": [],
                "preliminaryDueDate": w["preliminaryDueDate"], "windowStart": w["earliestReportDate"]}
    previous = employee.get("previousAssessment")
    start = (previous or {}).get("draftedAt") or employee["employment"]["since"]
    due = periodic_due_date(start, employee.get("absences") or [])
    return {
        "dueDate": due["dueDate"],
        "baseDueDate": due["baseDueDate"],
        "basis": (f"24 miesiące od sporządzenia poprzedniej oceny ({format_pl(start)})" if previous
                  else f"24 miesiące od zatrudnienia na czas nieokreślony ({format_pl(start)})"),
        "extensions": [{"days": a["days"], "reason": f"{a['reason']} ({a['from']} – {a['to']})", "from": a["from"],
                        "to": a["to"], "legalBasis": "art. 81 ust. 7 ustawy o służbie cywilnej"}
                       for a in due["extensions"]],
        "preliminaryDueDate": preliminary_meeting_due_date(start, (previous or {}).get("outcome")),
    }


def create_case(*, path: str, employee: dict, position: dict, evaluator: dict, head_of_unit: dict | None,
                org_unit_name: str, created_at: str, created_by: dict) -> dict:
    return {
        "id": new_id("case"),
        "path": path,
        "status": "w-toku",
        "employee": employee,
        "position": position,
        "evaluator": evaluator,
        **({"headOfUnit": head_of_unit} if head_of_unit else {}),
        "orgUnitName": org_unit_name,
        "createdAt": created_at,
        "updatedAt": created_at,
        "steps": {},
        "deadlines": compute_deadlines(employee, path),
        "positionReview": {},
        "criteria": {"additional": [], "rejectedSuggestions": []},
        "preliminary": {"topics": {}, "expectations": [], "goals": [], "notes": ""},
        "preparatoryService": {"note": ""},
        "report": {"summary": {"tasks": "", "problems": "", "skills": "", "improvements": ""}},
        "observations": [],
        "review": {"topics": {}, "notes": "", "employeePerspective": "", "developmentNeeds": ""},
        "ratings": [],
        "conclusion": {"justification": "", "developmentPlan": "", "promotionJustification": ""},
        "documents": [],
        "history": [history_event(created_at, created_by, "utworzenie",
                                  "Uruchomiono pierwszą ocenę." if path == "first" else "Uruchomiono ocenę okresową.")],
    }


def _next_action(c: dict, step_id: str) -> dict:
    if c["status"] == "zakonczona":
        return {"label": "Ocena zakończona"}
    d, k = c["deadlines"], c["conclusion"]
    if c["path"] == "first":
        if step_id == "rozmowa-wstepna":
            return {"label": "Rozmowa wstępna i termin sprawozdania", "due": d["preliminaryDueDate"]}
        if step_id == "sluzba-przygotowawcza":
            return {"label": "Wynik egzaminu ze służby przygotowawczej", "due": d.get("windowStart")}
        if step_id in ("obserwacje", "sprawozdanie"):
            return {"label": "Złożenie sprawozdania", "due": (c["preliminary"].get("reportWindow") or {}).get("to")}
        if step_id == "rozmowa-oceniajaca":
            return {"label": "Rozmowa oceniająca — niezwłocznie po sprawozdaniu", "due": d["dueDate"]}
        return {"label": "Zapoznanie z pierwszą oceną" if k.get("sheetGeneratedAt") else "Pierwsza ocena",
                "due": d["dueDate"]}
    if step_id in ("stanowisko", "kryteria", "rozmowa-wstepna"):
        return {"label": "Rozmowa i zapoznanie z kryteriami (część I)", "due": d["preliminaryDueDate"]}
    if step_id == "obserwacje":
        return {"label": "Zbieranie obserwacji", "due": d["dueDate"]}
    if step_id == "rozmowa-oceniajaca":
        return {"label": "Rozmowa oceniająca", "due": d["dueDate"]}
    if step_id == "ocena":
        return {"label": "Oceny cząstkowe", "due": d["dueDate"]}
    if k.get("sheetGeneratedAt") and not k.get("employeeAcknowledgedAt"):
        return {"label": "Zapoznanie ocenianego z oceną", "due": k.get("draftedAt") or d["dueDate"]}
    return {"label": "Sporządzenie oceny na piśmie", "due": d["dueDate"]}


def _attention(c: dict, action: dict, today: str) -> list[str]:
    if c["status"] == "zakonczona":
        return []
    reasons = []
    if action.get("due"):
        days = diff_in_days(action["due"], today)
        if days < 0:
            reasons.append("po-terminie")
        elif days == 0:
            reasons.append("termin-dzis")
        elif days <= 14:
            reasons.append("termin-bliski")
    if c["conclusion"].get("sheetGeneratedAt") and not c["conclusion"].get("employeeAcknowledgedAt"):
        reasons.append("brak-zapoznania")
    if any(not e.get("employeeNotifiedAt") for e in c["deadlines"]["extensions"]):
        reasons.append("zawiadomienie")
    return reasons


def summarize_case(c: dict, today: str) -> dict:
    steps = steps_for(c["path"])
    step_id = current_step_id(c)
    index = next(i for i, s in enumerate(steps) if s["id"] == step_id)
    action = _next_action(c, step_id)
    result = case_result(c)
    periodic = result.get("periodic")
    first = result.get("first")
    outcome = (periodic or {}).get("outcome") or (first or {}).get("outcome")
    mean = (periodic or {}).get("mean") if periodic else (first or {}).get("mean")
    done = c["status"] == "zakonczona"
    k = c["conclusion"]
    variant = c["positionReview"].get("confirmedVariant")
    summary = {
        "id": c["id"],
        "path": c["path"],
        "status": c["status"],
        **({"formVariant": variant} if variant else {}),
        "employee": {
            "id": c["employee"]["id"],
            "fullName": c["employee"]["fullName"],
            "positionTitle": c["position"]["title"],
            "positionCode": c["position"]["code"],
            "orgUnitCode": " ".join(c["position"]["code"].split(" ")[:-1]),
            "orgUnitName": c["position"]["division"],
            "departmentName": c["position"]["department"],
        },
        "evaluator": c["evaluator"],
        "currentStepId": step_id,
        "currentStepLabel": step_label(c["path"], step_id),
        "stepIndex": len(steps) if done else index + 1,
        "stepCount": len(steps),
        "dueDate": c["deadlines"]["dueDate"],
        "baseDueDate": c["deadlines"]["baseDueDate"],
        "extensions": [{k2: e[k2] for k2 in ("days", "from", "to", "legalBasis")} for e in c["deadlines"]["extensions"]],
        "nextActionLabel": action["label"],
        "attention": _attention(c, action, today),
        "observationsCount": len(c["observations"]),
        "updatedAt": c["updatedAt"],
    }
    if action.get("due"):
        summary["nextActionDue"] = action["due"]
    if outcome and (done or k.get("sheetGeneratedAt")):
        summary["outcome"] = outcome
    if mean is not None and done:
        summary["mean"] = mean
    if periodic and periodic.get("level") and done:
        summary["levelLabel"] = periodic["level"]["label"]
    if k.get("employeeAcknowledgedAt") and done:
        summary["completedAt"] = k["employeeAcknowledgedAt"]
    return summary
