import asyncio
import json

from fastapi import APIRouter, Header, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.rag.pipeline import answer
from app.rag.schema import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    # pipeline is sync (models on CPU) -> run in threadpool so the event loop stays free
    return await asyncio.to_thread(answer, req, request.app.state.index, request.app.state.store)


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """Pseudo-stream: computes full answer, then emits it in word chunks + final 'citations' event.
    Replace with litellm stream=True in generate.py if real token streaming is needed."""
    async def gen():
        resp = await asyncio.to_thread(answer, req, request.app.state.index, request.app.state.store)
        words = resp.answer.split(" ")
        for i in range(0, len(words), 4):
            yield {"event": "token", "data": " ".join(words[i:i + 4]) + " "}
            await asyncio.sleep(0.02)
        yield {"event": "citations", "data": json.dumps([c.model_dump() for c in resp.citations], ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps({"abstained": resp.abstained, "confidence": resp.confidence,
                                                    "trace_id": resp.trace_id}, ensure_ascii=False)}
    return EventSourceResponse(gen())


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request):
    return {"session_id": session_id, "messages": request.app.state.store.full(session_id)}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request):
    request.app.state.store.delete(session_id)
    return {"deleted": session_id}


@router.get("/sources/{chunk_id}")
def get_source(chunk_id: str, request: Request):
    c = request.app.state.index.by_id.get(chunk_id)
    if not c:
        raise HTTPException(404, "chunk not found")
    return {"id": c.id, "source_title": c.source_title, "citation": c.citation, "page": c.page,
            "doc_type": c.doc_type, "text": c.text, "parent_id": c.parent_id, "parent_text": c.parent_text,
            "extra": c.extra}


@router.post("/admin/ingest")
async def admin_ingest(x_admin_token: str = Header(default="")):
    if x_admin_token != settings.admin_token:
        raise HTTPException(401, "bad token")
    from scripts.ingest import run
    await asyncio.to_thread(run)
    from app.rag.index import get_index
    get_index.cache_clear()
    return {"status": "reindexed"}
