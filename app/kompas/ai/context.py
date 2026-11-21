"""Kontekst sprawy przekazywany do modelu — bez imion i nazwisk (oceniany = „pracownik”)."""
from __future__ import annotations

from app.domain import workflow
from app.domain.criteria import criterion_name
from app.domain.text import truncate

MAX_CONTEXT = 5000


def _rating_line(c: dict, criterion_id: str) -> str:
    rating = workflow.rating_for(c, criterion_id)
    if not rating:
        return ""
    levels = [str(i["level"]) for i in rating.get("indicators", []) if i.get("level") and not i.get("noBasis")]
    decision = rating.get("decision") or {}
    parts = []
    if levels:
        parts.append(f"zaznaczone poziomy zachowań: {', '.join(levels)}")
    if decision.get("points") is not None:
        parts.append(f"decyzja oceniającego: {decision['points']} pkt")
    return "; ".join(parts)


def case_context(c: dict, step_id: str | None = None) -> str:
    path_label = "pierwsza ocena" if c["path"] == "first" else "ocena okresowa"
    variant = (c.get("positionReview") or {}).get("confirmedVariant")
    lines = [
        f"Ścieżka: {path_label}{f', arkusz {variant}' if variant else ''}. Stanowisko pracownika: {c['position']['title']} "
        f"({c.get('orgUnitName', '')}).",
        f"Bieżący krok: {workflow.step_label(c['path'], step_id or workflow.current_step_id(c))}. "
        f"Termin oceny: {(c.get('deadlines') or {}).get('dueDate', 'nieustalony')}.",
    ]
    tasks = {t["id"]: t["text"] for t in c["position"].get("tasks", [])}
    criteria = workflow.case_criteria(c)
    if criteria:
        lines.append("Kryteria oceny:")
        for cid in criteria:
            rating = _rating_line(c, cid)
            lines.append(f"- {criterion_name(cid)} ({cid}){f' — {rating}' if rating else ''}")
    expectations = (c.get("preliminary") or {}).get("expectations") or []
    if expectations:
        lines.append("Oczekiwania z rozmowy wstępnej:")
        lines += [f"- {criterion_name(e['criterionId'])}: {truncate(e['text'], 160)}" for e in expectations[:8]]
    observations = sorted(c.get("observations") or [], key=lambda o: o["date"])
    if observations:
        lines.append("Obserwacje (fakty zapisane przez oceniającego):")
        for o in observations[-12:]:
            names = ", ".join(criterion_name(cid) for cid in o.get("criterionIds", []))
            task = tasks.get(o.get("positionTaskId") or "")
            lines.append(f"- {o['date']} „{o.get('title', '')}”: {truncate(o['description'], 220)}"
                         f"{f' [kryteria: {names}]' if names else ''}{f' [zadanie OSP: {truncate(task, 80)}]' if task else ''}")
    review = c.get("review") or {}
    for key, label in (("notes", "Notatki z rozmowy oceniającej"), ("employeePerspective", "Perspektywa pracownika"),
                       ("developmentNeeds", "Potrzeby rozwojowe")):
        if review.get(key):
            lines.append(f"{label}: {truncate(review[key], 300)}")
    text = "\n".join(lines)
    return text[:MAX_CONTEXT]
