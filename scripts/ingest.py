"""Build data/chunks.jsonl and the Chroma collection from all sources.

Usage:  python -m scripts.ingest            # full (needs embedding model)
        python -m scripts.ingest --dry      # only chunks.jsonl + stats, no embeddings
"""
import sys
from pathlib import Path

from app.core.config import settings
from app.rag.index import write_chunks
from app.rag.ingest.guides_faq import load_faq_chunks, load_guide_chunks
from app.rag.ingest.legal_json import load_all_legal
from app.rag.ingest.xlsx_model import load_model_chunks

RAW = settings.data_dir / "raw"

GUIDES = [  # (filename in data/raw, source_id, title, process)
    ("poradnik_oceny_okresowe_2016.pdf", "poradnik_okresowa",
     "Poradnik KPRM – Oceny okresowe w służbie cywilnej (2016)", "okresowa"),
    ("poradnik_pierwsza_ocena_2016.pdf", "poradnik_pierwsza",
     "Poradnik KPRM – Pierwsza ocena w służbie cywilnej (2016)", "pierwsza"),
]


def collect():
    chunks = []
    chunks += load_all_legal(settings.data_dir / "legal_json")
    xlsx = RAW / "Model_kompetencji.xlsx"
    if xlsx.exists():
        chunks += load_model_chunks(xlsx)
    for fn, sid, title, proc in GUIDES:
        p = RAW / fn
        if p.exists():
            chunks += load_guide_chunks(p, sid, title, proc)
        else:
            print(f"[warn] missing {p.name} – skipped")
    for p in sorted((settings.data_dir / "faq").glob("*.jsonl")):
        chunks += load_faq_chunks(p)
    ids = [c.id for c in chunks]
    dups = {i for i in ids if ids.count(i) > 1}
    assert not dups, f"duplicate chunk ids: {sorted(dups)[:10]}"
    return chunks


def run(dry: bool = False):
    chunks = collect()
    write_chunks(chunks)
    from collections import Counter
    print(f"chunks: {len(chunks)}", dict(Counter(c.doc_type for c in chunks)))
    if dry:
        return
    from app.rag.index import Embedder, build_chroma
    build_chroma(chunks, Embedder())
    print("chroma collection built:", settings.collection_name)


if __name__ == "__main__":
    run(dry="--dry" in sys.argv)
