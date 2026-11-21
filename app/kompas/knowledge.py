"""Baza wiedzy dla frontu: źródła i fragmenty z korpusu RAG (te same chunki, na których odpowiada asystent)."""
from __future__ import annotations

import re
from functools import lru_cache

from app.kompas.errors import not_found
from app.rag.index import Index, get_index
from app.rag.schema import Chunk

SOURCE_META: dict[str, dict] = {
    "rozp_2016": {"shortTitle": "Rozp. 2016 (oceny okresowe)", "kind": "przepis", "reference": "Dz. U. z 2016 r. poz. 470",
                  "description": "Warunki i sposób przeprowadzania ocen okresowych: kryteria, skala, rozmowa oceniająca, arkusze B i C."},
    "rozp_2015": {"shortTitle": "Rozp. 2015 (pierwsza ocena)", "kind": "przepis", "reference": "Dz. U. z 2015 r. poz. 1144",
                  "description": "Szczegółowe warunki i sposób dokonywania pierwszej oceny: elementy oceny, skala, warunki oceny pozytywnej, arkusz."},
    "ustawa_sc": {"shortTitle": "Ustawa o służbie cywilnej", "kind": "przepis", "reference": "Dz. U. z 2024 r. poz. 409 (wyciąg)",
                  "description": "Art. 81–84 i powiązane: kto podlega ocenie, terminy, sprzeciw, skutki oceny negatywnej."},
    "poradnik_okresowa": {"shortTitle": "Poradnik — ocena okresowa", "kind": "poradnik", "reference": "KPRM, DSC, wrzesień 2016",
                          "description": "Praktyka oceny okresowej: terminy, obserwacje, rozmowa, uzasadnienie, IPRZ."},
    "poradnik_pierwsza": {"shortTitle": "Poradnik — pierwsza ocena", "kind": "poradnik", "reference": "KPRM, DSC, wrzesień 2016",
                          "description": "Praktyka pierwszej oceny: okno terminu, rozmowa wstępna, skutki oceny."},
    "model_kompetencji": {"shortTitle": "Model kompetencji", "kind": "model", "reference": "Model kompetencji w służbie cywilnej",
                          "description": "14 kompetencji, 49 wskaźników behawioralnych, opisy zachowań na 5 poziomach."},
    "arkusze": {"shortTitle": "Wzory arkuszy", "kind": "wzor", "reference": "Zał. do rozp. 2016 i 2015",
                "description": "Części arkuszy oceny i pouczenia, które narzędzie wypełnia."},
    "reguly_narzedzia": {"shortTitle": "Reguły narzędzia", "kind": "regula-narzedzia", "reference": "Kompas Kompetencji",
                         "description": "Jak narzędzie liczy sugestie. To nie jest przepis — decyzja zawsze należy do oceniającego."},
    "faq": {"shortTitle": "FAQ — oceny w SC", "kind": "poradnik", "reference": "Opracowanie zespołu na podstawie przepisów",
            "description": "Najczęstsze pytania o pierwszą ocenę i ocenę okresową z odwołaniami do przepisów."},
    "faq_kompas": {"shortTitle": "FAQ Kompasu", "kind": "poradnik", "reference": "Opracowanie zespołu na podstawie przepisów",
                   "description": "Odpowiedzi asystenta przygotowane i sprawdzone przez zespół, z odwołaniami do przepisów."},
}
SOURCE_ORDER = list(SOURCE_META)
PATHS = {"okresowa": ["periodic"], "pierwsza": ["first"], "both": ["periodic", "first"]}
MAX_SEARCH = 30


def source_meta(source_id: str) -> dict:
    return SOURCE_META.get(source_id) or {"shortTitle": source_id, "kind": "poradnik", "reference": "", "description": ""}


