"""Ścieżki oceny, warunki ukończenia kroków i wynik sprawy.

Te same reguły stosuje front (podpowiedzi w UI) i backend (twarde blokady API).
"""
from __future__ import annotations

from app.domain.criteria import MAX_ADDITIONAL_CRITERIA, mandatory_criteria_for
from app.domain.dates import add_months, diff_in_days, is_after, is_before
from app.domain.result import compute_first_result, compute_periodic_result


def _step(id_, label, legal_ref):
    return {"id": id_, "label": label, "legalRef": legal_ref}


PERIODIC_STEPS = [
    _step("stanowisko", "Stanowisko i OSP", "§ 3 rozporządzenia z 2016 r."),
    _step("kryteria", "Kryteria", "§ 4–5 rozporządzenia z 2016 r."),
    _step("rozmowa-wstepna", "Rozmowa wstępna", "§ 5–7 rozporządzenia z 2016 r."),
    _step("obserwacje", "Obserwacje", "Poradnik KPRM, rozdz. 6.2.3"),
    _step("rozmowa-oceniajaca", "Rozmowa oceniająca", "§ 10 rozporządzenia z 2016 r."),
    _step("ocena", "Ocena kompetencji", "§ 11 ust. 1 pkt 1 rozporządzenia z 2016 r."),
    _step("podsumowanie", "Część II i dokument", "§ 11–12 rozporządzenia z 2016 r."),
]

FIRST_STEPS = [
    _step("rozmowa-wstepna", "Rozmowa wstępna", "§ 3–4 rozporządzenia z 2015 r."),
    _step("sluzba-przygotowawcza", "Służba przygotowawcza", "§ 2 pkt 2 i § 10 ust. 3 rozporządzenia z 2015 r."),
    _step("obserwacje", "Obserwacje", "§ 2 pkt 1 rozporządzenia z 2015 r."),
    _step("sprawozdanie", "Sprawozdanie", "§ 4–6 rozporządzenia z 2015 r."),
    _step("rozmowa-oceniajaca", "Rozmowa oceniająca", "§ 7–8 rozporządzenia z 2015 r."),
    _step("ocena", "Ocena elementów", "§ 9 rozporządzenia z 2015 r."),
    _step("podsumowanie", "Pierwsza ocena", "§ 10–11 rozporządzenia z 2015 r."),
]


def steps_for(path: str) -> list[dict]:
    return FIRST_STEPS if path == "first" else PERIODIC_STEPS


def step_definition(path: str, step_id: str) -> dict | None:
    return next((s for s in steps_for(path) if s["id"] == step_id), None)


def step_label(path: str, step_id: str) -> str:
    s = step_definition(path, step_id)
    return s["label"] if s else step_id


def _topic(id_, label, legal_ref, optional=False):
    return {"id": id_, "label": label, "legalRef": legal_ref, "optional": optional}


PERIODIC_PRELIMINARY_TOPICS = [
    _topic("obowiazki", "Główne obowiązki wynikające z opisu stanowiska pracy", "§ 5 ust. 1 pkt 1"),
    _topic("kryteria", "Kryteria obowiązkowe i dodatkowe", "§ 5 ust. 1 pkt 2"),
    _topic("oczekiwania", "Oczekiwania co do sposobu spełniania kryteriów", "§ 5 ust. 1 pkt 3"),
    _topic("cele", "Cele na okres oceny — jeżeli ich określenie jest uzasadnione", "§ 5 ust. 1 pkt 4", True),
]

FIRST_PRELIMINARY_TOPICS = [
    _topic("sposob-oceny", "Sposób dokonywania pierwszej oceny", "§ 3 pkt 1"),
    _topic("obowiazki", "Główne obowiązki z opisu stanowiska i oczekiwania co do ich wykonywania", "§ 3 pkt 2"),
    _topic("postawa", "Oczekiwania co do postawy, zaangażowania, postępów, relacji i terminowości", "§ 3 pkt 3"),
    _topic("sprawozdanie", "Termin złożenia sprawozdania", "§ 3 pkt 4"),
]

PERIODIC_REVIEW_TOPICS = [
    _topic("obowiazki", "Główne obowiązki w okresie oceny i sposób ich realizacji, z uwzględnieniem kryteriów", "§ 10 pkt 1"),
    _topic("cele", "Sposób realizowania wyznaczonych celów", "§ 10 pkt 2", True),
    _topic("rozwoj", "Kierunki dalszego rozwoju zawodowego i potrzeby w zakresie kwalifikacji", "§ 10 pkt 3"),
]

