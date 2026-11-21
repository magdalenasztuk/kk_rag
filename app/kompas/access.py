"""Uprawnienia do sprawy: oceniający edytuje, kierujący komórką czyta, kadry widzą przebieg bez treści."""
from __future__ import annotations

import copy

from app.kompas.errors import forbidden

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


def present_case(c: dict, user: dict) -> dict:
    """Widok sprawy dla konkretnej osoby. Kadry nie widzą treści obserwacji, zaznaczeń ani notatek z rozmów."""
    access = case_access(c, user)
    if not access:
        raise forbidden(CASE_FORBIDDEN)
    view = copy.deepcopy(c)
    view["access"] = access
    if not access["redacted"]:
        return view
    view["observations"] = []
    view["preliminary"]["notes"] = ""
    view["review"].update(notes="", employeePerspective="", developmentNeeds="")
    for rating in view["ratings"]:
        rating["indicators"] = []
        if rating.get("decision"):
            rating["decision"]["rationale"] = ""
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
