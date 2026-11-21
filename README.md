# Kompas Kompetencji – backend asystenta AI (RAG)

FastAPI + ChromaDB + BM25 + reranker + Claude (przez litellm). Odpowiada na pytania o pierwszą ocenę
i ocenę okresową w służbie cywilnej **wyłącznie na podstawie bazy wiedzy, z cytowaniem źródeł**,
pamięta kontekst rozmowy, a gdy nie ma podstaw – mówi to wprost.

## Szybki start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # wpisz ANTHROPIC_API_KEY
python -m scripts.ingest        # buduje data/chunks.jsonl + kolekcję Chroma (pobiera bge-m3 ~2 GB za 1. razem)
uvicorn app.main:app --reload --port 8000
```

```bash
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "session_id": "demo-1",
  "message": "Ile kryteriów dodatkowych mogę wybrać?",
  "mode": "formal",
  "context": {"process": "okresowa", "arkusz": "C", "step": "kryteria"}
}' | jq
```

Tryby awaryjne (demo bez sieci): `KOMPAS_DENSE_ENABLED=false` (tylko BM25, bez modelu embeddingów),
`KOMPAS_USE_RERANKER=false`, `KOMPAS_LLM_PROVIDER=ollama` (lokalny Bielik) lub `mock` (smoke test).

## Źródła wiedzy (data/)

| katalog | co | jak powstaje chunk |
|---|---|---|
| `legal_json/` | rozporządzenie 2016 (ocena okresowa), wyciąg z ustawy o SC | **ręcznie zweryfikowany JSON**: 1 chunk = 1 ustęp/pkt, rodzic = §; załącznik nr 1 = 1 chunk/kryterium; arkusz C = sekcje + przypisy |
| `raw/Model_kompetencji.xlsx` | model kompetencji | 1 chunk zasad + 14 przeglądów kompetencji + 49 wskaźników (każdy z 5 poziomami) |
| `raw/poradnik_*.pdf` | poradniki KPRM | podział po nagłówkach → okna ~450 tokenów, overlap ~70; ramki z przykładami = `example` |
| `faq/*.jsonl` | FAQ (Q+A+parafrazy+cytowania §) | 1 chunk = 1 Q&A; trafiony FAQ **dociąga cytowane § do kontekstu** |

**TODO przed demo:** dodać `legal_json/rozp_2015_pierwsza_ocena.json` (ta sama struktura) oraz wkleić
dosłowne brzmienie art. 81/83/89 ustawy z ISAP do `ustawa_sc_wyciag.json` (obecnie odtworzone z poradnika).

## Pipeline odpowiedzi

historia (SQLite, 6 ostatnich wiadomości) → **condense** pytania (Haiku) → **hybrid retrieval**
(Chroma/bge-m3 top-20 + BM25 top-20 z lematyzacją PL) → RRF (+boost 1 najlepszego FAQ, dywersyfikacja)
→ **reranker** bge-reranker-v2-m3 → próg abstain (`KOMPAS_ABSTAIN_THRESHOLD`, kalibrować na golden secie)
→ parent expansion dla aktów prawnych → **Claude Sonnet** (JSON: answer + citations + abstained)
→ walidacja cytowań `[n]` → zapis tury + trace (`data/traces.jsonl`).

Tryb `conversation` (asystent rozmowy) używa tego samego retrievalu z innym promptem i kontekstem
aplikacji (OSP, kryteria, notatki, wybrane poziomy) przekazywanym w `context`.

## API

| metoda | ścieżka | opis |
|---|---|---|
| POST | `/api/v1/chat` | pytanie → `{answer, citations[], abstained, confidence, rewritten_query, trace_id}` |
| POST | `/api/v1/chat/stream` | to samo jako SSE (`token`, `citations`, `done`) |
| GET/DELETE | `/api/v1/sessions/{id}` | historia / reset sesji |
| GET | `/api/v1/sources/{chunk_id}` | pełny fragment + rodzic (klik w cytat w UI) |
| POST | `/api/v1/admin/ingest` | przebudowa indeksu (`X-Admin-Token`) |
| GET | `/health` | status |

## Ewaluacja (golden dataset)

```bash
python -m eval.run_eval --retrieval-only --tag bge_hybrid      # recall@5 / MRR, bez LLM
python -m eval.run_eval --judge --tag bge_hybrid_rerank        # pełne metryki + sędzia LLM
```
`eval/golden.jsonl` – 40 pozycji: reguły, terminy, procedura, arkusz, model kompetencji, poradnik,
**5 pułapek** (`should_abstain`), 2 pytania o pierwszą ocenę (TODO), 3 scenariusze wieloturowe.
Metryki: recall@5, MRR, must_include, abstain-recall na pułapkach, answer-rate na zwykłych pytaniach,
citation-hit, judge 0–2, latencja p50/p95. Wyniki lądują w `eval/results/`.

Baseline **BM25-only, bez rerankera** (bez pobierania modeli): recall@5 = 0.59, MRR = 0.24.
To jest punkt odniesienia – hybrid + reranker powinien dać ≥0.85 recall@5; jeśli nie, pierwsze
podejrzane: brak chunków dla pierwszej oceny i słabe trafienia na pytania wieloturowe bez condense.

## Kolejność eksperymentów (każdy ≈30 min)

1. BM25 → hybrid (dense+BM25) 2. bge-m3 vs `Qwen/Qwen3-Embedding-0.6B` vs `sdadas/mmlw-retrieval-roberta-large`
3. z rerankerem / bez 4. okno poradnika 300 vs 450 5. próg abstain (patrz pułapki vs answer-rate).

## Przed produkcją (do opisu architektury)

uwierzytelnianie (SSO/AD) i role; RODO – w bazie wiedzy nie ma danych osobowych, dane pracownika z
`context` nie są logowane poza trace (wyłączyć lub pseudonimizować); rate-limit; LLM on-prem (Bielik)
lub umowa DPA; wersjonowanie bazy wiedzy; integracja EZD/QNT przez `/sources` i webhooki.
