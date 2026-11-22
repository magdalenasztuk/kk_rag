"""Asystent AI: strażnicy -> zapytania (Claude Haiku) -> RAG (BM25 + FAQ) -> odpowiedź ze źródłami (Claude Sonnet).

Bez klucza API albo przy błędzie modelu asystent odpowiada z bazy pytań zespołu (tryb offline) — demo działa zawsze.
"""
from __future__ import annotations

import logging
import re

from app.core.config import settings
from app.domain.text import new_id, normalize
from app.kompas import knowledge
from app.kompas.ai import prompts
from app.kompas.ai.context import case_context
from app.kompas.engines import assistant_rules
from app.rag import generate
from app.rag.index import tokenize_pl
from app.rag.prompts import ABSTAIN_SENTENCE
from app.rag.retrieve import Hit, retrieve_multi

log = logging.getLogger("kompas.assistant")

MAX_HISTORY = 10
TOP_K = 10
OFFLINE_FRAGMENTS = 3
OFFLINE_INTENT_DEPTH = 5
STRONG_RULE_SCORE = 6
FAQ_PREFIX = "faq_kompas__"
QUESTION_WORDS = {"jaki", "jaka", "jakie", "który", "ktory", "kiedy", "dlaczego", "czemu", "gdzie", "można", "mozna",
                  "musieć", "musiec", "mieć", "miec", "trzeba", "zrobić", "zrobic", "wplywac", "wpływać"}
MISSING_ANSWER = ("W udostępnionych źródłach nie znalazłem odpowiedzi na to pytanie. Nie zgaduję — sprawdź w komórce "
                  "kadr albo zadaj pytanie inaczej.")


def model_label(n_queries: int) -> str:
    name = settings.resolved_answer_model().split("/")[-1]
    return f"{name} + RAG (BM25 × {n_queries} zapytań, {len(knowledge._index().chunks)} fragmentów źródeł)"


def _process(question: str, path: str | None) -> str | None:
    text = normalize(question)
    if "pierwsz" in text and "okresow" not in text:
        return "pierwsza"
    if "okresow" in text and "pierwsz" not in text:
        return "okresowa"
    return {"first": "pierwsza", "periodic": "okresowa"}.get(path or "")


