"""Wywołania LLM (Anthropic SDK; Gemini / Ollama przez litellm) + parsowanie JSON + walidacja cytowań."""
from __future__ import annotations
import json
import re
from functools import lru_cache

from app.core.config import settings
from app.rag.prompts import ABSTAIN_SENTENCE, CONDENSE_SYSTEM, FORMAL_SYSTEM, CONVERSATION_SYSTEM, build_user_prompt


@lru_cache(maxsize=1)
def _anthropic():
    import anthropic
    return anthropic.Anthropic(timeout=settings.llm_timeout_s, max_retries=1)


def _mock_complete(system: str, messages: list[dict]) -> str:
    """Offline smoke-test mode (KOMPAS_LLM_PROVIDER=mock): echoes the first fragment as the answer."""
    user = messages[-1]["content"]
    if "Samodzielne pytanie:" in user:
        return user.split("OSTATNIE PYTANIE:")[1].split("\n")[0].strip()
    m = re.search(r"\[1\] (.+?)(?:\n\n\[2\]|\Z)", user, re.S)
    frag = (m.group(1).strip()[:300] if m else "")
    return json.dumps({"answer": f"[MOCK] {frag} [1]", "citations": [1], "abstained": not bool(frag)}, ensure_ascii=False)


def _complete(model: str, system: str, messages: list[dict], max_tokens: int, json_mode: bool = False) -> str:
    if settings.llm_provider == "mock":
        return _mock_complete(system, messages)
    if settings.llm_provider == "anthropic":
        resp = _anthropic().messages.create(
            model=model.removeprefix("anthropic/"), system=system, messages=messages, max_tokens=max_tokens)
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    import litellm
    litellm.drop_params = True
    kwargs = dict(model=model, messages=[{"role": "system", "content": system}, *messages],
                  max_tokens=max_tokens, temperature=settings.temperature, timeout=settings.llm_timeout_s)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content or ""


def complete_text(system: str, user: str, max_tokens: int = 1200, fast: bool = True) -> str:
    """Pojedyncze wywołanie modelu (szkice, analiza obserwacji, plan rozmowy)."""
    model = settings.resolved_fast_model() if fast else settings.resolved_answer_model()
    return _complete(model, system, [{"role": "user", "content": user}], max_tokens, json_mode=True)


def parse_json_object(raw: str) -> dict | None:
    """Pierwszy kompletny obiekt JSON w odpowiedzi modelu (tolerancja na tekst wokół i blok ```)."""
    for m in re.finditer(r"\{", raw or ""):
        try:
            data, _ = _DECODER.raw_decode(raw, m.start())
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def condense_question(history: list[dict], question: str) -> str:
    """history: [{"role":"user"|"assistant","content":...}] (already trimmed)."""
    if not history:
        return question
    convo = "\n".join(f"{'Użytkownik' if m['role']=='user' else 'Asystent'}: {m['content']}" for m in history)
    msg = [{"role": "user", "content": f"ROZMOWA:\n{convo}\n\nOSTATNIE PYTANIE: {question}\n\nSamodzielne pytanie:"}]
    try:
        out = _complete(settings.resolved_fast_model(), CONDENSE_SYSTEM, msg, max_tokens=200).strip().strip('"')
        return out if 5 < len(out) < 400 else question
    except Exception:
        return question


_JSON_START = re.compile(r'(```(?:json)?\s*)?\{\s*"(?:answer|citations|abstained)"\s*:', re.S)
_DECODER = json.JSONDecoder()


def _parse_json(raw: str) -> dict:
    """Models sometimes write prose and then repeat it as a (possibly truncated) ```json block.
    Order: any complete JSON object with an "answer" key (key order and trailing text don't matter)
    -> prose before the JSON -> "answer" value salvaged from truncated JSON -> raw text."""
    raw = raw.strip()
    for m in re.finditer(r"\{", raw):
        try:
            data, _ = _DECODER.raw_decode(raw, m.start())
        except ValueError:
            continue
        if isinstance(data, dict) and "answer" in data:
            return data
    start = _JSON_START.search(raw)
    if start:
        prose = raw[:start.start()].strip()
        if not prose:
            m = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)', raw[start.start():], re.S)
            if m:
                try:
                    prose = json.loads(f'"{m.group(1)}"')
                except Exception:
                    prose = m.group(1)
        text = prose.strip()
    else:
        text = raw
    return {"answer": text, "citations": [int(n) for n in re.findall(r"\[(\d+)\]", text)],
            "abstained": ABSTAIN_SENTENCE in text}


def generate_answer(question: str, hits_text: list[str], history: list[dict], app_context: dict, mode: str) -> dict:
    system = (FORMAL_SYSTEM if mode == "formal" else CONVERSATION_SYSTEM).format(abstain=ABSTAIN_SENTENCE)
    messages = [*history, {"role": "user", "content": build_user_prompt(question, hits_text, app_context, mode)}]
    raw = _complete(settings.resolved_answer_model(), system, messages, settings.answer_max_tokens, json_mode=True)
    data = _parse_json(raw)

    answer = str(data.get("answer", "")).strip()
    n = len(hits_text)
    used = {int(x) for x in re.findall(r"\[(\d+)\]", answer) if 1 <= int(x) <= n}
    declared = {int(x) for x in data.get("citations", []) if isinstance(x, (int, str)) and str(x).isdigit()}
    citations = sorted(used | {d for d in declared if 1 <= d <= n})
    # strip references to non-existent fragments
    answer = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if 1 <= int(m.group(1)) <= n else "", answer)
    abstained = bool(data.get("abstained")) or ABSTAIN_SENTENCE in answer
    if not answer:      # never return an empty answer: an empty reply is treated as an abstain
        return {**abstain_answer(), "raw": raw}
    return {"answer": answer, "citations": citations, "abstained": abstained, "raw": raw}


def abstain_answer() -> dict:
    return {"answer": ABSTAIN_SENTENCE + " Proszę doprecyzować pytanie lub zapytać mentora merytorycznego / komórkę kadr.",
            "citations": [], "abstained": True, "raw": ""}
