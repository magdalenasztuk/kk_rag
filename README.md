# Kompas Kompetencji — API

Backend aplikacji [Kompas Kompetencji](https://github.com/jakubGora/kompas-kompetencji):
sprawy ocen, pracownicy, dokumenty, powiadomienia, przypomnienia HR oraz asystent
odpowiadający na podstawie bazy wiedzy (przepisy, poradniki, FAQ) z cytatami źródeł.

## Produkcja (Vercel)

| | Adres |
|---|---|
| API | https://kompas-kompetencji-api.vercel.app |
| Aplikacja (front) | https://kompas-kompetencji.vercel.app |

Health: https://kompas-kompetencji-api.vercel.app/health

Stan demo jest w Postgresie (Neon), w jednej przestrzeni `default` — wszyscy jurorzy
widzą te same dane. `POST /api/demo/reset` przywraca dane startowe.

## Konta demonstracyjne

| Rola | Login | Hasło |
|------|-------|-------|
| Oceniający (Piotr Zieliński) | `piotr` | `piotr` |
| Kadry / HR (Marta Wiśniewska) | `marta` | `marta` |

Logowanie: `POST /api/auth/login` z `{ "login", "password" }` → Bearer token.
Bez tokenu pozostałe ścieżki `/api/*` zwracają 401.

## Co robi API

- Ścieżki ocen: start sprawy, autozapis sekcji, obserwacje, oceny cząstkowe, dokumenty, zakończenie kroków
- Pracownicy: lista, dodanie, zmiana umowy
- Kadry: lista procesów, przypomnienia, reguły terminów
- Asystent: pytanie → wyszukiwanie w bazie wiedzy → odpowiedź ze źródłami (albo jasna odmowa, gdy źródeł brak)
- Szkice w procesie (plan rozmowy, uzasadnienie) startują od reguł; model je uzupełnia, a przy błędzie zostaje wersja regułowa

Front Angular trzyma kontrakt 1:1 z tym API (test `tests/test_parity.py`).

## Uruchomienie lokalne

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # opcjonalnie ANTHROPIC_API_KEY — bez klucza asystent działa offline
KOMPAS_DENSE_ENABLED=false KOMPAS_USE_RERANKER=false \
  .venv/bin/uvicorn app.main:app --reload --port 8000
```

Front: w `kompas-web` ustaw proxy `/api` na `http://127.0.0.1:8000` i `npm start`.

## Zmienne środowiskowe (Vercel)

| Zmienna | Po co |
|---------|--------|
| `ANTHROPIC_API_KEY` | model asystenta i szkiców |
| `KOMPAS_AUTH_SECRET` | podpis tokenów logowania |
| `DATABASE_URL` / `POSTGRES_URL` | wspólny stan demo (Neon) |

Bez bazy używany jest SQLite lokalny (na Vercelu bez Neon dane nie są współdzielone między instancjami).

## Testy

```bash
.venv/bin/python -m pytest -q
```

`tests/test_parity.py` porównuje odpowiedzi z backendem demonstracyjnym frontu.
`tests/test_kompas_ai.py` sprawdza asystenta i szkice przy podstawionym modelu.
