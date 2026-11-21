"""Akty prawne z ręcznie zweryfikowanego JSON -> chunks (child = ustęp/pkt, parent = paragraf/artykuł)."""
import json
import re
from pathlib import Path
from app.rag.schema import Chunk
from app.rag.ingest.xlsx_model import _slug


def _cid(source_id: str, citation: str) -> str:
    return f"{source_id}__{_slug(citation)}"


def load_legal_chunks(path: Path) -> list[Chunk]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    sid, title, short = doc["source_id"], doc["source_title"], doc.get("short_title", doc["source_title"])
    process = doc.get("process", "both")
    units = doc["units"]

    # parent texts = concatenation of children sharing the same parent (plus a unit that IS the parent, if any)
    parents: dict[str, list[str]] = {}
    for u in units:
        p = u.get("parent")
        if p:
            parents.setdefault(p, []).append(f"{u['citation']}: {u['text']}")

    chunks: list[Chunk] = []
    for u in units:
        parent = u.get("parent")
        ctype = u.get("chunk_type") or ("ustep" if parent else "section")
        chunks.append(Chunk(
            id=_cid(sid, u["citation"]),
            text=f"{short}, {u['citation']}: {u['text']}",
            source_id=sid, source_title=title, doc_type="akt_prawny", process=process,
            citation=u["citation"], page=u.get("page"),
            parent_id=_cid(sid, parent) if parent else None,
            parent_text=("\n".join(parents[parent]) if parent and parent in parents else None),
            chunk_type=ctype, authority=3,
        ))
    return chunks


def load_all_legal(dir_: Path) -> list[Chunk]:
    out = []
    for p in sorted(dir_.glob("*.json")):
        out.extend(load_legal_chunks(p))
    return out
