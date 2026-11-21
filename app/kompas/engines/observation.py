"""Analiza notatki z obserwacji: fakty vs. opinie, powiązanie ze wskaźnikami modelu, tytuł i zadanie z OSP.

Heurystyka działa zawsze (offline); gdy dostępny jest model językowy, `app.kompas.ai.enrich` ją uszczegóławia.
"""
from __future__ import annotations

import re
import unicodedata

from app.domain.text import collapse_whitespace, fold, match_stems, normalize

INDICATOR_STEMS: dict[str, list[str]] = {
    "c01-i01": ["procedur", "standard", "zgodnie z", "jakosc", "poprawn", "bled", "dokladn", "rzeteln"],
    "c01-i02": ["termin", "w czasie", "opozni", "harmonogram", "na czas", "zobowiaz"],
    "c02-i01": ["wysluch", "dopytal", "upewnil", "zrozumieni", "sluchal"],
    "c02-i02": ["wyjasnil", "przedstawil", "omowil", "ustnie", "spotkani"],
    "c02-i03": ["pism", "notatk", "komunikat", "raport", "e-mail", "mail", "liste ustalen", "lista ustalen"],
    "c02-i04": ["argument", "przekonal", "uzasadnil", "rekomend"],
    "c03-i01": ["wiedz", "przepis", "ustaw", "znajomosc", "ekspert"],
    "c03-i02": ["szkoleni", "kurs", "nauczyl", "doskonal", "certyfikat", "aktualizacj"],
    "c03-i03": ["zrodl", "narzedzi", "system", "baz", "dane z", "technologi"],
    "c04-i01": ["plan", "harmonogram", "kamieni", "rozpisal", "sposob realizacji"],
    "c04-i02": ["priorytet", "pilne", "kolejnosc", "wazn"],
    "c04-i03": ["zasob", "wlascicieli", "przypisal", "podzial", "odpowiedzialn"],
    "c04-i04": ["zmian", "dostosow", "elastyczn", "nieprzewidzian"],
    "c04-i05": ["zaangazow", "wytrwal", "mimo", "doprowadzil", "dokonczyl"],
    "c05-i01": ["zaproponowal", "nowe rozwiazani", "usprawnieni", "pomysl", "wariant"],
    "c05-i02": ["nietypow", "niestandardow", "inaczej", "kreatywn"],
    "c06-i01": ["wlaczyl", "wspolnie", "razem", "pomogl", "wsparl", "zespol"],
    "c06-i02": ["przekazal", "rozeslal", "poinformowal", "liste ustalen", "lista ustalen", "przeplyw", "uzgodni"],
    "c06-i03": ["atmosfer", "otwart", "zyczliw"],
    "c06-i04": ["docenil", "podziekowal", "wklad"],
    "c06-i05": ["uwzglednil", "opinie", "zdanie", "konsultowal"],
    "c06-i06": ["podzielil", "wskazowki", "przeszkolil", "instrukcj", "omowienie"],
    "c07-i01": ["istotn", "kluczow", "rozroz", "wyselekcjon"],
    "c07-i02": ["zaleznosc", "rozbieznos", "zestawil", "porownal", "przyczyn"],
    "c07-i03": ["wniosk", "rekomendacj", "zidentyfikowal", "ocenil"],
    "c08-i01": ["stanowisko negocjacyjn", "ustepstw", "mandat"],
    "c08-i02": ["negocj", "kompromis"],
    "c08-i03": ["porozumieni", "uzgodnil z"],
    "c09-i01": ["prezentacj", "slajd", "multimedi"],
    "c09-i02": ["audytori", "uczestnik", "sala"],
    "c09-i03": ["czas wystapienia", "ramy czasowe", "zmiescil sie"],
    "c09-i04": ["trudne pytani", "krytyk", "stres"],
    "c10-i01": ["takt", "szacun", "uprzejm"],
    "c10-i02": ["potrzeb", "klient", "interesant", "wnioskodawc"],
    "c11-i01": ["incydent", "kryzys", "alarm", "powiadomil", "eskalac", "dyzurn", "rcb", "zglosil"],
    "c11-i02": ["reagow", "opanowal", "dzialania naprawcze", "zabezpiecz", "ograniczyl skutki"],
    "c11-i03": ["wnioski z incydent", "po incydencie", "lessons learned", "poprawi procedur", "szablon komunikatu"],
    "c12-i01": ["wizj", "cele strategiczne", "strategi"],
    "c12-i02": ["cele operacyjne", "plan dzialan"],
    "c12-i03": ["analiza ryzyka", "ryzyko strategiczne"],
    "c13-i01": ["delegowal", "przydzielil"],
    "c13-i02": ["monitorowal", "korygujac", "nadzorowal"],
    "c13-i03": ["motywow", "zaangazowal zespol"],
    "c13-i04": ["informacje zwrotna", "informacji zwrotnej", "feedback"],
    "c13-i05": ["konflikt", "spor"],
    "c13-i06": ["rozwoj pracownik", "potrzeby rozwojowe", "mentoring"],
    "c14-i01": ["warianty", "alternatyw", "ryzyk", "opcj"],
    "c14-i02": ["zdecydowal", "decyzj", "wybral"],
    "c14-i03": ["odpowiedzialnosc", "wziela na siebie", "wzial na siebie", "przyjela odpowiedzialnosc"],
}

OPINION_PATTERNS = [re.compile(p) for p in (
    r"\bslabo\b", r"\bzle\b", r"\bzawsze\b", r"\bnigdy\b", r"\bleniw\w*", r"\bnie potrafi\b", r"\bnie umie\b",
    r"\bswietn\w*", r"\bbeznadziej\w*", r"\bnie nadaje\b", r"\bkonfliktow\w*", r"\bmalo zaangazowan\w*",
    r"\bkiepsk\w*", r"\bciagle\b", r"\bnieodpowiedzialn\w*", r"\barogan\w*", r"\bemocjonaln\w*",
    r"\bcharakter\w*", r"\bosobowos\w*",
)]

