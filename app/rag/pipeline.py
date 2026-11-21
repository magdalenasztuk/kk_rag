"""Orkiestracja: historia -> condense -> retrieval -> gate -> LLM -> post-check -> zapis + trace."""
from __future__ import annotations
import json
import time
import uuid

from app.core.config import settings
from app.rag.generate import abstain_answer, condense_question, generate_answer
from app.rag.index import Index
from app.rag.memory import SessionStore
from app.rag.retrieve import retrieve, should_abstain
from app.rag.schema import ChatRequest, ChatResponse, Citation


def _confidence(hits, result) -> str:
    if result["abstained"]:
        return "low"
    best = hits[0].score if hits else 0
    if not result["citations"]:
        return "low"
    if hits and hits[0].rerank is not None:
        return "high" if best >= 0.6 else "medium"
    return "medium"


def answer(req: ChatRequest, index: Index, store: SessionStore) -> ChatResponse:
    t0 = time.time()
    trace_id = uuid.uuid4().hex[:12]
    store.touch(req.session_id, req.context)
    history = store.history(req.session_id)

    rewritten = condense_question(history, req.message)
    process = req.context.get("process") if req.context.get("process") in ("okresowa", "pierwsza") else None
    hits = retrieve(index, rewritten, process=process)

    if req.mode == "formal" and should_abstain(hits):
        result = abstain_answer()
        hits_used = []
    else:
        result = generate_answer(rewritten, [h.context_text for h in hits], history, req.context, req.mode)
        hits_used = hits

    citations = []
    for n in result["citations"]:
        h = hits_used[n - 1]
        c = h.chunk
        citations.append(Citation(n=n, chunk_id=c.id, source_title=c.source_title, citation=c.citation,
                                  snippet=c.text[:400], doc_type=c.doc_type, page=c.page, score=round(h.score, 3)))

    resp = ChatResponse(answer=result["answer"], citations=citations, abstained=result["abstained"],
                        confidence=_confidence(hits_used, result), rewritten_query=rewritten,
                        latency_ms=int((time.time() - t0) * 1000), trace_id=trace_id)

    store.add(req.session_id, "user", req.message)
    store.add(req.session_id, "assistant", resp.answer, [c.model_dump() for c in citations])
    _trace(trace_id, req, rewritten, hits, resp)
    return resp


def _trace(trace_id, req, rewritten, hits, resp) -> None:
    rec = {"trace_id": trace_id, "ts": time.time(), "session_id": req.session_id, "mode": req.mode,
           "question": req.message, "rewritten": rewritten, "context": req.context,
           "hits": [{"id": h.chunk.id, "rrf": round(h.rrf, 4), "rerank": h.rerank, "src": h.sources} for h in hits],
           "answer": resp.answer, "citations": [c.chunk_id for c in resp.citations],
           "abstained": resp.abstained, "latency_ms": resp.latency_ms}
    settings.traces_path.parent.mkdir(parents=True, exist_ok=True)
    with settings.traces_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
