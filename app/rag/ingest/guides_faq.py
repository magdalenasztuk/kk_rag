"""Poradniki KPRM (PDF -> sekcje po nagłówkach -> okna ~450 tokenów) oraz FAQ (1 chunk = 1 Q&A)."""
import json
import re
from pathlib import Path
from app.rag.schema import Chunk
from app.rag.ingest.xlsx_model import _slug

WATERMARK_RE = re.compile(r"^\s*(v\.p|rcl|ww|\.go|l|w\.)\s*$", re.M)   # śmieci z PDF Dziennika Ustaw
HEADING_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<title>[A-ZĄĆĘŁŃÓŚŹŻ][^\n]{3,90})$", re.M)


def clean_pdf_text(text: str) -> str:
    text = WATERMARK_RE.sub("", text)
    text = re.sub(r"-\n(?=[a-ząćęłńóśźż])", "", text)          # de-hyphenate line breaks
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def pdf_to_pages(path: Path) -> list[str]:
    from pypdf import PdfReader
    return [clean_pdf_text(p.extract_text() or "") for p in PdfReader(str(path)).pages]


def _approx_tokens(s: str) -> int:
    return int(len(s.split()) * 1.5)


def split_paragraph_windows(text: str, max_tokens: int = 450, overlap_tokens: int = 70) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    windows, cur = [], []
    for p in paras:
        if cur and _approx_tokens(" ".join(cur + [p])) > max_tokens:
            windows.append("\n\n".join(cur))
            # overlap: keep trailing paragraphs up to overlap_tokens
            tail, acc = [], 0
            for q in reversed(cur):
                if acc + _approx_tokens(q) > overlap_tokens:
                    break
                tail.insert(0, q); acc += _approx_tokens(q)
            cur = tail
        cur.append(p)
    if cur:
        windows.append("\n\n".join(cur))
    return windows


def load_guide_chunks(path: Path, source_id: str, source_title: str, process: str) -> list[Chunk]:
    pages = pdf_to_pages(path)
    # join with page markers to recover page numbers later
    joined = "".join(f"\n\x0c{i+1}\n{t}" for i, t in enumerate(pages))
    # split on headings
    parts, last, cur_heading = [], 0, "Wstęp"
    for m in HEADING_RE.finditer(joined):
        parts.append((cur_heading, joined[last:m.start()]))
        cur_heading, last = f"{m.group('num')} {m.group('title').strip()}", m.end()
    parts.append((cur_heading, joined[last:]))

    chunks: list[Chunk] = []
    seen: dict[str, int] = {}
    for heading, body in parts:
        page_hits = re.findall(r"\x0c(\d+)\n", body)
        page = int(page_hits[0]) if page_hits else None
        body = re.sub(r"\x0c\d+\n", "\n", body).strip()
        body = re.sub(r"(?m)^\d{1,2}\s*$\n?", "", body)   # stray page numbers
        if len(body) < 80:
            continue
        hslug = _slug(heading)[:48]
        seen[hslug] = seen.get(hslug, 0) + 1
        parent_id = f"{source_id}__{hslug}" + (f"_v{seen[hslug]}" if seen[hslug] > 1 else "")
        windows = split_paragraph_windows(body)
        for i, w in enumerate(windows, start=1):
            is_example = bool(re.search(r"\b(np\.|Przykład|został zatrudniony|została zatrudniona)\b", w)) and len(windows) > 1
            chunks.append(Chunk(
                id=f"{parent_id}__{i}",
                text=f"{source_title} – rozdział „{heading}”: {w}",
                source_id=source_id, source_title=source_title, doc_type="poradnik", process=process,
                citation=f"rozdz. {heading}", page=page,
                parent_id=parent_id if len(windows) > 1 else None,
                parent_text=body if len(windows) > 1 and _approx_tokens(body) < 1800 else None,
                chunk_type="example" if is_example else "section", authority=2,
            ))
    return chunks


def load_faq_chunks(path: Path) -> list[Chunk]:
    """faq.jsonl: {"id","question","answer","alt_questions":[],"process","citations":["§ 5 ust. 2"]}"""
    chunks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        alts = " | ".join(q.get("alt_questions", []))
        chunks.append(Chunk(
            id=f"faq__{q['id']}",
            text=f"Pytanie: {q['question']}" + (f" (inaczej: {alts})" if alts else "") + f"\nOdpowiedź: {q['answer']}",
            source_id="faq", source_title="Zestaw pytań i odpowiedzi – Kompas Kompetencji",
            doc_type="faq", process=q.get("process", "both"), citation=f"FAQ {q['id']}",
            chunk_type="faq", authority=1, extra={"citations": q.get("citations", [])},
        ))
    return chunks
