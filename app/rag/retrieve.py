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
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:          # slim install (requirements.txt only) -> RRF ranking
        return None
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
        linked = list(h.chunk.extra.get("linked_ids", []))
        process = h.chunk.process
        for cit in h.chunk.extra.get("citations", []):
            # "§ 5 ust. 2" exists in both regulations — keep the one matching the FAQ's assessment path.
            linked += [cid for cid in index.by_citation.get(cit.lower(), [])
                       if process == "both" or index.by_id[cid].process in (process, "both")]
        for cid in linked:
            if cid in index.by_id:
                if cid not in present:
                    present.add(cid)
                    extra.append(Hit(chunk=index.by_id[cid], rrf=h.rrf * 0.98, sources=["faq_link"]))
    return sorted(hits + extra, key=lambda x: -x.rrf)


def _pin_faq_links(hits: list[Hit], n_linked: int) -> list[Hit]:
    """Move the n best-reranked FAQ-cited chunks up to directly after the first FAQ hit.
    Only ever moves a chunk up: one the reranker already placed above the FAQ stays where it is."""
    if n_linked <= 0:
        return hits
    faq_pos = next((i for i, h in enumerate(hits) if h.chunk.doc_type == "faq"), None)
    if faq_pos is None:
        return hits
    linked = [(i, h) for i, h in enumerate(hits) if "faq_link" in (h.sources or [])][:n_linked]
    move = [h for i, h in linked if i > faq_pos + 1]
    if not move:
        return hits
    move_ids = {h.chunk.id for h in move}
    rest = [h for h in hits if h.chunk.id not in move_ids]
    return rest[:faq_pos + 1] + move + rest[faq_pos + 1:]   # faq_pos unchanged: moved items were all below it


def _reserve_legal(hits: list[Hit], k: int, n: int) -> list[Hit]:
    """Ensure at least n akt_prawny chunks in the first k by swapping in the best ones from below
    (the top-ranked hit is never displaced, so abstain decisions are unchanged)."""
    if n <= 0 or len(hits) <= k:
        return hits
    top, rest = hits[:k], hits[k:]
    missing = n - sum(h.chunk.doc_type == "akt_prawny" for h in top)
    if missing <= 0:
        return hits
    # make room only by demoting the lowest-ranked non-legal hits (never position 0)
    droppable = [i for i in range(k - 1, 0, -1) if top[i].chunk.doc_type != "akt_prawny"]
    extra = [h for h in rest if h.chunk.doc_type == "akt_prawny"][:min(missing, len(droppable))]
    if not extra:
        return hits
    drop_idx = set(droppable[:len(extra)])
    kept = [h for i, h in enumerate(top) if i not in drop_idx]
    dropped = [top[i] for i in sorted(drop_idx)]
    extra_ids = {h.chunk.id for h in extra}
    return kept + extra + dropped + [h for h in rest if h.chunk.id not in extra_ids]


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
        # The reranker scores short legal ustępy below long poradnik passages, undoing the FAQ link
        # and crowding the primary source out of the top-k -> restore both.
        fused = _pin_faq_links(fused, settings.faq_linked_pin)
        fused = _reserve_legal(fused, top_k, settings.min_legal_in_top)

    hits = fused[:top_k]
    for h in hits:
        c = h.chunk
        h.context_text = c.text
        if c.parent_text and c.doc_type == "akt_prawny":
            h.context_text += f"\n[Kontekst – cały {c.parent_id.split('__', 1)[1].replace('_', ' ')}]: {c.parent_text}"
    return hits


def _context(hits: list[Hit]) -> list[Hit]:
    for h in hits:
        c = h.chunk
        h.context_text = c.text
        if c.parent_text and c.doc_type == "akt_prawny":
            h.context_text += f"\n[Kontekst – cały {c.parent_id.split('__', 1)[1].replace('_', ' ')}]: {c.parent_text}"
    return hits


def _dedupe(hits: list[Hit], containment: float = 0.8) -> list[Hit]:
    """Drop near-duplicates (overlapping guide windows, app paraphrases of the same passage)."""
    from app.rag.index import tokenize_pl
    out: list[Hit] = []
    seen: list[set[str]] = []
    for h in hits:
        toks = set(tokenize_pl(h.chunk.text))
        if toks and any(len(toks & s) / len(toks) >= containment for s in seen):
            continue
        out.append(h)
        seen.append(toks)
    return out


def retrieve_multi(index: Index, queries: list[str], process: str | None = None, top_k: int | None = None) -> list[Hit]:
    """Several reformulations of one question -> one fused ranking (RRF over every list).
    Compensates for the lexical-only index in the serverless deployment."""
    top_k = top_k or settings.final_top_k
    k = settings.rrf_k
    acc: dict[str, Hit] = {}
    for qi, query in enumerate(q for q in queries if q and q.strip()):
        lists = [("bm25", index.lexical(query, settings.bm25_top_k, process))]
        if index.dense_enabled:
            lists.append(("dense", index.dense(query, settings.dense_top_k, process)))
        for name, ranked in lists:
            weight = 1.0 if qi == 0 else 0.8      # the user's own wording counts most
            for rank, (cid, _) in enumerate(ranked, start=1):
                h = acc.setdefault(cid, Hit(chunk=index.by_id[cid], rrf=0.0))
                h.rrf += weight / (k + rank)
                if name not in h.sources:
                    h.sources.append(name)
    hits = sorted(acc.values(), key=lambda h: -h.rrf)
    for h in hits:
        if h.chunk.doc_type == "faq":
            h.rrf *= settings.faq_boost
            break
    hits.sort(key=lambda h: -h.rrf)
    hits = _diversify(hits)[: max(settings.dense_top_k, settings.bm25_top_k)]
    hits = _dedupe(expand_faq_citations(index, hits))

    reranker = get_reranker()
    if reranker and hits:
        import math
        scores = reranker.predict([(queries[0], h.chunk.text) for h in hits], activation_fn=None)
        for h, s in zip(hits, scores):
            h.rerank = 1 / (1 + math.exp(-float(s)))
        hits.sort(key=lambda h: (-(h.rerank or 0), -h.chunk.authority))
        hits = _pin_faq_links(hits, settings.faq_linked_pin)
    hits = _reserve_legal(hits, top_k, settings.min_legal_in_top)
    return _context(hits[:top_k])


def should_abstain(hits: list[Hit]) -> bool:
    if not hits:
        return True
    best = hits[0].score
    if hits[0].rerank is not None:
        return best < settings.abstain_threshold
    return best < 0.02   # RRF-only fallback (no reranker): ~1/(60+rank) scale
