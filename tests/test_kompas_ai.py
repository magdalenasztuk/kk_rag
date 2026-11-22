"""Asystent i funkcje AI z podstawionym modelem: cytowania, numeracja, odmowa, walidacja, tryb awaryjny."""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("KOMPAS_DENSE_ENABLED", "false")
os.environ.setdefault("KOMPAS_USE_RERANKER", "false")

from app.core.config import settings  # noqa: E402
from app.kompas import reference as ref  # noqa: E402
from app.kompas.ai import assistant, enrich  # noqa: E402
from app.kompas.workspace import seeded_state  # noqa: E402
from app.rag import generate  # noqa: E402

NOW = "2026-11-21T10:00:00.000Z"


@pytest.fixture
def llm(monkeypatch):
    """Podstawiony model: zwraca kolejne odpowiedzi z listy i zapisuje prompty."""
    calls: list[dict] = []
    replies: list = []

    def fake(model, system, messages, max_tokens, json_mode=False):
        calls.append({"model": model, "system": system, "messages": messages})
        reply = replies.pop(0) if replies else "{}"
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(generate, "_complete", fake)
    return calls, replies


def _case(case_id: str) -> dict:
    return next(c for c in seeded_state()["cases"] if c["id"] == case_id)


def test_formal_answer_maps_and_renumbers_citations(llm):
    calls, replies = llm
    replies += [
        {"question": "Ile kryteriów dodatkowych można wybrać w ocenie okresowej?", "queries": ["kryteria dodatkowe liczba"]},
        {"answer": "Możesz wybrać najwyżej 3 kryteria dodatkowe [3].", "bullets": ["Wybór jest dobrowolny [1]."],
         "citations": [3, 1], "abstained": False, "tool_rule": False, "follow_ups": ["Jak wybrać kryteria?"]},
    ]
    answer = assistant.ask({"question": "Ile kryteriów dodatkowych?", "mode": "formalny"}, NOW)
    assert answer["status"] == "odpowiedz"
    assert answer["answer"] == "Możesz wybrać najwyżej 3 kryteria dodatkowe [1]."
    assert answer["bullets"] == ["Wybór jest dobrowolny [2]."]
    assert [c["label"].split("]")[0] for c in answer["citations"]] == ["[1", "[2"]
    assert all(c["fragmentId"] and c["quote"] for c in answer["citations"])
    assert "BM25" in answer["model"]
    # Zapytanie do wyszukiwarki i odpowiedź idą do różnych modeli (Haiku / Sonnet).
    assert calls[0]["model"] == settings.resolved_fast_model()
    assert calls[1]["model"] == settings.resolved_answer_model()
    assert "FRAGMENTY ŹRÓDEŁ" in calls[1]["messages"][-1]["content"]


def test_abstain_returns_missing_source(llm):
    _, replies = llm
    replies += [{"question": "Ile wynosi dodatek stażowy?", "queries": []},
                {"answer": "W dostępnych dokumentach nie znalazłem tej informacji.", "bullets": [], "citations": [],
                 "abstained": True, "follow_ups": []}]
    answer = assistant.ask({"question": "Ile wynosi dodatek stażowy?", "mode": "formalny"}, NOW)
    assert answer["status"] == "brak-zrodla"
    assert answer["citations"] == []


def test_guard_never_calls_model(llm):
    calls, _ = llm
    answer = assistant.ask({"question": "Jaką ocenę mam wystawić Annie?", "mode": "formalny"}, NOW)
    assert answer["status"] == "poza-zakresem"
    assert calls == []


def test_model_failure_falls_back_to_offline_answers(llm):
    _, replies = llm
    replies += [RuntimeError("timeout"), RuntimeError("timeout")]
    answer = assistant.ask({"question": "Ile kryteriów dodatkowych mogę wybrać?", "mode": "formalny"}, NOW)
    assert answer["status"] == "odpowiedz"
    assert answer["model"].endswith("(tryb offline)")
    assert assistant.status()["lastError"]["error"].startswith("RuntimeError")