FIRST_REVIEW_TOPICS = [
    _topic("elementy", "Postawa, zaangażowanie, postępy, relacje i terminowość (elementy oceny)", "§ 7 pkt 1 w zw. z § 2"),
    _topic("egzamin", "Wynik egzaminu ze służby przygotowawczej", "§ 2 pkt 2"),
    _topic("sprawozdanie", "Sprawozdanie ocenianego", "§ 2 pkt 3"),
    _topic("rozwoj", "Kierunki dalszego rozwoju zawodowego i potrzeby ocenianego", "§ 7 pkt 1", True),
]


def review_topics_for(path: str) -> list[dict]:
    return FIRST_REVIEW_TOPICS if path == "first" else PERIODIC_REVIEW_TOPICS


def topics_complete(definitions: list[dict], topics: dict) -> bool:
    return all(
        topics.get(t["id"]) == "omowiono" or (t["optional"] and topics.get(t["id"]) == "nie-dotyczy")
        for t in definitions
    )


def case_criteria(c: dict) -> list[str]:
    mandatory = mandatory_criteria_for(c["path"], c["positionReview"].get("confirmedVariant"))
    return list(mandatory) if c["path"] == "first" else [*mandatory, *c["criteria"]["additional"]]


def rating_for(c: dict, criterion_id: str) -> dict | None:
    return next((r for r in c["ratings"] if r["criterionId"] == criterion_id), None)


def decision_points(c: dict, criterion_id: str) -> int | None:
    rating = rating_for(c, criterion_id)
    return (rating.get("decision") or {}).get("points") if rating else None


def report_on_time(c: dict) -> bool | None:
    report = c["report"]
    if report.get("status") == "niezlozone":
        return False
    if report.get("status") != "zlozone" or not report.get("submittedAt"):
        return None
    deadline = (c["preliminary"].get("reportWindow") or {}).get("to")
    return not is_after(report["submittedAt"], deadline) if deadline else None


def case_result(c: dict) -> dict:
    scores = [{"criterionId": cid, "points": decision_points(c, cid)} for cid in case_criteria(c)]
    if c["path"] == "first":
        return {"path": "first",
                "first": compute_first_result(scores, c["preparatoryService"].get("outcome"), report_on_time(c))}
    return {"path": "periodic", "periodic": compute_periodic_result(scores)}


def case_outcome(c: dict) -> str | None:
    r = case_result(c)
    return r["first"]["outcome"] if r["path"] == "first" else r["periodic"]["outcome"]


def case_mean(c: dict) -> float | None:
    r = case_result(c)
    return r["first"]["mean"] if r["path"] == "first" else r["periodic"]["mean"]


# — Walidacja kroków —

def _error(message: str, field: str | None = None) -> dict:
    return {"severity": "error", "message": message, **({"field": field} if field else {})}


def _warning(message: str) -> dict:
    return {"severity": "warning", "message": message}


def _blank(value) -> bool:
    return not (value or "").strip()


def validate_step(c: dict, step_id: str) -> list[dict]:
    return {
        "stanowisko": _validate_position,
        "kryteria": _validate_criteria,
        "rozmowa-wstepna": _validate_first_preliminary if c["path"] == "first" else _validate_periodic_preliminary,
        "sluzba-przygotowawcza": _validate_preparatory_service,
        "obserwacje": _validate_observations,
        "sprawozdanie": _validate_report,
        "rozmowa-oceniajaca": _validate_review,
        "ocena": _validate_ratings,
        "podsumowanie": _validate_conclusion,
    }[step_id](c)


def blocking_issues(issues: list[dict]) -> list[dict]:
    return [i for i in issues if i["severity"] == "error"]


def _validate_position(c: dict) -> list[dict]:
    review = c["positionReview"]
    analysis = review.get("analysis")
    if not review.get("confirmedVariant"):
        return [_error("Potwierdź arkusz oceny (B albo C).")]
    if analysis and review["confirmedVariant"] != analysis.get("recommendedVariant") and _blank(review.get("overrideReason")):
        return [_error("Wybrano inny arkusz niż wynika z OSP — wpisz uzasadnienie odstępstwa.")]
    return []


def _validate_criteria(c: dict) -> list[dict]:
    issues = []
    additional = c["criteria"]["additional"]
    if len(additional) > MAX_ADDITIONAL_CRITERIA:
        issues.append(_error(f"Wybierz najwyżej {MAX_ADDITIONAL_CRITERIA} kryteria dodatkowe (§ 5 ust. 2)."))
    if not additional:
        issues.append(_warning("Nie wybrano kryteriów dodatkowych — to dopuszczalne, ale sprawdź charakter zadań z OSP."))
    return issues


