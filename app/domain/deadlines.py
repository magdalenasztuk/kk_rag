"""Terminy z ustawy o służbie cywilnej, rozporządzeń i poradników KPRM (art. 111–112 KC)."""
from __future__ import annotations

from app.domain.dates import add_days, add_months, days_inclusive, is_after

PERIODIC_INTERVAL_MONTHS = 24
PRELIMINARY_MEETING_DAYS = 30
PRELIMINARY_AFTER_NEGATIVE_DAYS = 7
REASSESSMENT_AFTER_NEGATIVE_MONTHS = 6
OBJECTION_DAYS = 7
FIRST_PRELIMINARY_DAYS = 21
FIRST_REPORT_AFTER_MONTHS = 8


def qualifying_absences(absences: list[dict]) -> list[dict]:
    """Art. 81 ust. 7 ustawy: usprawiedliwiona nieobecność dłuższa niż miesiąc przedłuża termin o jej czas."""
    return [{**a, "days": days_inclusive(a["from"], a["to"])}
            for a in absences if is_after(a["to"], add_months(a["from"], 1))]


def periodic_due_date(start: str, absences: list[dict] | None = None) -> dict:
    base = add_months(start, PERIODIC_INTERVAL_MONTHS)
    extensions = [a for a in qualifying_absences(absences or [])
                  if not is_after(a["from"], base) and is_after(a["to"], start)]
    days = sum(a["days"] for a in extensions)
    return {"baseDueDate": base, "dueDate": add_days(base, days), "extensionDays": days, "extensions": extensions}


def preliminary_meeting_due_date(start: str, previous_outcome: str | None = None) -> str:
    return add_days(start, PRELIMINARY_AFTER_NEGATIVE_DAYS if previous_outcome == "negatywna" else PRELIMINARY_MEETING_DAYS)


def objection_deadline(acknowledged_at: str) -> str:
    """Art. 83 ust. 1 ustawy: sprzeciw do dyrektora generalnego w ciągu 7 dni od zapoznania."""
    return add_days(acknowledged_at, OBJECTION_DAYS)


def first_assessment_windows(employed_since: str, contract_end: str) -> dict:
    return {
        "preliminaryDueDate": add_days(employed_since, FIRST_PRELIMINARY_DAYS),
        "earliestReportDate": add_months(employed_since, FIRST_REPORT_AFTER_MONTHS),
        "assessmentDeadline": add_months(contract_end, -1),
    }
