"""Strażnicy i odpowiedzi awaryjne asystenta (bez modelu językowego).

Strażnicy działają zawsze — także przed wywołaniem Claude: asystent nie wystawia ocen i nie ocenia osobowości.
"""
from __future__ import annotations

import re

from app.domain.text import new_id, normalize
from app.kompas import reference as ref

RULES_MODEL = "Kompas — reguły i baza pytań (tryb offline)"

DECISION_PATTERNS = [re.compile(p) for p in (
    r"\bjaka ocene (mam|powinien|powinna|dac|wystawic|przyznac)",
    r"\bile punktow (mam|powinien|powinna|dac|przyznac)",
    r"\b(ocen|wystaw) (ja|go|ich|jej|mu)\b",
    r"\bczy (ona|on) zasluguje",
)]

PERSONALITY_PATTERNS = [re.compile(p) for p in (
    r"\banaliz\w* (emocj|osobowos)",
    r"\bosobowos",
    r"\b(jaki|jaka) (ma|jest) (charakter|osobowosc)",
    r"\bczy (jest|byl|byla) leniw",
    r"\bstan zdrowia",
    r"\bzdrowi\w* psychiczn",
)]


def app_citation(fragment_id: str) -> dict | None:
    from app.kompas import knowledge
    from app.rag.ingest.app_knowledge import chunk_id
    chunk = knowledge._index().by_id.get(chunk_id(fragment_id))
    return knowledge.citation_for(chunk) if chunk else None


def _base(question: dict, answered_at: str, model: str) -> dict:
    return {"id": new_id("ans"), "question": question["question"], "mode": question["mode"],
            "answeredAt": answered_at, "model": model}


def guard(question: dict, answered_at: str, model: str) -> dict | None:
    """Odpowiedź „poza zakresem”, gdy pytanie dotyczy wystawienia oceny albo cech osoby."""
    text = normalize(question["question"])
    if any(p.search(text) for p in DECISION_PATTERNS):
        return {**_base(question, answered_at, model), "status": "poza-zakresem",
                "answer": "Nie wystawiam ocen — decyzję podejmuje oceniający. Mogę pokazać, jak powstaje sugestia "
                          "narzędzia i które obserwacje ją uzasadniają.",
                "bullets": [], "citations": [c for c in (app_citation("regula-sugestia"), app_citation("r16-p2")) if c],
                "toolRule": True, "followUps": ["Jak liczona jest sugestia?", "Co oznacza „brak podstaw do oceny”?"]}
    if any(p.search(text) for p in PERSONALITY_PATTERNS):
        return {**_base(question, answered_at, model), "status": "poza-zakresem",
                "answer": "Nie analizuję emocji, zdrowia ani cech osobowości. Ocena dotyczy zachowań w pracy opisanych "
                          "w modelu kompetencji — opisz konkretną sytuację, działanie i rezultat.",
                "bullets": [], "citations": [c for c in (app_citation("model-przyklady"),) if c],
                "toolRule": False, "followUps": ["Jak opisać obserwację?"]}
    return None


def _score_intent(intent: dict, question: str, path: str | None) -> float:
    text = normalize(question)
    score = sum(1 for k in intent["keywords"] if normalize(k) in text)
    score += sum(2.5 for p in intent.get("phrases") or [] if normalize(p) in text)
    if path and intent["paths"]:
        effective = "first" if "pierwsz" in text else "periodic" if "okresow" in text else path
        score += 0.75 if effective in intent["paths"] else -2
    return score


def suggested_questions(path: str | None, mode: str) -> list[dict]:
    if mode == "rozmowa":
        texts = ["Jak zacząć rozmowę oceniającą?", "Jak omówić niepełny komunikat w czasie incydentu?",
                 "Jak zapytać o plan rozwoju?", "Co zrobić, gdy pracownik się nie zgadza?"]
    elif path == "first":
        texts = ["Jakie są warunki pozytywnej pierwszej oceny?", "Jaka jest skala w pierwszej ocenie?",
                 "Kogo nie dotyczy egzamin ze służby przygotowawczej?", "Co po pierwszej ocenie?"]
    else:
        texts = ["Ile kryteriów dodatkowych mogę wybrać?", "Kiedy ocena jest negatywna?",
                 "Dlaczego 6,00 to „na poziomie oczekiwań”?", "Jak nieobecność wpływa na termin oceny?",
                 "Jak liczona jest sugestia?"]
    return [{"text": t, "mode": mode} for t in texts]


def intent_pool(mode: str) -> list[dict]:
    data = ref.intents()
    return [*data["conversation"], *data["formal"]] if mode == "rozmowa" else data["formal"]


def match_intent(question: dict) -> tuple[dict | None, float]:
    path = (question.get("context") or {}).get("path")
    ranked = sorted(((i, _score_intent(i, question["question"], path) + (0.5 if i["mode"] == question["mode"] else 0))
                     for i in intent_pool(question["mode"])), key=lambda x: -x[1])
    return ranked[0] if ranked else (None, 0.0)


def answer_missing(question: dict, answered_at: str) -> dict:
    return {**_base(question, answered_at, RULES_MODEL), "status": "brak-zrodla",
            "answer": "W udostępnionych źródłach nie znalazłem odpowiedzi na to pytanie. Nie zgaduję — sprawdź "
                      "w komórce kadr albo zadaj pytanie inaczej.",
            "bullets": ["Przeszukano: rozporządzenia z 2015 i 2016 r., poradniki KPRM, wzory arkuszy i model kompetencji."],
            "citations": [], "toolRule": False,
            "followUps": [s["text"] for s in suggested_questions((question.get("context") or {}).get("path"), question["mode"])[:3]]}


def answer_offline(question: dict, answered_at: str) -> dict:
    guarded = guard(question, answered_at, RULES_MODEL)
    if guarded:
        return guarded
    intent, score = match_intent(question)
    if not intent or score < 2:
        return answer_missing(question, answered_at)
    return answer_from_intent(question, answered_at, intent)


def answer_from_intent(question: dict, answered_at: str, intent: dict) -> dict:
    return {**_base(question, answered_at, RULES_MODEL), "status": "odpowiedz", "answer": intent["answer"],
            "bullets": intent.get("bullets") or [],
            "citations": [c for c in (app_citation(f) for f in intent["fragmentIds"]) if c],
            "toolRule": bool(intent.get("toolRule")), "followUps": intent.get("followUps") or []}
