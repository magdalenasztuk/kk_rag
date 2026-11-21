"""Wynik oceny: okresowej (§ 11 rozporządzenia z 2016 r.) i pierwszej (§ 9–10 rozporządzenia z 2015 r.)."""
from __future__ import annotations

from app.domain.scales import overall_level_for


def format_score(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def compute_periodic_result(scores: list[dict]) -> dict:
    missing = [s["criterionId"] for s in scores if s["points"] is None]
    rated = [s for s in scores if s["points"] is not None]
    total = sum(s["points"] for s in rated)
    count = len(rated)
    complete = count > 0 and not missing
    veto = [s["criterionId"] for s in rated if s["points"] == 1]
    if not complete:
        return {"complete": complete, "missing": missing, "count": count, "sum": total,
                "mean": total / count if count else None, "level": None, "outcome": None,
                "vetoCriteria": veto, "onBoundary": False, "explanation": []}
    level = overall_level_for(total, count)
    mean = total / count
    on_boundary = any(total == edge * count for edge in (2, 4, 6, 8))
    outcome = "pozytywna" if level["positiveEligible"] and not veto else "negatywna"
    explanation = [
        f"Średnia arytmetyczna {count} ocen cząstkowych: {total} / {count} = {format_score(mean)}.",
        f"Przedział {level['range']} oznacza poziom „{level['label'].lower()}” (§ 11 ust. 1 pkt 2).",
    ]
    if on_boundary:
        explanation.append(
            f"Wartość {format_score(mean)} jest górną granicą przedziału „{level['label'].lower()}” — "
            "kolejny przedział zaczyna się powyżej tej wartości.")
    if veto:
        explanation.append("Co najmniej jedna ocena cząstkowa wynosi 1 pkt, dlatego ocena jest negatywna "
                           "niezależnie od średniej (§ 11 ust. 1 pkt 4).")
    elif not level["positiveEligible"]:
        explanation.append("Poziom niższy niż „na poziomie oczekiwań” oznacza ocenę negatywną (§ 11 ust. 1 pkt 4).")
    else:
        explanation.append("Poziom co najmniej „na poziomie oczekiwań” i brak oceny 1 pkt oznaczają ocenę "
                           "pozytywną (§ 11 ust. 1 pkt 3).")
    return {"complete": complete, "missing": missing, "count": count, "sum": total, "mean": mean, "level": level,
            "outcome": outcome, "vetoCriteria": veto, "onBoundary": on_boundary, "explanation": explanation}


def compute_first_result(scores: list[dict], exam: str | None, report_on_time: bool | None) -> dict:
    missing = [s["criterionId"] for s in scores if s["points"] is None]
    rated = [s for s in scores if s["points"] is not None]
    total = sum(s["points"] for s in rated)
    count = len(rated)
    scores_complete = count > 0 and not missing
    below = sum(1 for s in rated if s["points"] == 3)
    mean = total / count if count else None
    exam_met = (exam != "niezaliczony") if exam else None
    exam_detail = {
        "zaliczony": "Egzamin zaliczony.",
        "nie-dotyczy": "Obowiązek nie dotyczy pracownika (§ 10 ust. 3).",
        "niezaliczony": "Egzamin niezaliczony — ocena musi być negatywna.",
    }.get(exam or "", "Brak informacji o egzaminie.")
    report_detail = ("Brak informacji o sprawozdaniu." if report_on_time is None
                     else "Sprawozdanie złożono w terminie." if report_on_time
                     else "Sprawozdanie niezłożone albo złożone po terminie.")
    conditions = [
        {"id": "egzamin", "label": "Egzamin kończący służbę przygotowawczą zaliczony albo nie dotyczy",
         "met": exam_met, "detail": exam_detail, "legalRef": "§ 10 ust. 1 pkt 1"},
        {"id": "sprawozdanie", "label": "Sprawozdanie złożone w wyznaczonym terminie",
         "met": report_on_time, "detail": report_detail, "legalRef": "§ 10 ust. 1 pkt 2"},
        {"id": "oceny-3", "label": "Nie więcej niż jedna ocena cząstkowa w wysokości 3 pkt",
         "met": below <= 1 if scores_complete else None,
         "detail": f"Liczba ocen 3 pkt: {below}." if scores_complete else "Uzupełnij oceny wszystkich elementów.",
         "legalRef": "§ 10 ust. 1 pkt 3"},
        {"id": "srednia", "label": "Ocena łączna (średnia ocen cząstkowych) nie niższa niż 5 pkt",
         "met": total >= 5 * count if scores_complete else None,
         "detail": f"Średnia: {format_score(mean)}." if scores_complete and mean is not None
         else "Uzupełnij oceny wszystkich elementów.",
         "legalRef": "§ 10 ust. 1 pkt 4"},
    ]
    any_failed = any(c["met"] is False for c in conditions)
    all_known = all(c["met"] is not None for c in conditions)
    outcome = "negatywna" if any_failed else "pozytywna" if all_known else None
    return {"complete": scores_complete and all_known, "missing": missing, "count": count, "sum": total,
            "mean": mean, "belowCount": below, "conditions": conditions, "outcome": outcome}
