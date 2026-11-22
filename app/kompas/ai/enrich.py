"""Funkcje AI przy sprawie (Claude Haiku): analiza obserwacji, plan rozmowy, szkice uzasadnienia i wniosków IPRZ.

Każda funkcja zaczyna od wyniku deterministycznego (engines) i tylko go uzupełnia. Model nie widzi imion
i nazwisk, nie dostaje prawa do wystawienia oceny, a jego wynik jest walidowany (np. identyfikatory wskaźników).
Przy braku klucza lub błędzie zwracamy wersję deterministyczną.
"""
from __future__ import annotations

import json
import logging

from app.core.config import settings
from app.domain.criteria import criterion_name
from app.domain.text import collapse_whitespace, truncate
from app.domain.workflow import case_criteria, decision_points
from app.domain.scales import points_label
from app.kompas import reference as ref
from app.kompas.ai.context import case_context
from app.kompas.engines import drafts, observation
from app.rag import generate

log = logging.getLogger("kompas.enrich")

_RULES = """Piszesz po polsku, prostym językiem urzędowym, bez markdown. Opierasz się wyłącznie na przekazanych danych — \
nie dopisujesz faktów, dat ani ocen, których w nich nie ma. Nie oceniasz osobowości, emocji ani zdrowia. \
Nie wystawiasz ocen: oceny cząstkowe wybiera oceniający. Pracownika nazywaj „pracownik” albo „osoba oceniana”. \
Zwracasz WYŁĄCZNIE jeden obiekt JSON."""


def _call(system: str, user: str, max_tokens: int = 1200) -> dict | None:
    if not settings.llm_available():
        return None
    try:
        return generate.parse_json_object(generate.complete_text(f"{system}\n\n{_RULES}", user, max_tokens=max_tokens))
    except Exception as exc:  # noqa: BLE001 — wersja deterministyczna wystarcza
        log.warning("enrich call failed: %s", exc)
        return None