def _validate_periodic_preliminary(c: dict) -> list[dict]:
    issues = []
    p = c["preliminary"]
    if not p.get("meetingDate"):
        issues.append(_error("Podaj datę rozmowy wstępnej.", "podpis"))
    if not topics_complete(PERIODIC_PRELIMINARY_TOPICS, p.get("topics") or {}):
        issues.append(_error("Potwierdź omówienie wszystkich tematów z § 5 ust. 1."))
    expectations = p.get("expectations") or []
    missing = [cid for cid in case_criteria(c)
               if _blank(next((e.get("text") for e in expectations if e.get("criterionId") == cid), ""))]
    if missing:
        issues.append(_error(f"Opisz oczekiwania dla wszystkich kryteriów (brakuje: {len(missing)})."))
    if (p.get("topics") or {}).get("cele") == "omowiono" and not [g for g in p.get("goals") or [] if not _blank(g.get("text"))]:
        issues.append(_error("Zaznaczono omówienie celów — dodaj co najmniej jeden cel."))
    if not p.get("assessmentDueDate"):
        issues.append(_error("Podaj termin sporządzenia oceny na piśmie."))
    elif is_after(p["assessmentDueDate"], c["deadlines"]["dueDate"]):
        issues.append(_error("Termin oceny nie może być późniejszy niż termin ustawowy."))
    if not p.get("employeeAcknowledgedAt"):
        issues.append(_error("Odnotuj datę zapoznania ocenianego z kryteriami (podpis części I).", "podpis"))
    if p.get("meetingDate") and is_after(p["meetingDate"], c["deadlines"]["preliminaryDueDate"]):
        issues.append(_warning("Rozmowa odbyła się po terminie z § 7 — odnotuj przyczynę w notatce."))
    return issues


def _validate_first_preliminary(c: dict) -> list[dict]:
    issues = []
    p = c["preliminary"]
    d = c["deadlines"]
    if not p.get("meetingDate"):
        issues.append(_error("Podaj datę rozmowy wstępnej.", "podpis"))
    if not topics_complete(FIRST_PRELIMINARY_TOPICS, p.get("topics") or {}):
        issues.append(_error("Potwierdź omówienie wszystkich tematów z § 3."))
    window = p.get("reportWindow") or {}
    start, end = window.get("from"), window.get("to")
    if not start or not end:
        issues.append(_error("Wyznacz termin złożenia sprawozdania (data początkowa i końcowa)."))
    else:
        if is_after(start, end):
            issues.append(_error("Data początkowa terminu sprawozdania jest późniejsza niż końcowa."))
        if d.get("windowStart") and is_before(start, d["windowStart"]):
            issues.append(_error("Termin sprawozdania musi przypadać po upływie 8 miesięcy od zatrudnienia (§ 4 ust. 1)."))
        if is_after(end, d["dueDate"]):
            issues.append(_error("Ocena musi nastąpić najpóźniej miesiąc przed końcem umowy — skróć termin sprawozdania."))
    if not p.get("employeeAcknowledgedAt"):
        issues.append(_error("Odnotuj podpis ocenianego potwierdzający rozmowę i termin sprawozdania (§ 4 ust. 3).", "podpis"))
    if p.get("meetingDate") and is_after(p["meetingDate"], d["preliminaryDueDate"]):
        issues.append(_warning("Rozmowa wstępna po terminie 21 dni z § 3."))
    return issues


def _validate_preparatory_service(c: dict) -> list[dict]:
    s = c["preparatoryService"]
    if not s.get("outcome"):
        return [_error("Wybierz wynik egzaminu albo „nie dotyczy”.")]
    if s["outcome"] == "nie-dotyczy" and not s.get("exemption"):
        return [_error("Wskaż podstawę zwolnienia z egzaminu (§ 10 ust. 3).")]
    if s["outcome"] != "nie-dotyczy" and not s.get("examDate"):
        return [_error("Podaj datę egzaminu.")]
    if s["outcome"] == "niezaliczony":
        return [_warning("Niezaliczony egzamin oznacza negatywną pierwszą ocenę (§ 10 ust. 1 pkt 1).")]
    return []


def _validate_observations(c: dict) -> list[dict]:
    criteria = case_criteria(c)
    covered = {cid for o in c["observations"] for cid in o["criterionIds"]}
    uncovered = [cid for cid in criteria if cid not in covered]
    if not c["observations"]:
        return [_warning("Brak obserwacji. Ocena oparta na faktach wymaga przykładów z okresu oceny.")]
    if uncovered:
        return [_warning(f"{len(uncovered)} z {len(criteria)} kryteriów nie ma jeszcze obserwacji — brak obserwacji "
                         "nie obniża oceny, ale warto o nie zapytać w rozmowie.")]
    return []