def _history(raw) -> list[dict]:
    turns = []
    for t in (raw or [])[-MAX_HISTORY:]:
        role, content = t.get("role"), (t.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            turns.append({"role": role, "content": content[:1200]})
    return turns


def _queries(question: str, history: list[dict]) -> tuple[str, list[str]]:
    """Samodzielne pytanie + parafrazy słownictwem przepisów (poprawia trafność wyszukiwania leksykalnego)."""
    if not settings.multi_query:
        return question, [question]
    convo = "\n".join(f"{'Użytkownik' if t['role'] == 'user' else 'Asystent'}: {t['content'][:400]}" for t in history)
    user = (f"HISTORIA:\n{convo}\n\n" if convo else "") + f"OSTATNIE PYTANIE: {question}"
    try:
        data = generate.parse_json_object(generate.complete_text(prompts.QUERY_SYSTEM, user, max_tokens=300)) or {}
    except Exception as exc:  # noqa: BLE001 — wyszukiwanie działa też na samym pytaniu
        log.warning("query rewrite failed: %s", exc)
        data = {}
    standalone = str(data.get("question") or question).strip() or question
    extra = [str(q).strip() for q in data.get("queries") or [] if str(q).strip()][:3]
    queries = [question] if standalone == question else [standalone, question]
    return standalone, queries + [q for q in extra if q not in queries]


def _fragment_text(hit: Hit) -> str:
    c = hit.chunk
    meta = knowledge.source_meta(c.source_id)
    label = "Reguła narzędzia (nie przepis)" if c.doc_type == "regula_narzedzia" else meta["shortTitle"]
    return f"({label}, {knowledge.locator(c)}) {hit.context_text or c.text}"


def _clean(text: str) -> str:
    return re.sub(r"\*\*|__|^#+\s*", "", str(text or ""), flags=re.M).strip()


def _cited_numbers(texts: list[str], declared) -> list[int]:
    seen: list[int] = []
    for t in texts:
        for n in re.findall(r"\[(\d+)\]", t):
            if int(n) not in seen:
                seen.append(int(n))
    for n in declared or []:
        try:
            if int(n) not in seen:
                seen.append(int(n))
        except (TypeError, ValueError):
            continue
    return seen


def _renumber(text: str, mapping: dict[int, int]) -> str:
    """Numery odwołań zgodne z kolejnością listy źródeł pod odpowiedzią."""
    out = re.sub(r"\[(\d+)\]", lambda m: f"[{mapping[int(m.group(1))]}]" if int(m.group(1)) in mapping else "", text)
    return re.sub(r"\s+([.,;:])", r"\1", out).strip()


_last_error: dict = {}


def status() -> dict:
    """Diagnostyka wdrożenia: czy model jest skonfigurowany i czy ostatnie wywołanie się udało."""
    return {"llm": settings.llm_available(), "provider": settings.llm_provider,
            "answerModel": settings.resolved_answer_model(), "fastModel": settings.resolved_fast_model(),
            "denseRetrieval": settings.dense_enabled, "fragments": len(knowledge._index().chunks),
            **({"lastError": _last_error} if _last_error else {})}


def ask(question: dict, answered_at: str, case: dict | None = None) -> dict:
    guarded = assistant_rules.guard(question, answered_at, assistant_rules.RULES_MODEL)
    if guarded:
        return guarded
    if not settings.llm_available():
        return _answer_offline(question, answered_at)
    try:
        answer = _ask_llm(question, answered_at, case)
        _last_error.clear()
        return answer
    except Exception as exc:  # noqa: BLE001 — model niedostępny: odpowiedź z bazy pytań
        log.exception("assistant LLM failed: %s", exc)
        _last_error.update(at=answered_at, error=f"{type(exc).__name__}: {str(exc)[:300]}")
        return _answer_offline(question, answered_at)


def _terms(text: str) -> set[str]:
    return {t for t in tokenize_pl(text) if len(t) > 3 and t not in QUESTION_WORDS}


def _covers(terms: set[str], text: str) -> bool:
    return bool(terms) and len(terms & set(tokenize_pl(text))) >= min(2, len(terms))


def _offline_intent(question: dict, process: str | None) -> dict | None:
    """Pytanie z bazy zespołu wybrane wyszukiwaniem (BM25 po pytaniach, parafrazach i odpowiedziach), nie słowem kluczem."""
    text = question["question"]
    pool = {i["id"]: i for i in assistant_rules.intent_pool(question["mode"])}
    index = knowledge._index()
    terms = _terms(text)
    key_terms = set(sorted(terms, key=lambda t: -index.bm25.idf.get(t, 0.0))[:2])
    for cid, _ in index.lexical(text, OFFLINE_INTENT_DEPTH, process):
        intent = pool.get(cid.removeprefix(FAQ_PREFIX)) if cid.startswith(FAQ_PREFIX) else None
        faq_text = index.by_id[cid].text if intent else ""
        if intent and _covers(terms, faq_text) and key_terms & set(tokenize_pl(faq_text)):
            return intent
    intent, score = assistant_rules.match_intent(question)
    return intent if intent and score >= STRONG_RULE_SCORE else None


def _answer_offline(question: dict, answered_at: str) -> dict:
    """Baza pytań zespołu, a gdy pytania w niej nie ma — dosłowne fragmenty źródeł zamiast odmowy."""
    guarded = assistant_rules.guard(question, answered_at, assistant_rules.RULES_MODEL)
    if guarded:
        return guarded
    text = question["question"]
    process = _process(text, (question.get("context") or {}).get("path"))
    intent = _offline_intent(question, process)
    if intent:
        return assistant_rules.answer_from_intent(question, answered_at, intent)
    offline = assistant_rules.answer_missing(question, answered_at)
    terms = _terms(text)
    hits = [h for h in retrieve_multi(knowledge._index(), [text], process, top_k=OFFLINE_FRAGMENTS)
            if _covers(terms, h.chunk.text)]
    if not hits:
        return offline
    return {**offline, "status": "odpowiedz",
            "model": "Kompas — wyszukiwarka źródeł (tryb offline, bez modelu AI)",
            "answer": ("Model AI jest teraz niedostępny, więc nie formułuję własnej odpowiedzi. Poniżej najtrafniejsze "
                       "fragmenty źródeł — przeczytaj je i oceń, czy odpowiadają na pytanie."),
            "bullets": [f"{knowledge.display_text(h.chunk)[:240].rstrip()}… [{i}]"
                        for i, h in enumerate(hits, start=1)],
            "citations": [knowledge.citation_for(h.chunk, i) for i, h in enumerate(hits, start=1)],
            "toolRule": any(h.chunk.doc_type == "regula_narzedzia" for h in hits)}


def _ask_llm(question: dict, answered_at: str, case: dict | None) -> dict:
    mode = question["mode"]
    context = question.get("context") or {}
    history = _history(question.get("history"))
    standalone, queries = _queries(question["question"], history)
    hits = retrieve_multi(knowledge._index(), queries, _process(standalone, context.get("path")), top_k=TOP_K)
    base = {"id": new_id("ans"), "question": question["question"], "mode": mode, "answeredAt": answered_at,
            "model": model_label(len(queries))}
    if not hits:
        return {**base, "status": "brak-zrodla", "answer": MISSING_ANSWER, "bullets": [], "citations": [],
                "toolRule": False,
                "followUps": [s["text"] for s in assistant_rules.suggested_questions(context.get("path"), mode)[:3]]}

    app_context = case_context(case, context.get("stepId")) if case else ""
    system = prompts.CONVERSATION_SYSTEM if mode == "rozmowa" else prompts.FORMAL_SYSTEM
    messages = [*history, {"role": "user", "content": prompts.build_user_prompt(
        standalone, [_fragment_text(h) for h in hits], app_context)}]
    raw = generate._complete(settings.resolved_answer_model(), system, messages, settings.answer_max_tokens, json_mode=True)
    data = generate.parse_json_object(raw)
    if data is None:
        raise ValueError(f"model returned no JSON: {raw[:200]!r}")

    answer = _clean(data.get("answer"))
    bullets = [_clean(b) for b in data.get("bullets") or [] if _clean(b)][:6]
    abstained = bool(data.get("abstained")) or ABSTAIN_SENTENCE.lower() in answer.lower()
    numbers = [n for n in _cited_numbers([answer, *bullets], data.get("citations")) if 1 <= n <= len(hits)]
    if abstained and not bullets:
        return {**base, "status": "brak-zrodla", "answer": MISSING_ANSWER,
                "bullets": ["Przeszukano: ustawę o służbie cywilnej, rozporządzenia z 2015 i 2016 r., poradniki KPRM, "
                            "model kompetencji i wzory arkuszy."],
                "citations": [], "toolRule": False,
                "followUps": [str(f) for f in data.get("follow_ups") or []][:3]
                or [s["text"] for s in assistant_rules.suggested_questions(context.get("path"), mode)[:3]]}
    if not numbers and mode == "formalny":
        raise ValueError("formal answer without citations")

    mapping = {n: i for i, n in enumerate(numbers, start=1)}
    cited = [hits[n - 1].chunk for n in numbers]
    tool_rule = bool(data.get("tool_rule")) or any(c.doc_type == "regula_narzedzia" for c in cited)
    return {**base, "status": "odpowiedz", "answer": _renumber(answer, mapping),
            "bullets": [_renumber(b, mapping) for b in bullets],
            "citations": [knowledge.citation_for(c, i) for i, c in enumerate(cited, start=1)],
            "toolRule": tool_rule, "followUps": [str(f) for f in data.get("follow_ups") or []][:3]}