def _strings(value, limit: int, max_len: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    return [truncate(collapse_whitespace(str(v)), max_len) for v in value if str(v).strip()][:limit]


# — Analiza obserwacji —

OBSERVATION_SYSTEM = """Pomagasz przełożonemu w służbie cywilnej zapisać obserwację zachowania pracownika tak, żeby była faktem \
(kiedy, co konkretnie zrobił, jaki był skutek), a nie opinią. Dopasowujesz ją do wskaźników behawioralnych modelu kompetencji.
Zwróć JSON:
{"quality": "konkretna" | "do-uzupelnienia" | "ocena-zamiast-faktu",
 "message": "<1–2 zdania informacji zwrotnej dla przełożonego>",
 "missing": [<z: "data", "zachowanie", "rezultat">],
 "flagged_phrases": ["<dosłowne fragmenty notatki, które są opinią/etykietą, nie faktem>"],
 "questions": ["<0–3 pytania, które pomogą uzupełnić notatkę>"],
 "matches": [{"indicator_id": "<id z listy>", "confidence": "wysoka"|"srednia"|"niska", "phrases": ["<dosłowne fragmenty notatki>"]}],
 "title": "<krótki tytuł obserwacji, do 60 znaków>",
 "task_id": "<id zadania z OSP albo null>"}
Dopasuj najwyżej 3 wskaźniki i tylko z podanej listy."""


def analyze_observation(draft: dict, criteria: list[str], tasks: list[dict], analyzed_at: str) -> dict:
    base = observation.analyze_observation(draft, criteria, tasks, analyzed_at)
    description = collapse_whitespace(draft.get("description") or "")
    if len(description) < 15:
        return base
    indicators = {i["id"]: (cid, i["text"]) for cid in criteria for i in (ref.competency(cid) or {}).get("indicators", [])}
    user = json.dumps({
        "notatka": {"data": draft.get("date") or None, "tytul": draft.get("title") or None, "opis": description},
        "wskazniki": [{"id": iid, "kryterium": criterion_name(cid), "opis": text} for iid, (cid, text) in indicators.items()],
        "zadania_OSP": [{"id": t["id"], "opis": truncate(t["text"], 160)} for t in tasks],
    }, ensure_ascii=False)
    data = _call(OBSERVATION_SYSTEM, user, 900)
    if not data:
        return base
    coaching = dict(base["coaching"])
    if data.get("quality") in ("konkretna", "do-uzupelnienia", "ocena-zamiast-faktu") and data.get("message"):
        missing = [m for m in data.get("missing") or [] if m in ("data", "zachowanie", "rezultat")]
        if not draft.get("date") and "data" not in missing:
            missing.insert(0, "data")
        flagged = [p for p in _strings(data.get("flagged_phrases"), 4, 80) if p.lower() in description.lower()]
        coaching = {"quality": data["quality"] if not (missing and data["quality"] == "konkretna") else "do-uzupelnienia",
                    "message": truncate(str(data["message"]), 400), "missing": missing,
                    "flaggedPhrases": flagged or coaching["flaggedPhrases"],
                    "questions": _strings(data.get("questions"), 3, 200)}
    matches = []
    for m in data.get("matches") or []:
        iid = str((m or {}).get("indicator_id") or "")
        if iid in indicators and iid not in {x["indicatorId"] for x in matches}:
            matches.append({"criterionId": indicators[iid][0], "indicatorId": iid,
                            "confidence": m.get("confidence") if m.get("confidence") in ("wysoka", "srednia", "niska") else "srednia",
                            "matchedPhrases": _strings(m.get("phrases"), 3, 80)})
    task_ids = {t["id"] for t in tasks}
    task_id = data.get("task_id") if data.get("task_id") in task_ids else base.get("suggestedTaskId")
    title = (draft.get("title") or "").strip() or truncate(str(data.get("title") or ""), 60).rstrip("…") or base["suggestedTitle"]
    out = {**base, "coaching": coaching, "matches": matches[:3] or base["matches"], "suggestedTitle": title}
    if task_id:
        out["suggestedTaskId"] = task_id
    return out


# — Plan rozmowy —

PLAN_SYSTEM = """Przygotowujesz przełożonego do rozmowy oceniającej. Dostajesz kontekst sprawy, fakty z obserwacji i pytania bazowe.
Każde pytanie ma dotyczyć INNEGO faktu z opisu sytuacji. Nie używaj jednej ramy w rodzaju „Jak oceniasz sytuację… Co zadziałało”.
Gdy ta sama obserwacja wraca przy drugim kryterium, zapytaj o inny szczegół. Przy luce pytaj o brakujący wskaźnik, nie o całe kryterium tym samym zdaniem.
Jeśli nie potrafisz rozróżnić pytań, zwróć pytania_bazowe bez zmian.
Zwróć JSON:
{"opening": "<2–3 zdania otwarcia rozmowy>",
 "items": [{"criterion_id": "<id>", "questions": ["<2–3 różne pytania otwarte>"]}],
 "development_questions": ["<3 pytania o rozwój i wsparcie>"],
 "closing": "<1–2 zdania zamknięcia>"}"""


def _uniform_questions(questions: list[str]) -> bool:
    """Model czasem wstawia wszystkie pytania w to samo zdanie — wtedy zostawiamy pytania bazowe."""
    if len(questions) < 3:
        return False
    openings = [collapse_whitespace(question)[:42] for question in questions]
    return len(set(openings)) <= max(1, len(openings) // 2)


def conversation_plan(c: dict, generated_at: str) -> dict:
    plan = drafts.build_conversation_plan(c, generated_at)
    skeleton = [{"criterion_id": i["criterionId"], "kryterium": criterion_name(i["criterionId"]),
                 "fakty": [f"{f['date']}: {f['text']}" for f in i["facts"]], "luki": i["gaps"],
                 "pytania_bazowe": i["questions"]} for i in plan["items"]]
    data = _call(PLAN_SYSTEM, f"KONTEKST SPRAWY:\n{case_context(c)}\n\nSZKIELET:\n{json.dumps(skeleton, ensure_ascii=False)}", 1600)
    if not data:
        return plan
    questions = {str(i.get("criterion_id")): _strings(i.get("questions"), 3, 260) for i in data.get("items") or [] if isinstance(i, dict)}
    proposed = [{**i, "questions": questions.get(i["criterionId"]) or i["questions"]} for i in plan["items"]]
    flat = [question for item in proposed for question in item["questions"]]
    if not _uniform_questions(flat):
        plan["items"] = proposed
    if data.get("opening"):
        plan["opening"] = truncate(collapse_whitespace(str(data["opening"])), 600)
    if data.get("closing"):
        plan["closing"] = truncate(collapse_whitespace(str(data["closing"])), 400)
    plan["developmentQuestions"] = _strings(data.get("development_questions"), 4, 260) or plan["developmentQuestions"]
    return plan


# — Szkice uzasadnienia i wniosków IPRZ —

DRAFT_SYSTEM = """Piszesz SZKIC tekstu do arkusza oceny w służbie cywilnej, który oceniający przeczyta i poprawi. \
Tekst ma się opierać na decyzjach oceniającego (oceny cząstkowe) i konkretnych obserwacjach z datami. \
Zwróć JSON: {"text": "<szkic>"}"""


def _decisions(c: dict) -> list[str]:
    out = []
    for cid in case_criteria(c):
        points = decision_points(c, cid)
        out.append(f"{criterion_name(cid)}: {f'{points} pkt — {points_label(points)}' if points is not None else 'brak decyzji'}")
    return out


def justification(c: dict, generated_at: str) -> dict:
    base = drafts.draft_justification(c, generated_at)
    user = (f"KONTEKST SPRAWY:\n{case_context(c)}\n\nDECYZJE OCENIAJĄCEGO:\n" + "\n".join(_decisions(c))
            + f"\n\nSZKIC BAZOWY (popraw styl, dodaj przykłady z obserwacji):\n{base['text']}\n\n"
              "Napisz uzasadnienie oceny (4–7 zdań): mocne strony z przykładami, obszary do poprawy z przykładami, "
              "odniesienie do wyniku. Nie zmieniaj ocen. Oznacz [do uzupełnienia] miejsca, gdzie brakuje faktów.")
    data = _call(DRAFT_SYSTEM, user, 1200)
    text = collapse_whitespace(str((data or {}).get("text") or ""))
    return {**base, "text": text, "basedOn": [*base["basedOn"], "Szkic: Claude (do weryfikacji)"]} if len(text) > 80 else base


def development_plan(c: dict, generated_at: str) -> dict:
    base = drafts.draft_development_plan(c, generated_at)
    areas = [criterion_name(a) for a in drafts.development_areas(c)]
    user = (f"KONTEKST SPRAWY:\n{case_context(c)}\n\nDECYZJE OCENIAJĄCEGO:\n" + "\n".join(_decisions(c))
            + f"\n\nOBSZARY DO ROZWOJU: {', '.join(areas) or 'brak wskazanych — skup się na potrzebach z rozmowy'}\n\n"
              "Napisz wnioski do indywidualnego programu rozwoju zawodowego (IPRZ): 3–5 krótkich punktów w osobnych "
              "liniach (cel rozwojowy, forma — szkolenie/mentoring/zadanie rozwojowe, termin przeglądu). Odnieś się do "
              "zadań z opisu stanowiska i potrzeb zgłoszonych przez pracownika.")
    data = _call(DRAFT_SYSTEM, user, 900)
    text = str((data or {}).get("text") or "").strip()
    return {**base, "text": text, "basedOn": [*base["basedOn"], "Szkic: Claude (do weryfikacji)"]} if len(text) > 60 else base