def test_formal_answer_without_citations_is_rejected(llm):
    _, replies = llm
    replies += [{"question": "Kiedy ocena jest negatywna?", "queries": []},
                {"answer": "Gdy średnia jest niska.", "bullets": [], "citations": [], "abstained": False}]
    answer = assistant.ask({"question": "Kiedy ocena jest negatywna?", "mode": "formalny"}, NOW)
    assert answer["model"].endswith("(tryb offline)")


def test_conversation_mode_gets_pseudonymised_case_context(llm):
    calls, replies = llm
    replies += [{"question": "Jak omówić incydent?", "queries": []},
                {"answer": "Zacznij od faktów z obserwacji [1].", "bullets": ["Zapytaj o przebieg."], "citations": [1],
                 "abstained": False, "follow_ups": []}]
    case = _case("case-anna")
    answer = assistant.ask({"question": "Jak omówić incydent?", "mode": "rozmowa",
                            "context": {"caseId": "case-anna", "path": "periodic"},
                            "history": [{"role": "user", "content": "Cześć"}, {"role": "assistant", "content": "Witaj"}]},
                           NOW, case)
    assert answer["status"] == "odpowiedz"
    prompt = calls[1]["messages"][-1]["content"]
    assert "KONTEKST APLIKACJI I SPRAWY" in prompt and "Obserwacje" in prompt
    assert case["employee"]["lastName"] not in prompt
    assert calls[1]["messages"][0] == {"role": "user", "content": "Cześć"}


def test_observation_enrichment_validates_indicator_ids(llm):
    _, replies = llm
    c = _case("case-anna")
    criteria = ["c01", "c04"]
    replies.append({"quality": "konkretna", "message": "Dobra notatka.", "missing": [], "flagged_phrases": ["super"],
                    "questions": [], "matches": [{"indicator_id": "c01-i01", "confidence": "wysoka", "phrases": ["w terminie"]},
                                                 {"indicator_id": "c99-i01", "confidence": "wysoka"}],
                    "title": "Raport z incydentu", "task_id": "nope"})
    result = enrich.analyze_observation({"date": "2026-11-10", "title": "", "description": "Przygotowała raport z incydentu w terminie."},
                                        criteria, c["position"]["tasks"], NOW)
    assert [m["indicatorId"] for m in result["matches"]] == ["c01-i01"]
    assert result["coaching"]["flaggedPhrases"] != ["super"]  # fraza spoza notatki odrzucona
    assert result["suggestedTitle"] == "Raport z incydentu"
    assert result.get("suggestedTaskId") != "nope"


def test_conversation_questions_use_different_facts():
    from app.kompas.engines.drafts import build_conversation_plan

    plan = build_conversation_plan(_case("case-anna"), NOW)
    questions = [question for item in plan["items"] for question in item["questions"]]
    assert len(questions) >= 8
    assert len(set(questions)) == len(questions)
    openings = [question[:42] for question in questions]
    assert len(set(openings)) > len(openings) // 2
    nato = [question for question in questions if "NATO" in question]
    assert len(nato) == 2 and nato[0] != nato[1]
    assert all("Jak oceniasz sytuację" not in question for question in questions)
    assert any("komunikat był niepełny" in question for question in questions)


def test_drafts_fall_back_without_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = _case("case-anna")
    assert enrich.justification(c, NOW)["text"]
    assert enrich.conversation_plan(c, NOW)["items"]
    assert ref.competency("c01")


def test_offline_answers_suggested_questions_and_refuses_off_topic(monkeypatch):
    from app.kompas.engines import assistant_rules

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for path in ("periodic", "first"):
        for mode in ("formalny", "rozmowa"):
            for s in assistant_rules.suggested_questions(path, mode):
                a = assistant.ask({"question": s["text"], "mode": mode, "context": {"path": path}}, NOW)
                assert a["status"] == "odpowiedz" and a["model"] == assistant_rules.RULES_MODEL, s["text"]
                assert a["citations"], s["text"]
    for q in ("Jak ugotować pierogi?", "Jaka jest stolica Francji?"):
        assert assistant.ask({"question": q, "mode": "formalny"}, NOW)["status"] == "brak-zrodla"
    fragments = assistant.ask({"question": "Kto decyduje o ocenie okresowej?", "mode": "formalny"}, NOW)
    assert fragments["status"] == "odpowiedz" and fragments["citations"] and "niedostępny" in fragments["answer"]
