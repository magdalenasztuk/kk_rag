import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.kompas.api import router as kompas_router
from app.rag.index import get_index
from app.rag.memory import SessionStore
from app.rag.retrieve import get_reranker


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.index = get_index()          # loads chunks, BM25 (+ Chroma, embedder when dense is enabled)
    get_reranker()                          # warm-up (no-op when the reranker is disabled)
    app.state.store = SessionStore()
    yield


app = FastAPI(title="Kompas Kompetencji – API i asystent AI", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
@app.get("/api/health")
def health():
    idx = app.state.index
    return {"status": "ok", "chunks": len(idx.chunks), "dense": idx.dense_enabled and idx.col is not None,
            "llm": settings.resolved_answer_model() if settings.llm_available() else "offline"}


app.include_router(router, prefix="/api/v1")
app.include_router(kompas_router, prefix="/api")

if os.environ.get("VERCEL"):
    # Serverless runtime may skip ASGI lifespan events — initialise eagerly on cold start.
    app.state.index = get_index()
    app.state.store = SessionStore()