RESULT_STEMS = ["w terminie", "w efekcie", "dzieki", "skutk", "rezultat", "przyjeto", "przyjal", "zaakcept",
                "zakonczon", "udalo", "jednak", "bez uwag", "wczesniej", "opozni", "liste ustalen", "warianty"]

MIN_BEHAVIOR_LENGTH = 25
TITLE_LIMIT, TITLE_MIN = 60, 15
_TRAILING_WORD = re.compile(r"^(?:i|oraz|a|w|z|na|do|o|od|po|przy|dla)$", re.I)


def find_opinion_phrases(text: str) -> list[str]:
    original = unicodedata.normalize("NFC", text)
    folded = fold(original)  # fold() zachowuje długość tekstu w NFC, więc indeksy wskazują oryginał
    found: list[str] = []
    for pattern in OPINION_PATTERNS:
        m = pattern.search(folded)
        if m:
            phrase = original[m.start():m.end()]
            if phrase not in found:
                found.append(phrase)
    return found


def _has_result(description: str) -> bool:
    return bool(match_stems(description, RESULT_STEMS)) or bool(re.search(r"[;,]", description))


def coach_observation(draft: dict) -> dict:
    description = collapse_whitespace(draft.get("description") or "")
    flagged = find_opinion_phrases(" ".join(x for x in (draft.get("title"), description) if x))
    missing: list[str] = []
    if not draft.get("date"):
        missing.append("data")
    if len(description) < MIN_BEHAVIOR_LENGTH:
        missing.append("zachowanie")
    elif not _has_result(description):
        missing.append("rezultat")
    questions = []
    if "data" in missing:
        questions.append("Kiedy dokładnie to było? Podaj datę albo przybliżony tydzień.")
    if "zachowanie" in missing:
        questions.append("Co konkretnie zrobił(a) pracownik i przy jakim zadaniu? Opisz zachowanie, które można było "
                         "zobaczyć lub usłyszeć.")
    if "rezultat" in missing:
        questions.append("Jaki był skutek dla zadania, terminu, zespołu lub odbiorcy?")
    for phrase in flagged[:2]:
        questions.append(f"Zamiast „{phrase}” opisz zachowanie: co dokładnie zostało powiedziane lub zrobione?")
    if flagged and missing:
        return {"quality": "ocena-zamiast-faktu",
                "message": "To raczej ocena niż obserwacja. Opisz konkretną sytuację: kiedy to było, co zrobił(a) "
                           "pracownik i jaki był skutek. Opinia bez faktu nie powinna podnosić ani obniżać oceny.",
                "missing": missing, "flaggedPhrases": flagged, "questions": questions}
    if missing or flagged:
        return {"quality": "do-uzupelnienia",
                "message": ("Notatka zawiera określenia oceniające. Zostaw fakty — zachowanie i jego skutek." if flagged
                            else "Uzupełnij notatkę, żeby była konkretnym przykładem: zadanie, zachowanie i jego rezultat."),
                "missing": missing, "flaggedPhrases": flagged, "questions": questions}
    return {"quality": "konkretna",
            "message": "Notatka opisuje zachowanie i jego rezultat — nadaje się jako przykład do oceny.",
            "missing": [], "flaggedPhrases": [], "questions": []}


def suggest_title(description: str) -> str:
    sentence = (re.split(r"[.;:!?,]", collapse_whitespace(description))[0] or "").strip()
    clause = re.split(r"\s(?:i|oraz|a|ale|lecz)\s", sentence)[0] if sentence else sentence
    base = clause if len(clause) >= TITLE_MIN else sentence
    words = base.split(" ") if len(base) <= TITLE_LIMIT else base[: TITLE_LIMIT + 1].split(" ")[:-1]
    while len(words) > 1 and _TRAILING_WORD.match(words[-1] or ""):
        words.pop()
    title = " ".join(words)
    return title[:1].upper() + title[1:]


def suggest_task(description: str, tasks: list[dict]) -> str | None:
    haystack = normalize(description)
    scored = []
    for task in tasks:
        stems = {w[:6] for w in re.split(r"[^a-z0-9]+", normalize(task["text"])) if len(w) >= 6}
        hits = sum(1 for s in stems if s in haystack)
        if hits >= 2:
            scored.append((hits, task["id"]))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored else None


def match_indicators(draft: dict, criteria: list[str]) -> list[dict]:
    text = " ".join(x for x in (draft.get("title"), draft.get("description")) if x)
    allowed = set(criteria)
    entries = [(iid, match_stems(text, stems)) for iid, stems in INDICATOR_STEMS.items() if iid[:3] in allowed]
    entries = sorted([e for e in entries if e[1]], key=lambda e: -len(e[1]))[:4]
    return [{"criterionId": iid[:3], "indicatorId": iid,
             "confidence": "wysoka" if len(hits) >= 3 else "srednia" if len(hits) == 2 else "niska",
             "matchedPhrases": hits} for iid, hits in entries]


def analyze_observation(draft: dict, criteria: list[str], tasks: list[dict], analyzed_at: str) -> dict:
    description = draft.get("description") or ""
    task_id = suggest_task(description, tasks)
    return {
        "coaching": coach_observation(draft),
        "matches": match_indicators(draft, criteria),
        "suggestedTitle": (draft.get("title") or "").strip() or suggest_title(description),
        **({"suggestedTaskId": task_id} if task_id else {}),
        "analyzedAt": analyzed_at,
    }