def _validate_report(c: dict) -> list[dict]:
    r = c["report"]
    issues = []
    if not r.get("status"):
        return [_error("Odnotuj, czy sprawozdanie zostało złożone.")]
    if r["status"] == "zlozone":
        if not r.get("submittedAt"):
            issues.append(_error("Podaj datę złożenia sprawozdania."))
        coverage = r.get("coverage") or {}
        if coverage.get("from") and coverage.get("to") and is_before(coverage["to"], add_months(coverage["from"], 7)):
            issues.append(_warning("Sprawozdanie powinno obejmować co najmniej 7 miesięcy pracy (§ 6 ust. 1)."))
    if report_on_time(c) is False:
        issues.append(_warning("Sprawozdanie niezłożone w terminie — warunek z § 10 ust. 1 pkt 2 nie jest spełniony."))
    return issues


def _validate_review(c: dict) -> list[dict]:
    issues = []
    r = c["review"]
    if not r.get("meetingDate"):
        issues.append(_error("Podaj datę rozmowy oceniającej."))
    if not topics_complete(review_topics_for(c["path"]), r.get("topics") or {}):
        issues.append(_error("Potwierdź omówienie wymaganych tematów rozmowy."))
    if _blank(r.get("notes")):
        issues.append(_error("Zapisz najważniejsze ustalenia z rozmowy."))
    if c["path"] == "first" and c["report"].get("submittedAt") and r.get("meetingDate"):
        if diff_in_days(r["meetingDate"], c["report"]["submittedAt"]) > 14:
            issues.append(_warning("Rozmowa powinna odbyć się niezwłocznie po złożeniu sprawozdania (§ 8 ust. 1)."))
    return issues


def _validate_ratings(c: dict) -> list[dict]:
    issues = []
    criteria = case_criteria(c)
    missing = [cid for cid in criteria if not (rating_for(c, cid) or {}).get("decision")]
    if missing:
        issues.append(_error(f"Brakuje {len(missing)} z {len(criteria)} ocen cząstkowych."))

    def deviates_without_rationale(cid: str) -> bool:
        d = (rating_for(c, cid) or {}).get("decision")
        return bool(d and d.get("suggestedPoints") is not None and d["points"] != d["suggestedPoints"]
                    and _blank(d.get("rationale")))

    if any(deviates_without_rationale(cid) for cid in criteria):
        issues.append(_error("Uzasadnij oceny, które różnią się od sugestii narzędzia."))
    return issues


def _validate_conclusion(c: dict) -> list[dict]:
    issues = []
    outcome = case_outcome(c)
    k = c["conclusion"]
    if outcome is None:
        issues.append(_error("Wynik oceny jest niepełny — uzupełnij poprzednie kroki."))
    if outcome == "negatywna" and _blank(k.get("justification")):
        issues.append(_error("Ocena negatywna wymaga uzasadnienia."))
    if c["path"] == "periodic":
        if _blank(k.get("developmentPlan")):
            issues.append(_error("Wpisz wnioski dotyczące indywidualnego programu rozwoju zawodowego (§ 11 ust. 1 pkt 5)."))
        if c["employee"].get("status") == "urzednik-sc" and outcome == "pozytywna" and not k.get("promotionRequest"):
            issues.append(_error("Zdecyduj o wniosku o kolejny stopień służbowy (część III)."))
        if k.get("promotionRequest") == "tak" and _blank(k.get("promotionJustification")):
            issues.append(_error("Wniosek o kolejny stopień wymaga uzasadnienia."))
    elif not k.get("headOfUnitConfirmedAt"):
        issues.append(_error("Odnotuj potwierdzenie kierującego komórką organizacyjną."))
    if not k.get("draftedAt"):
        issues.append(_error("Podaj datę sporządzenia oceny na piśmie."))
    if not k.get("sheetGeneratedAt"):
        issues.append(_error("Wygeneruj arkusz do podpisu."))
    if not k.get("employeeAcknowledgedAt"):
        issues.append(_error("Odnotuj datę zapoznania ocenianego z oceną."))
    return issues


def current_step_id(c: dict) -> str:
    steps = steps_for(c["path"])
    return next((s["id"] for s in steps if not (c["steps"].get(s["id"]) or {}).get("completedAt")), steps[-1]["id"])


def is_step_completed(c: dict, step_id: str) -> bool:
    return bool((c["steps"].get(step_id) or {}).get("completedAt"))


def is_step_reachable(c: dict, step_id: str) -> bool:
    ids = [s["id"] for s in steps_for(c["path"])]
    if step_id not in ids:
        return False
    return all(is_step_completed(c, sid) for sid in ids[: ids.index(step_id)])