def display_text(chunk: Chunk) -> str:
    """Tekst bez prefiksu „tytuł źródła, jednostka:”, który dodajemy tylko na potrzeby wyszukiwania."""
    if chunk.extra.get("display"):
        return chunk.extra["display"]
    text = chunk.text
    for marker in (f"{chunk.citation}: ", "”: "):
        pos = text.find(marker)
        if 0 <= pos < 200:
            return text[pos + len(marker):].strip()
    return text


def heading(chunk: Chunk) -> str:
    if chunk.extra.get("heading"):
        return chunk.extra["heading"]
    if chunk.doc_type == "model_kompetencji" and chunk.extra.get("competency"):
        comp = str(chunk.extra["competency"]).capitalize()
        return f"{comp} — wskaźnik {chunk.extra.get('indicator_no')}" if chunk.extra.get("indicator_no") else comp
    if chunk.doc_type == "poradnik":
        m = re.match(r"rozdz\. [\d.]*\s*(.+)", chunk.citation)
        return m.group(1) if m else chunk.citation
    return chunk.citation


def locator(chunk: Chunk) -> str:
    m = re.match(r"rozdz\. [\d.]+", chunk.citation) if chunk.doc_type == "poradnik" else None
    if m and chunk.page:
        return f"{m.group(0).capitalize()}, s. {chunk.page}"
    if chunk.page and chunk.doc_type == "poradnik":
        return f"{chunk.citation}, s. {chunk.page}"
    return chunk.citation


def fragment_dto(chunk: Chunk) -> dict:
    return {"id": chunk.id, "sourceId": chunk.source_id, "locator": locator(chunk), "heading": heading(chunk),
            "text": display_text(chunk), "paths": PATHS.get(chunk.process, PATHS["both"])}


def _visible(chunk: Chunk) -> bool:
    return chunk.extra.get("searchable", True) is not False


@lru_cache(maxsize=1)
def _index() -> Index:
    return get_index()


def sources() -> list[dict]:
    idx = _index()
    counts: dict[str, int] = {}
    titles: dict[str, str] = {}
    for c in idx.all_chunks:
        if _visible(c):
            counts[c.source_id] = counts.get(c.source_id, 0) + 1
            titles.setdefault(c.source_id, c.source_title)
    return [{"id": sid, "title": titles[sid], **{k: source_meta(sid)[k] for k in ("shortTitle", "kind", "reference", "description")},
             "fragmentCount": counts[sid]}
            for sid in sorted(counts, key=lambda s: SOURCE_ORDER.index(s) if s in SOURCE_ORDER else 99)]


def fragments(source_id: str | None = None, q: str | None = None) -> list[dict]:
    idx = _index()
    q = (q or "").strip()
    if q:
        ranked = [idx.by_id[cid] for cid, _ in idx.lexical(q, MAX_SEARCH * 2, None)]
        hits = [c for c in ranked if not source_id or c.source_id == source_id][:MAX_SEARCH]
        return [fragment_dto(c) for c in hits]
    if source_id:
        return [fragment_dto(c) for c in idx.all_chunks if c.source_id == source_id and _visible(c)]
    # Bez filtra: fragmenty wybrane do aplikacji (krótkie, z nagłówkami) — pełne akty są pod źródłami.
    return [fragment_dto(c) for c in idx.all_chunks if c.chunk_type == "app_fragment"]


def fragment(fragment_id: str) -> dict:
    chunk = _index().by_id.get(fragment_id)
    if not chunk:
        raise not_found("Nie ma takiego fragmentu źródła.")
    return fragment_dto(chunk)


def citation_for(chunk: Chunk, number: int | None = None, quote_len: int = 260) -> dict:
    from app.domain.text import truncate
    meta = source_meta(chunk.source_id)
    label = f"{locator(chunk)} • {meta['shortTitle']}"
    return {"fragmentId": chunk.id, "sourceId": chunk.source_id, "label": f"[{number}] {label}" if number else label,
            "kind": meta["kind"], "quote": truncate(display_text(chunk), quote_len)}
