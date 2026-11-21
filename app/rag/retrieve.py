"""Hybrid retrieval: dense + BM25 -> RRF (+FAQ boost) -> cross-encoder rerank -> parent expansion."""
from __future__ import annotations
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import settings
from app.rag.index import Index
from app.rag.schema import Chunk


@dataclass
class Hit:
    chunk: Chunk
    rrf: float
    rerank: float | None = None
    context_text: str = ""            # text handed to the LLM (child + parent)
    sources: list[str] = field(default_factory=list)   # ["dense", "bm25"]

    @property
    def score(self) -> float:
        return self.rerank if self.rerank is not None else self.rrf


@lru_cache(maxsize=1)
def get_reranker():
    if not settings.use_reranker:
        return None
    from sentence_transformers import CrossEncoder
    return CrossEncoder(settings.reranker_model, max_length=1024)


def rrf_fuse(index: Index, dense: list[tuple[str, float]], lexical: list[tuple[str, float]]) -> list[Hit]:
    k = settings.rrf_k
    acc: dict[str, Hit] = {}
    for name, ranked in (("dense", dense), ("bm25", lexical)):
        for rank, (cid, _) in enumerate(ranked, start=1):
            h = acc.setdefault(cid, Hit(chunk=index.by_id[cid], rrf=0.0))
            h.rrf += 1.0 / (k + rank)
            h.sources.append(name)
    hits = sorted(acc.values(), key=lambda h: -h.rrf)
    # boost only the best FAQ hit (a matching FAQ is gold; the rest of FAQ is noise sharing vocabulary)
    for h in hits:
        if h.chunk.doc_type == "faq":
            h.rrf *= settings.faq_boost
            break
    hits.sort(key=lambda h: -h.rrf)
    return _diversify(hits)


def _diversify(hits: list[Hit], max_faq: int = 1, max_per_parent: int = 2) -> list[Hit]:
    """Keep at most 1 FAQ and 2 windows of the same guide section in the candidate list."""
    out, n_faq, per_parent = [], 0, {}
    for h in hits:
        c = h.chunk
        if c.doc_type == "faq":
            if n_faq >= max_faq:
                continue
            n_faq += 1
        if c.parent_id and c.doc_type == "poradnik":
            per_parent[c.parent_id] = per_parent.get(c.parent_id, 0) + 1
            if per_parent[c.parent_id] > max_per_parent:
                continue
        out.append(h)
    return out


def expand_faq_citations(index: Index, hits: list[Hit]) -> list[Hit]:
    """A retrieved FAQ entry carries the legal citations its answer rests on -> pull those chunks in
    (just below the FAQ hit) so the LLM can cite the primary source, not only the FAQ."""
    present = {h.chunk.id for h in hits}
    extra: list[Hit] = []
    for h in hits:
        if h.chunk.doc_type != "faq":
            continue
        for cit in h.chunk.extra.get("citations", []):
            for cid in index.by_citation.get(cit.lower(), []):
                if cid not in present:
                    present.add(cid)
                    extra.append(Hit(chunk=index.by_id[cid], rrf=h.rrf * 0.98, sources=["faq_link"]))
    return sorted(hits + extra, key=lambda x: -x.rrf)


def retrieve(index: Index, query: str, process: str | None = None, top_k: int | None = None) -> list[Hit]:
    top_k = top_k or settings.final_top_k
    dense = index.dense(query, settings.dense_top_k, process)
    lexical = index.lexical(query, settings.bm25_top_k, process)
    fused = rrf_fuse(index, dense, lexical)[: max(settings.dense_top_k, settings.bm25_top_k)]
    fused = expand_faq_citations(index, fused)

    reranker = get_reranker()
    if reranker and fused:
        scores = reranker.predict([(query, h.chunk.text) for h in fused], activation_fn=None)
        import math
        for h, s in zip(fused, scores):
            h.rerank = 1 / (1 + math.exp(-float(s)))      # sigmoid -> 0..1, comparable across queries
        fused.sort(key=lambda h: (-(h.rerank or 0), -h.chunk.authority))

    hits = fused[:top_k]
    for h in hits:
        c = h.chunk
        h.context_text = c.text
        if c.parent_text and c.doc_type == "akt_prawny":
            h.context_text += f"\n[Kontekst – cały {c.parent_id.split('__', 1)[1].replace('_', ' ')}]: {c.parent_text}"
    return hits


def should_abstain(hits: list[Hit]) -> bool:
    if not hits:
        return True
    best = hits[0].score
    if hits[0].rerank is not None:
        return best < settings.abstain_threshold
    return best < 0.02   # RRF-only fallback (no reranker): ~1/(60+rank) scale
