# Kompas Kompetencji – backend aplikacji i asystenta AI (RAG)

Pełny backend aplikacji [Kompas Kompetencji](https://github.com/jakubGora/kompas-kompetencji) (Angular):
sprawy ocen (pierwsza ocena i ocena okresowa krok po kroku), kryteria i wskaźniki behawioralne, obserwacje,
oceny z sugestią narzędzia (decyduje przełożony), arkusze i zawiadomienia, terminy i przypomnienia dla HR,
rekrutacje — oraz asystent AI na RAG + Claude, który **odpowiada wyłącznie na podstawie źródeł, z cytatami**,
a gdy podstaw brak — mówi to wprost. Asystent nigdy nie wystawia ocen.

## Architektura

```
Angular (Vercel) ──/api/*──▶ FastAPI (Vercel, api/index.py)
                              ├─ /api/*      API aplikacji (app/kompas/routes) — kontrakt 1:1 z mockiem frontu
                              ├─ /api/v1/*   pierwotne API czatu RAG
                              └─ stan demo: przestrzeń robocza (JSON) na przeglądarkę → Postgres albo SQLite
```

- **Logowanie**: `POST /api/auth/login` (login + hasło kont demo) → Bearer token HMAC. Bez tokenu całe `/api/*`
  (poza `auth/login`, `auth/accounts`, `auth/logout`, health) zwraca 401 — chroni klucz Anthropic przed
  anonimowym użyciem. Konta: `piotr/piotr`, `marta/marta`, `ewa.mazur/ewa`, `karolina/karolina`,
  `tomasz/tomasz`, `adam/adam`.
- **Przestrzeń robocza**: każda przeglądarka wysyła `X-Kompas-Workspace` (losowe id z localStorage) i dostaje
  własną kopię danych demo — jurorzy nie nadpisują sobie spraw. Bez nagłówka: cookie `kompas_ws`, potem `default`.
- **Magazyn**: `DATABASE_URL` / `POSTGRES_URL` (np. Neon z integracji Vercel) → tabela `kompas_workspaces` (JSONB);
  bez niej SQLite (`/tmp/kompas` na Vercelu — działa, ale nie jest współdzielony między instancjami funkcji).
- **Asystent** (`app/kompas/ai/assistant.py`): strażnicy (pytania o ocenę konkretnej osoby, cechy osobowości,
  poza zakresem) → Claude Haiku przepisuje pytanie na samodzielne + 2 parafrazy słownictwem przepisów →
  BM25 × zapytania, RRF, boost FAQ, dociąganie cytowanych § → Claude Sonnet (JSON: odpowiedź, punkty, cytaty
  `[n]`, odmowa) → walidacja i przenumerowanie cytatów. Do modelu trafia spseudonimizowany kontekst sprawy
  (krok, kryteria, oceny, obserwacje — bez nazwisk); konta HR nie wysyłają treści spraw.
- **Bez klucza / przy błędzie modelu** asystent działa dalej: pytanie z bazy zespołu wybrane BM25, a gdy jej
  brak — dosłowne fragmenty źródeł z cytatami, jasno oznaczone jako tryb offline. Ostatni błąd modelu widać
  w `GET /api/assistant/status`.
- **AI w krokach** (`app/kompas/ai/enrich.py`): analiza obserwacji, plan rozmowy, szkic uzasadnienia i planu
  rozwoju — zawsze startują od wersji regułowej i do niej wracają przy błędzie; szkice są oznaczone
  „do weryfikacji”.

## Uruchomienie lokalne (z frontem)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # ANTHROPIC_API_KEY=... (bez klucza asystent działa w trybie offline)
KOMPAS_DENSE_ENABLED=false KOMPAS_USE_RERANKER=false .venv/bin/uvicorn app.main:app --reload --port 8000
# w kompas-web: npm start  → http://127.0.0.1:4300 (proxy /api → :8000)
```

## Wdrożenie na Vercel

1. Projekt Vercel z tego repo (root = katalog repo). Vercel wykrywa FastAPI (`api/index.py`), Python 3.12
   i zależności z `pyproject.toml` / `uv.lock` (lekki zestaw: BM25 + SDK Anthropic, bez modeli ML).
2. Zmienne środowiskowe: `ANTHROPIC_API_KEY` (wymagany dla Claude), `KOMPAS_AUTH_SECRET` (losowy podpis
   tokenów logowania), opcjonalnie `DATABASE_URL` (Storage → Neon Postgres; zalecane przy wielu instancjach).
3. Front (`kompas-web/vercel.json`) przekierowuje `/api/:path*` na domenę backendu
   (`https://kompas-kompetencji-api.vercel.app` — przy innej nazwie projektu zmień ten adres).
4. Sprawdzenie wdrożenia tym samym scenariuszem co testy (143 żądania):
   `KOMPAS_E2E_URL=https://<backend>.vercel.app .venv/bin/python -m pytest tests/test_deployed.py -q`

## Testy

`tests/test_parity.py` odtwarza pełny flow z Figmy (ocena okresowa, pierwsza ocena, HR, rekrutacje, błędy
walidacji) i porównuje odpowiedzi z backendem demonstracyjnym frontu (`npm run parity:trace` w kompas-web
generuje `tests/parity/expected.json`). `tests/test_kompas_ai.py` sprawdza asystenta i szkice AI z
podstawionym modelem (cytowania, odmowa, walidacja, tryb awaryjny).

```bash
.venv/bin/python -m pytest -q
```

## Pierwotny moduł RAG (`/api/v1`, pełny zestaw z embeddingami)

`requirements-ml.txt` (Chroma, sentence-transformers, litellm) — używany przez `Dockerfile` i ewaluację.

## Szybki start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ml.txt
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
| `legal_json/rozp_2015_pierwsza_ocena.json` | rozporządzenie 2015 (pierwsza ocena) | jak rozporządzenie 2016 |
| `app/kompas/seed/knowledge.json` | reguły narzędzia i baza pytań aplikacji | 1 chunk = 1 fragment (`kompas__*`) / 1 pytanie (`faq_kompas__*`); reguły narzędzia oznaczone jako „nie przepis” |

**TODO:** wkleić dosłowne brzmienie art. 81/83/89 ustawy z ISAP do `ustawa_sc_wyciag.json`
(obecnie odtworzone z poradnika).

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
