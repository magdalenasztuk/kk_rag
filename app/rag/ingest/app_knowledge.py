"""Baza wiedzy aplikacji (app/kompas/seed) -> chunks.

- fragmenty poradników, wzorów arkuszy, modelu i reguł narzędzia — przeszukiwane jak pozostałe źródła;
- fragmenty rozporządzeń z bazy aplikacji — tylko do podglądu cytatów trybu offline (pełny tekst aktów
  pochodzi z legal_json, więc nie dublujemy go w wyszukiwaniu);
- pytania i odpowiedzi asystenta (intents) — jako FAQ z odwołaniami do jednostek redakcyjnych.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.rag.schema import Chunk

APP_PREFIX = "kompas__"

SOURCE_MAP = {  # app sourceId -> (chunk source_id, doc_type, source_title, searchable)
    "rozp-2016": ("rozp_2016", "akt_prawny", "Rozporządzenie Prezesa Rady Ministrów z dnia 4 kwietnia 2016 r. w sprawie "
                  "warunków i sposobu przeprowadzania ocen okresowych urzędników służby cywilnej i pracowników służby "
                  "cywilnej (Dz. U. poz. 470)", False),
    "rozp-2015": ("rozp_2015", "akt_prawny", "Rozporządzenie Prezesa Rady Ministrów z dnia 23 lipca 2015 r. w sprawie "
                  "szczegółowych warunków i sposobu dokonywania pierwszej oceny w służbie cywilnej (Dz. U. poz. 1144)", False),
    "poradnik-okresowa": ("poradnik_okresowa", "poradnik", "Poradnik KPRM – Oceny okresowe w służbie cywilnej (2016)", True),
    "poradnik-pierwsza": ("poradnik_pierwsza", "poradnik", "Poradnik KPRM – Pierwsza ocena w służbie cywilnej (2016)", True),
    "arkusze": ("arkusze", "arkusz", "Wzory arkuszy oceny okresowej B i C oraz arkusza pierwszej oceny", True),
    "model": ("model_kompetencji", "model_kompetencji", "Model kompetencji – służba cywilna (14 kompetencji, 49 "
              "wskaźników, 5 poziomów)", True),
    "reguly": ("reguly_narzedzia", "regula_narzedzia", "Reguły narzędzia Kompas Kompetencji (nie są przepisem)", True),
}

AUTHORITY = {"akt_prawny": 3, "poradnik": 2, "arkusz": 2, "model_kompetencji": 2, "regula_narzedzia": 1}


def chunk_id(fragment_id: str) -> str:
    return f"{APP_PREFIX}{fragment_id}"


def _process(paths: list[str]) -> str:
    if set(paths) >= {"periodic", "first"} or not paths:
        return "both"
    return "pierwsza" if paths == ["first"] else "okresowa"


def _numbers(spec: str) -> set[int]:
    """'1–2' -> {1, 2}; '1 i 3' -> {1, 3}; '3' -> {3}."""
    out: set[int] = set()
    for a, b in re.findall(r"(\d+)(?:\s*[–-]\s*(\d+))?", spec):
        out.update(range(int(a), int(b or a) + 1))
    return out


def legal_links(locator: str, source_id: str, legal: list[Chunk]) -> list[str]:
    """Jednostki redakcyjne aktu (chunks legal_json) objęte lokalizatorem fragmentu aplikacji, np. '§ 9 ust. 1 i 3'."""
    m = re.match(r"§\s*([\d\s–-]+?)(?:\s+ust\.\s*(.+))?$", locator.strip())
    if not m:
        return []
    paragraphs = _numbers(m.group(1))
    ustepy = _numbers(m.group(2)) if m.group(2) else set()
    ids = []
    for c in legal:
        if c.source_id != source_id or c.doc_type != "akt_prawny":
            continue
        cm = re.match(r"§\s*(\d+)(?:\s+ust\.\s*(\d+))?", c.citation)
        if not cm or int(cm.group(1)) not in paragraphs:
            continue
        if ustepy and cm.group(2) and int(cm.group(2)) not in ustepy:
            continue
        ids.append(c.id)
    return ids


def load_app_chunks(seed_dir: Path, corpus: list[Chunk]) -> list[Chunk]:
    kb = json.loads((seed_dir / "knowledge.json").read_text(encoding="utf-8"))
    intents = json.loads((seed_dir / "intents.json").read_text(encoding="utf-8"))
    chunks: list[Chunk] = []
    links: dict[str, list[str]] = {}
    for f in kb["fragments"]:
        source_id, doc_type, title, searchable = SOURCE_MAP[f["sourceId"]]
        linked = legal_links(f["locator"], source_id, corpus) if doc_type == "akt_prawny" else []
        links[f["id"]] = linked or [chunk_id(f["id"])]
        chunks.append(Chunk(
            id=chunk_id(f["id"]),
            text=f"{f['heading']} ({f['locator']}): {f['text']}",
            source_id=source_id, source_title=title, doc_type=doc_type, process=_process(f["paths"]),
            citation=f["locator"], chunk_type="app_fragment", authority=AUTHORITY[doc_type],
            extra={"heading": f["heading"], "display": f["text"], "searchable": searchable,
                   "app_fragment": f["id"], "linked_ids": linked},
        ))
    for intent in intents["formal"] + intents["conversation"]:
        questions = intent.get("phrases") or []
        answer = intent["answer"] + (" " + " ".join(intent.get("bullets") or []) if intent.get("bullets") else "")
        linked_ids = [cid for fid in intent["fragmentIds"] for cid in links.get(fid, [])]
        paths = intent["paths"] or ["periodic", "first"]
        chunks.append(Chunk(
            id=f"faq_kompas__{intent['id']}",
            text=f"Pytanie: {intent['id'].replace('-', ' ')}; {'; '.join(questions)}\nOdpowiedź: {answer}",
            source_id="faq_kompas", source_title="Pytania i odpowiedzi zespołu Kompas Kompetencji",
            doc_type="faq", process=_process(paths), citation=f"FAQ {intent['id']}", chunk_type="faq", authority=1,
            extra={"linked_ids": linked_ids, "heading": intent["id"].replace("-", " ").capitalize(),
                   "display": answer, "mode": intent["mode"], "tool_rule": bool(intent.get("toolRule"))},
        ))
    return chunks
