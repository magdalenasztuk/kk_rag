"""Budowa i ładowanie indeksów: Chroma (dense) + BM25 (lexical, in-memory) + słownik chunków."""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.rag.schema import Chunk

_PL = str.maketrans("ąćęłńóśżź", "acelnoszz")


def tokenize_pl(text: str) -> list[str]:
    """Lowercase, strip diacritics, lemmatize (simplemma) — keeps '§', 'art', numbers."""
    try:
        import simplemma
        lem = lambda w: simplemma.lemmatize(w, lang="pl")
    except Exception:  # pragma: no cover
        lem = lambda w: w
    toks = re.findall(r"§|[a-ząćęłńóśżź]+|\d+", text.lower())
    return [lem(t).translate(_PL) for t in toks]


class Embedder:
    def __init__(self):
        self.provider = settings.embedding_provider
        if self.provider == "local":
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(settings.embedding_model)
        else:
            import voyageai
            self.client = voyageai.Client()

    def encode(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if self.provider == "local":
            return self.model.encode(texts, normalize_embeddings=True, batch_size=16).tolist()
        r = self.client.embed(texts, model=settings.voyage_model, input_type="query" if kind == "query" else "document")
        return r.embeddings


def read_chunks(path: Path = settings.chunks_path) -> list[Chunk]:
    return [Chunk.model_validate_json(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_chunks(chunks: list[Chunk], path: Path = settings.chunks_path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(c.model_dump_json() + "\n")


def build_chroma(chunks: list[Chunk], embedder: Embedder) -> None:
    import chromadb
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    try:
        client.delete_collection(settings.collection_name)
    except Exception:
        pass
    col = client.create_collection(
        settings.collection_name,
        metadata={"hnsw:space": "cosine", "embedding_model": settings.embedding_model},
    )
    B = 64
    for i in range(0, len(chunks), B):
        batch = chunks[i:i + B]
        col.add(
            ids=[c.id for c in batch],
            documents=[c.text for c in batch],
            metadatas=[c.chroma_metadata() for c in batch],
            embeddings=embedder.encode([c.text for c in batch]),
        )


class Index:
    """Loaded once in FastAPI lifespan."""

    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None):
        from rank_bm25 import BM25Okapi
        import chromadb
        self.chunks = chunks
        self.by_id = {c.id: c for c in chunks}
        self.by_citation: dict[str, list[str]] = {}
        for c in chunks:
            if c.doc_type in ("akt_prawny", "model_kompetencji") and c.citation:
                self.by_citation.setdefault(c.citation.lower(), []).append(c.id)
        self.bm25_ids = [c.id for c in chunks]
        self.bm25 = BM25Okapi([tokenize_pl(c.text) for c in chunks])
        self.dense_enabled = settings.dense_enabled
        self.embedder, self.col = None, None
        if self.dense_enabled:
            try:
                self.embedder = embedder or Embedder()
                self.col = chromadb.PersistentClient(path=str(settings.chroma_dir)).get_collection(settings.collection_name)
            except Exception as e:  # no model / no collection -> lexical-only fallback (offline demo mode)
                print(f"[index] dense retrieval disabled: {e!r}")
                self.dense_enabled = False

    def dense(self, query: str, k: int, process: str | None) -> list[tuple[str, float]]:
        if not self.dense_enabled:
            return []
        where = {"process": {"$in": [process, "both"]}} if process else None
        r = self.col.query(query_embeddings=self.embedder.encode([query], kind="query"), n_results=k, where=where)
        return list(zip(r["ids"][0], [1 - d for d in r["distances"][0]]))

    def lexical(self, query: str, k: int, process: str | None) -> list[tuple[str, float]]:
        scores = self.bm25.get_scores(tokenize_pl(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        out = []
        for i in order:
            c = self.chunks[i]
            if process and c.process not in (process, "both"):
                continue
            if scores[i] <= 0:
                break
            out.append((c.id, float(scores[i])))
            if len(out) >= k:
                break
        return out


@lru_cache(maxsize=1)
def get_index() -> Index:
    return Index(read_chunks())
