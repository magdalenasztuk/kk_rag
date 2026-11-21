"""Model kompetencji (XLSX) -> chunks.

Sheet 0: overview (rules in header rows + table Lp./Kompetencja/Liczba wskaźników)
Sheets 1..14: one per competency; row 3 = header with 5 levels, rows 4.. = indicators.
"""
import re
from pathlib import Path
import openpyxl
from app.rag.schema import Chunk

SOURCE_ID = "model_kompetencji"
SOURCE_TITLE = "Model kompetencji – służba cywilna (14 kompetencji, 49 wskaźników, 5 poziomów)"
LEVELS = ["znacznie poniżej oczekiwań", "poniżej oczekiwań", "na poziomie oczekiwań",
          "powyżej oczekiwań", "znacznie powyżej oczekiwań"]
POINTS = {0: 1, 1: 3, 2: 5, 3: 7, 4: 9}


def _slug(s: str) -> str:
    s = s.lower()
    s = (s.replace("ą", "a").replace("ć", "c").replace("ę", "e").replace("ł", "l").replace("ń", "n")
         .replace("ó", "o").replace("ś", "s").replace("ż", "z").replace("ź", "z"))
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def load_model_chunks(path: Path) -> list[Chunk]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    chunks: list[Chunk] = []

    # --- sheet 0: rules + competency list ---
    ws0 = wb.worksheets[0]
    rows0 = [[_clean(c) for c in r] for r in ws0.iter_rows(values_only=True)]
    rules = []
    for r in rows0[:8]:
        if r and r[0] and not r[0].startswith("MODEL") and not r[0].startswith("Lp") and len(r[0]) > 25:
            rules.append(r[0])
    rules = list(dict.fromkeys(rules))
    chunks.append(Chunk(
        id="model__rules",
        text="Model kompetencji – zasady stosowania: " + " ".join(rules),
        source_id=SOURCE_ID, source_title=SOURCE_TITLE, doc_type="model_kompetencji",
        process="both", citation="Zasady stosowania modelu", chunk_type="model_rules", authority=2,
    ))

    # --- per-competency sheets ---
    for ws in wb.worksheets[1:]:
        rows = [[_clean(c) for c in r] for r in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        comp_name = rows[0][0]
        comp_slug = _slug(comp_name)
        header_idx = next(i for i, r in enumerate(rows) if r and r[0].lower().startswith("wskaźnik"))
        indicators = [r for r in rows[header_idx + 1:] if r and r[0]]

        ind_lines = []
        for k, r in enumerate(indicators, start=1):
            indicator = r[0]
            levels = r[1:6]
            ind_lines.append(f"{k}. {indicator}")
            level_txt = "\n".join(f"- {LEVELS[i]} ({POINTS[i]} pkt): {levels[i]}" for i in range(5) if i < len(levels))
            chunks.append(Chunk(
                id=f"model__{comp_slug}__wsk{k}",
                text=(f"Model kompetencji – kompetencja: {comp_name}. Wskaźnik behawioralny {k}: {indicator}\n"
                      f"Opis zachowań na poszczególnych poziomach oceny:\n{level_txt}"),
                source_id=SOURCE_ID, source_title=SOURCE_TITLE, doc_type="model_kompetencji",
                process="both", citation=f"{comp_name} / wskaźnik {k}", chunk_type="indicator_full",
                parent_id=f"model__{comp_slug}", authority=2,
                extra={"competency": comp_name, "indicator": indicator, "indicator_no": k,
                       "levels": {LEVELS[i]: levels[i] for i in range(5) if i < len(levels)}},
            ))
        chunks.append(Chunk(
            id=f"model__{comp_slug}",
            text=(f"Model kompetencji – kompetencja: {comp_name}. Liczba wskaźników behawioralnych: {len(indicators)}. "
                  f"Wskaźniki: " + "; ".join(ind_lines) + ". Każdy wskaźnik oceniany jest na skali 5 poziomów: "
                  + ", ".join(LEVELS) + "."),
            source_id=SOURCE_ID, source_title=SOURCE_TITLE, doc_type="model_kompetencji",
            process="both", citation=comp_name, chunk_type="competency_overview", authority=2,
            extra={"competency": comp_name, "indicator_count": len(indicators)},
        ))
    return chunks


if __name__ == "__main__":
    import sys, json
    for c in load_model_chunks(Path(sys.argv[1])):
        print(json.dumps(c.model_dump(), ensure_ascii=False)[:300])
