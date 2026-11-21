"""Wywołania LLM przez litellm (Anthropic / Gemini / Ollama) + parsowanie JSON + walidacja cytowań."""
from __future__ import annotations
import json
import re

import litellm

from app.core.config import settings
from app.rag.prompts import ABSTAIN_SENTENCE, CONDENSE_SYSTEM, FORMAL_SYSTEM, CONVERSATION_SYSTEM, build_user_prompt

litellm.drop_params = True


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
    kwargs = dict(model=model, messages=[{"role": "system", "content": system}, *messages],
                  max_tokens=max_tokens, temperature=settings.temperature, timeout=60)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content or ""


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


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        return json.loads(m.group(0) if m else raw)
    except Exception:
        return {"answer": raw, "citations": [int(n) for n in re.findall(r"\[(\d+)\]", raw)], "abstained": ABSTAIN_SENTENCE in raw}


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
    return {"answer": answer, "citations": citations, "abstained": abstained, "raw": raw}


def abstain_answer() -> dict:
    return {"answer": ABSTAIN_SENTENCE + " Proszę doprecyzować pytanie lub zapytać mentora merytorycznego / komórkę kadr.",
            "citations": [], "abstained": True, "raw": ""}
