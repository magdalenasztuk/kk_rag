"""Ewaluacja na golden datasecie.

  python -m eval.run_eval --retrieval-only     # recall@5 / MRR, bez LLM (szybka pętla na chunking/model)
  python -m eval.run_eval                      # pełny pipeline + metryki odpowiedzi (+ sędzia LLM, jeśli --judge)
  python -m eval.run_eval --judge --tag bge-m3_hybrid_rerank

Wynik: eval/results/<tag>_<timestamp>.json + tabela w stdout.
"""
from __future__ import annotations
import argparse
import json
import statistics
import time
import uuid
from pathlib import Path

from app.core.config import settings
from app.rag.index import get_index
from app.rag.memory import SessionStore
from app.rag.prompts import ABSTAIN_SENTENCE
from app.rag.retrieve import retrieve, should_abstain
from app.rag.schema import ChatRequest

GOLDEN = Path(__file__).parent / "golden.jsonl"
RESULTS = Path(__file__).parent / "results"

JUDGE_PROMPT = """Oceń odpowiedź asystenta względem odpowiedzi wzorcowej. Skala: 2 = poprawna i kompletna, 1 = częściowo poprawna / niepełna, 0 = błędna lub niezgodna.
PYTANIE: {q}
WZORZEC: {ref}
ODPOWIEDŹ: {ans}
Zwróć tylko cyfrę."""


def load_golden() -> list[dict]:
    return [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]


def retrieval_metrics(index, items, k=5):
    recalls, mrrs = [], []
    for it in items:
        exp = set(it.get("expected_chunk_ids") or [])
        if not exp:
            continue
        proc = it.get("process") if it.get("process") in ("okresowa", "pierwsza") else None
        hits = retrieve(index, it["question"], process=proc, top_k=k)
        ids = [h.chunk.id for h in hits]
        recalls.append(len(exp & set(ids)) / len(exp))
        rr = 0.0
        for rank, cid in enumerate(ids, start=1):
            if cid in exp:
                rr = 1 / rank
                break
        mrrs.append(rr)
        it["_retrieved"] = ids
    return {"recall@5": round(statistics.mean(recalls), 3) if recalls else None,
            "mrr": round(statistics.mean(mrrs), 3) if mrrs else None, "n": len(recalls)}


def judge(q, ref, ans) -> int:
    import litellm
    r = litellm.completion(model=settings.resolved_fast_model(), temperature=0, max_tokens=3,
                           messages=[{"role": "user", "content": JUDGE_PROMPT.format(q=q, ref=ref, ans=ans)}])
    txt = (r.choices[0].message.content or "").strip()
    return int(txt[0]) if txt and txt[0] in "012" else 0


def answer_metrics(index, items, use_judge: bool):
    from app.rag.pipeline import answer
    store = SessionStore(settings.data_dir / "eval_sessions.sqlite")
    rows, must_ok, abst_ok_pos, abst_ok_neg, cit_ok, judge_scores, lat = [], [], [], [], [], [], []
    for it in items:
        sid = "eval-" + uuid.uuid4().hex[:8]
        # replay multi-turn history
        for m in it.get("messages", [])[:-1]:
            store.touch(sid); store.add(sid, m["role"], m["content"])
        req = ChatRequest(session_id=sid, message=it["question"], mode="formal",
                          context={"process": it.get("process")} if it.get("process") in ("okresowa", "pierwsza") else {})
        t0 = time.time()
        resp = answer(req, index, store)
        lat.append(time.time() - t0)
        a = resp.answer.lower()

        if it.get("should_abstain"):
            abst_ok_neg.append(resp.abstained)
        else:
            abst_ok_pos.append(not resp.abstained)
            mi = it.get("must_include", [])
            must_ok.append(all(s.lower() in a for s in mi) if mi else True)
            if it.get("must_not_include"):
                must_ok[-1] = must_ok[-1] and not any(s.lower() in a for s in it["must_not_include"])
            exp = set(it.get("expected_chunk_ids") or [])
            if exp:
                cit_ok.append(bool(exp & {c.chunk_id for c in resp.citations}))
            if use_judge:
                judge_scores.append(judge(it["question"], it["expected_answer"], resp.answer))
        rw_ok = None
        if it.get("expected_rewritten_contains"):
            rw_ok = all(s.lower() in resp.rewritten_query.lower() for s in it["expected_rewritten_contains"])
        rows.append({"id": it["id"], "category": it["category"], "abstained": resp.abstained, "confidence": resp.confidence,
                     "rewritten": resp.rewritten_query, "rewrite_ok": rw_ok, "citations": [c.chunk_id for c in resp.citations],
                     "answer": resp.answer, "latency_s": round(lat[-1], 2)})
    m = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    return {"must_include_acc": m(must_ok), "abstain_recall(traps)": m(abst_ok_neg),
            "answer_rate(non-traps)": m(abst_ok_pos), "citation_hit": m(cit_ok),
            "judge_mean(0-2)": round(statistics.mean(judge_scores), 3) if judge_scores else None,
            "latency_p50_s": round(statistics.median(lat), 2), "latency_p95_s": round(sorted(lat)[int(len(lat) * .95) - 1], 2)}, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--category", default=None)
    args = ap.parse_args()

    items = load_golden()
    if args.category:
        items = [i for i in items if i["category"] == args.category]
    index = get_index()
    out = {"tag": args.tag, "ts": time.time(), "config": {
        "embedding_model": settings.embedding_model, "reranker": settings.reranker_model if settings.use_reranker else None,
        "llm": settings.resolved_answer_model(), "abstain_threshold": settings.abstain_threshold}}
    out["retrieval"] = retrieval_metrics(index, items)
    print("RETRIEVAL:", out["retrieval"])
    if not args.retrieval_only:
        out["answers"], out["rows"] = answer_metrics(index, items, args.judge)
        print("ANSWERS:  ", out["answers"])
        for r in out["rows"]:
            if r["category"] == "pulapka" or r["rewrite_ok"] is False:
                print(f"  {r['id']:>4} abst={r['abstained']} conf={r['confidence']} :: {r['answer'][:110]}")
    RESULTS.mkdir(exist_ok=True)
    p = RESULTS / f"{args.tag}_{int(time.time())}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", p)


if __name__ == "__main__":
    main()
