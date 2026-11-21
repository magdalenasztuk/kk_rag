from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.rag.index import get_index
from app.rag.memory import SessionStore
from app.rag.retrieve import get_reranker


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.index = get_index()          # loads chunks, BM25, Chroma, embedder
    get_reranker()                          # warm-up
    app.state.store = SessionStore()
    yield


app = FastAPI(title="Kompas Kompetencji – asystent AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health():
    idx = app.state.index
    return {"status": "ok", "chunks": len(idx.chunks), "collection": settings.collection_name,
            "embedding_model": settings.embedding_model, "llm": settings.resolved_answer_model()}
