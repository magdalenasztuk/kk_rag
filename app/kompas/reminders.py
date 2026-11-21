"""Kandydaci do przypomnień — wylicza serwer na podstawie reguł kadr i stanu spraw."""
from __future__ import annotations

from app.domain.dates import describe_due_in, diff_in_days, format_pl
from app.domain.workflow import current_step_id

LOOKAHEAD_DAYS = 31


def _severity(due: str, today: str) -> str:
    days = diff_in_days(due, today)
    if days <= 3:
        return "pilne"
    if days <= 14:
        return "wkrotce"
    return "informacja"


def reminder_candidates(cases: list[dict], rules: list[dict], log: list[dict], today: str) -> list[dict]:
    enabled = {r["id"] for r in rules if r.get("enabled")}
    out: list[dict] = []

    def last_sent(case_id: str, title: str) -> str | None:
        sent = sorted(e["sentAt"] for e in log if e["caseId"] == case_id and e["title"].startswith(title[:12]))
        return sent[-1] if sent else None

    for c in cases:
        if c["status"] == "zakonczona":
            continue
        step = current_step_id(c)
        name = c["employee"]["fullName"]
        d = c["deadlines"]

        def push(rule_id: str, due: str, title: str, message: str) -> None:
            item = {"id": f"{c['id']}:{rule_id}", "ruleId": rule_id, "caseId": c["id"], "employeeName": name,
                    "recipient": c["evaluator"], "dueDate": due, "title": title, "message": message,
                    "severity": _severity(due, today)}
            sent = last_sent(c["id"], title)
            if sent:
                item["lastSentAt"] = sent
            out.append(item)

        preliminary_pending = (step in ("stanowisko", "kryteria", "rozmowa-wstepna") if c["path"] == "periodic"
                               else step == "rozmowa-wstepna")
        if "rozmowa-wstepna" in enabled and preliminary_pending and diff_in_days(d["preliminaryDueDate"], today) <= LOOKAHEAD_DAYS:
            push("rozmowa-wstepna", d["preliminaryDueDate"], f"Rozmowa wstępna do {format_pl(d['preliminaryDueDate'])}",
                 f"{name}: rozmowa i zapoznanie z kryteriami {describe_due_in(d['preliminaryDueDate'], today)}.")
        if ("termin-oceny" in enabled and not preliminary_pending and diff_in_days(d["dueDate"], today) <= LOOKAHEAD_DAYS
                and not c["conclusion"].get("sheetGeneratedAt")):
            push("termin-oceny", d["dueDate"], f"Termin oceny {format_pl(d['dueDate'])}",
                 f"{name}: termin sporządzenia oceny {describe_due_in(d['dueDate'], today)}. Obecny krok: {step}.")
        if "zapoznanie" in enabled and c["conclusion"].get("sheetGeneratedAt") and not c["conclusion"].get("employeeAcknowledgedAt"):
            push("zapoznanie", c["conclusion"].get("draftedAt") or today, "Zapoznanie z oceną",
                 f"{name}: arkusz wygenerowany — zapoznaj ocenianego z oceną niezwłocznie.")
        for extension in d["extensions"]:
            if "zawiadomienie-o-terminie" in enabled and not extension.get("employeeNotifiedAt"):
                push("zawiadomienie-o-terminie", today, "Zawiadomienie o nowym terminie",
                     f"{name}: termin przedłużono o {extension['days']} dni — zawiadom ocenianego pisemnie (§ 8).")
        report_due = (c["preliminary"].get("reportWindow") or {}).get("to")
        if ("sprawozdanie" in enabled and c["path"] == "first" and report_due and c["report"].get("status") != "zlozone"
                and diff_in_days(report_due, today) <= 14):
            push("sprawozdanie", report_due, f"Sprawozdanie do {format_pl(report_due)}",
                 f"{name}: termin złożenia sprawozdania {describe_due_in(report_due, today)}.")
    return sorted(out, key=lambda x: x["dueDate"])
