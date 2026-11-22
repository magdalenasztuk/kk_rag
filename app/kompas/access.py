"""Uprawnienia do sprawy: oceniający edytuje, kierujący komórką czyta, kadry widzą przebieg bez treści."""
from __future__ import annotations

import copy
import re

from app.kompas.errors import forbidden

_SHEET_OVERRIDE = "Zatwierdzono inny arkusz niż wynika z opisu stanowiska."
_SCORE_DEVIATION = "Ocena cząstkowa inna niż sugestia narzędzia. Uzasadnienie zostaje u oceniającego."
_SUGGESTION = re.compile(r"sugest", re.I)
_POINTS = re.compile(r"(\d+)\s*pkt")

CASE_FORBIDDEN = "Ta ocena jest dostępna tylko dla oceniającego, kierującego komórką i kadr."


def case_access(c: dict, user: dict) -> dict | None:
    if c["evaluator"]["id"] == user["id"]:
        return {"role": "oceniajacy", "canEdit": c["status"] == "w-toku", "redacted": False}
    if (c.get("headOfUnit") or {}).get("id") == user["id"]:
        return {"role": "kierujacy", "canEdit": False, "redacted": False}
    if "hr" in user["roles"]:
        return {"role": "kadry", "canEdit": False, "redacted": True}
    return None


def can_see_case(c: dict, user: dict) -> bool:
    return case_access(c, user) is not None


def history_summary_for_hr(event: dict) -> str:
    """Ta sama reguła co `historySummaryForHr` na froncie. Idempotentna."""
    summary = event.get("summary") or ""
    kind = event.get("kind")
    if kind == "obserwacja":
        if summary in ("Dodano obserwację.", "Usunięto obserwację."):
            return summary
        return "Usunięto obserwację." if summary.startswith("Usunięto") else "Dodano obserwację."
    if kind == "odstepstwo":
        if summary in (_SHEET_OVERRIDE, _SCORE_DEVIATION):
            return summary
        return _SHEET_OVERRIDE if "wbrew rekomendacji" in summary else _SCORE_DEVIATION
    if kind == "decyzja" and _SUGGESTION.search(summary):
        score = _POINTS.search(summary)
        return f"Zapisano ocenę cząstkową {score.group(1)} pkt." if score else "Zapisano ocenę cząstkową."
    return summary


def present_case(c: dict, user: dict) -> dict:
    """Kadry prowadzą proces. Obserwacje i notatki zostają u oceniającego.

    Oczekiwania i cele widać po podpisie części I, uzasadnienie i wnioski — po zapoznaniu z oceną.
    """
    access = case_access(c, user)
    if not access:
        raise forbidden(CASE_FORBIDDEN)
    view = copy.deepcopy(c)
    view["access"] = access
    if not access["redacted"]:
        return view
    preliminary = view["preliminary"]
    part_one_in_file = bool(preliminary.get("employeeAcknowledgedAt"))
    sheet_in_file = bool(view["conclusion"].get("employeeAcknowledgedAt"))
    view["observations"] = []
    preliminary["notes"] = ""
    if not part_one_in_file:
        preliminary["expectations"] = []
        preliminary["goals"] = []
    view["review"].update(notes="", employeePerspective="", developmentNeeds="")
    position = view.get("positionReview")
    if isinstance(position, dict):
        position.pop("overrideReason", None)
    for rating in view["ratings"]:
        rating["indicators"] = []
        if rating.get("decision"):
            rating["decision"]["rationale"] = ""
    if not sheet_in_file:
        conclusion = view["conclusion"]
        conclusion["justification"] = ""
        conclusion["developmentPlan"] = ""
        conclusion["promotionJustification"] = ""
        conclusion.pop("justificationAiDraft", None)
        conclusion.pop("promotionRequest", None)
    view["history"] = [{**event, "summary": history_summary_for_hr(event)} for event in view["history"]]
    return view


def require_editor(c: dict, user: dict) -> None:
    access = case_access(c, user)
    if not access:
        raise forbidden()
    if not access["canEdit"]:
        raise forbidden("Ocena jest zakończona — dane są tylko do odczytu." if c["status"] == "zakonczona"
                        else "Zmiany w ocenie wprowadza oceniający. Masz dostęp tylko do odczytu.")


def require_hr(user: dict) -> None:
    if "hr" not in user["roles"]:
        raise forbidden("Ta funkcja jest dostępna dla kadr.")
