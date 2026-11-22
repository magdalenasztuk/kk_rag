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
from app.domain.text import collapse_whitespace, fold, truncate
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


def _call(system: str, user: str, max_tokens: int = 1200, *, fast: bool = True,
          schema: dict | None = None) -> dict | None:
    if not settings.llm_available():
        return None
    try:
        raw = generate.complete_text(
            f"{system}\n\n{_RULES}", user, max_tokens=max_tokens, fast=fast, schema=schema)
        data = generate.parse_json_object(raw)
        if data is None:
            log.warning("enrich: model nie zwrócił JSON (długość %s): %s", len(raw or ""), (raw or "")[:500])
        return data
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

PLAN_SYSTEM = """Przygotowujesz przełożonego do rozmowy oceniającej w służbie cywilnej. Piszesz pytania, które może przeczytać na głos.
Zasady języka:
- poprawna, mówiona polszczyzna; przełożony zwraca się do pracownika w drugiej osobie;
- czasowniki: „opowiedz”, „zrobiłeś”, „sprawdziłeś”, „jak to ułożyłeś”, „co powiedziałeś”;
- zakaz strony biernej i bezosobowej: „zrobiono”, „sprawdzono”, „zaplanowano”, „wybrano”, „zastosowano”, „utrzymywano”, „skoordynowano”, „dostosowano”;
- pełne zdania, bez cytowania nazw wskaźników i bez cudzysłowów z tekstu kompetencji;
- zakaz ramek w rodzaju „było widać:”, „w tym rodzaju”, „jak to wygląda u Ciebie na co dzień: «…»”;
- pytanie ma dać się przeczytać na głos i prowadzić do przykładu: co pracownik zrobił, jaki był skutek, co zależało od niego.
Zasady treści:
- obserwacje to jedyne fakty z okresu oceny; opisy kryteriów i zadania stanowiska to oczekiwania, nie zdarzenia, które już zaszły;
- nie pisz „w notatkach pojawiło się” ani „jeśli miałeś związek z…”;
- nie wymyślaj konkretnych ćwiczeń, pism ani konfliktów; jeśli obserwacji nie ma, pytaj o przykład z okresu, bez nazywania zdarzenia, którego nie zapisano;
- gdy jest obserwacja, pierwsze pytanie dotyczy tej sytuacji (data i tytuł), drugie pyta o inny szczegół: skutek, udział innych osób albo co następnym razem;
- gdy obserwacji nie ma, poproś o jeden przykład z okresu oceny, trybem „opowiedz o sytuacji, w której…”; nie zakładaj, że coś konkretnego się wydarzyło;
- dwa pytania na kryterium, każde o czym innym; nie powtarzaj tej samej konstrukcji we wszystkich kryteriach;
- nie wystawiaj ocen i nie sugeruj punktów.
Zwróć JSON:
{"opening": "<2–3 zdania, jak zacząć rozmowę>",
 "items": [{"criterion_id": "<id z listy>", "questions": ["<pytanie 1>", "<pytanie 2>"]}],
 "development_questions": ["<2–3 pytania o rozwój i potrzebne wsparcie>"],
 "closing": "<1–2 zdania, jak zamknąć rozmowę>"}"""

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "opening": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "criterion_id": {"type": "string"},
                    "questions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["criterion_id", "questions"],
            },
        },
        "development_questions": {"type": "array", "items": {"type": "string"}},
        "closing": {"type": "string"},
    },
    "required": ["opening", "items", "development_questions", "closing"],
}


_BAD_QUESTION = (
    "było widać", "w tym rodzaju", "jak to wygląda u ciebie na co dzień:",
    "w notatkach", "miałeś związek",
)
_IMPERSONAL = (
    "zastosowano", "sprawdzono", "zweryfikowano", "zaplanowano", "skoordynowano",
    "dostosowano", "wybrano", "utrzymywano", "ustalano", "zrobiono", "przekazano",
)


def _spoken_questions(raw, banned: list[str]) -> list[str]:
    accepted = []
    for question in _strings(raw, 3, 280):
        low = question.lower()
        if any(bad in low for bad in _BAD_QUESTION) or any(word in low for word in _IMPERSONAL):
            continue
        if any(len(snippet) > 36 and snippet.lower() in low for snippet in banned):
            continue
        if len(question) < 40:
            continue
        accepted.append(question)
    return accepted


def _mentions_observation(question: str, observations: list[dict]) -> bool:
    folded = fold(question)
    for observation in observations:
        for token in fold(observation.get("title") or "").split():
            if len(token) > 3 and token in folded:
                return True
    return False


def conversation_plan(c: dict, generated_at: str) -> dict:
    plan = drafts.build_conversation_plan(c, generated_at)
    skeleton = []
    for item in plan["items"]:
        competency = ref.competency(item["criterionId"]) or {}
        skeleton.append({
            "criterion_id": item["criterionId"],
            "kryterium": criterion_name(item["criterionId"]),
            "znaczenie": [truncate(i["text"], 140) for i in competency.get("indicators", [])[:3]],
            "obserwacje": [f"{f['date']}: {f['text']}" for f in item["facts"]],
            "czego_brakuje": item["gaps"],
        })
    data = _call(
        PLAN_SYSTEM,
        f"KONTEKST SPRAWY:\n{case_context(c)}\n\nKRYTERIA DO PYTAŃ:\n{json.dumps(skeleton, ensure_ascii=False)}",
        4000,
        fast=False,
        schema=PLAN_SCHEMA,
    )
    if not data:
        return plan
    by_id = {str(i.get("criterion_id")): i for i in data.get("items") or [] if isinstance(i, dict)}
    items = []
    for item in plan["items"]:
        competency = ref.competency(item["criterionId"]) or {}
        banned = [i["text"][:80] for i in competency.get("indicators", [])]
        proposed = _spoken_questions((by_id.get(item["criterionId"]) or {}).get("questions"), banned)
        observations = [o for o in c["observations"] if item["criterionId"] in o.get("criterionIds", [])]
        if observations and proposed and not any(_mentions_observation(q, observations) for q in proposed):
            proposed = [item["questions"][0], *proposed]
        items.append({**item, "questions": (proposed or item["questions"])[:3]})
    plan["items"] = items
    opening = collapse_whitespace(str(data.get("opening") or ""))
    closing = collapse_whitespace(str(data.get("closing") or ""))
    if len(opening) > 40 and not any(bad in opening.lower() for bad in _BAD_QUESTION):
        plan["opening"] = truncate(opening, 600)
    if len(closing) > 20 and not any(bad in closing.lower() for bad in _BAD_QUESTION):
        plan["closing"] = truncate(closing, 400)
    plan["developmentQuestions"] = _spoken_questions(data.get("development_questions"), []) or plan["developmentQuestions"]
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
