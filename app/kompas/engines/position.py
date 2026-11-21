"""Analiza OSP: rekomendacja arkusza (reguła z § 3) i propozycje kryteriów dodatkowych z cytatami."""
from __future__ import annotations

from app.domain.criteria import CRITERIA, MANDATORY_CRITERIA
from app.domain.text import match_stems, normalize, sentences, truncate

ANALYZER_MODEL = "Kompas — reguły § 3 + analiza treści OSP"

SIGNALS = [
    ("c11", ["kryzys", "incydent", "alarm", "zagrozen", "dyzur", "reagowani"],
     "Zadania obejmują zarządzanie kryzysowe i reagowanie na incydenty."),
    ("c07", ["analiz", "dokonuje oceny", "interpretac", "rozbieznos", "identyfik", "formuluje opini"],
     "Stanowisko wymaga analizy informacji i formułowania wniosków."),
    ("c14", ["samodzielne podejmowanie decyzji", "decyzji uznaniowych", "decyzje", "autonomicznych decyzji"],
     "OSP wskazuje na samodzielne podejmowanie decyzji."),
    ("c08", ["negocj", "reprezentowania rp", "reprezentuje", "uzgodnien", "przekonywania", "godzenie interesow"],
     "Zadania obejmują reprezentowanie urzędu i uzgadnianie stanowisk z partnerami."),
    ("c09", ["wystapien", "konferencj", "prezentac", "prowadzi szkolenia", "seminari"],
     "Stanowisko wiąże się z wystąpieniami i prowadzeniem szkoleń."),
    ("c10", ["klient", "interesant", "odpowiedzi na pisma", "odpowiedzi na zapytania", "udziela odpowiedzi"],
     "Zadania obejmują obsługę zapytań odbiorców zewnętrznych lub wewnętrznych."),
    ("c05", ["nowych rozwiazan", "nowe koncepcje", "nowych zasad", "innowac", "propozycje zmian", "usprawni"],
     "Od osoby na stanowisku oczekuje się proponowania nowych rozwiązań."),
    ("c12", ["strateg", "polityki", "perspektyw", "wizj"], "Zadania mają wymiar strategiczny lub polityczny."),
    ("c03", ["wiedzy eksperckiej", "specjalistyczna wiedze", "ekspert"], "Stanowisko wymaga wiedzy eksperckiej."),
    ("c01", ["rzeteln", "terminow", "kontrol", "procedur"], "Zadania wymagają rzetelności i zgodności z procedurami."),
]


def _score_signal(position: dict, stems: list[str]) -> tuple[float, list[dict]]:
    score, evidence = 0.0, []
    for task in position["tasks"]:
        hits = match_stems(task["text"], stems)
        if hits:
            dominant = task["kind"] == "dominujace"
            score += len(hits) * (3 if dominant else 2)
            evidence.append({"text": truncate(task["text"]),
                             "location": f"Zadanie {task['no']} ({'dominujące' if dominant else 'pozostałe'})",
                             "taskId": task["id"]})
    extra = [
        ("Niezbędna samodzielność i inicjatywa", position.get("independence", "")),
        ("Upoważnienia i pełnomocnictwa", ". ".join(position.get("authorizations", []))),
        ("Cel istnienia stanowiska", position.get("purpose", "")),
    ]
    for location, text in extra:
        for sentence in sentences(text):
            hits = match_stems(sentence, stems)
            if hits:
                score += len(hits)
                evidence.append({"text": truncate(sentence), "location": location})
    return score, evidence


def _confidence(score: float) -> str:
    return "wysoka" if score >= 7 else "srednia" if score >= 3 else "niska"


def recommend_variant(position: dict) -> tuple[str, str]:
    if position["subordinates"]["range"] != "brak":
        return "B", ("OSP wskazuje, że praca na stanowisku polega na bezpośrednim kierowaniu pracownikami — "
                     "właściwy jest arkusz B.")
    return "C", ("OSP wskazuje brak podległych pracowników i stanowisko nie jest stanowiskiem kierownika urzędu — "
                 "właściwy jest arkusz C.")


def analyze_position(position: dict, analyzed_at: str) -> dict:
    variant, rationale = recommend_variant(position)
    mandatory = set(MANDATORY_CRITERIA[variant])
    scored = []
    for cid, stems, why in SIGNALS:
        if cid in mandatory:
            continue
        score, evidence = _score_signal(position, stems)
        soft = next((s for s in position.get("softCompetencies", []) if normalize(s) == normalize(CRITERIA[cid]["name"])), None)
        if soft:
            score += 3
            evidence.append({"text": soft, "location": "Wymagane kompetencje miękkie"})
        if score > 0 and evidence:
            scored.append((score, cid, why, evidence[:3]))
    scored.sort(key=lambda x: -x[0])
    suggestions = [{"criterionId": cid, "confidence": _confidence(score), "rationale": why, "evidence": evidence}
                   for score, cid, why, evidence in scored[:5]]
    warnings = []
    unmatched = [s for s in position.get("softCompetencies", [])
                 if not any(normalize(c["name"]) == normalize(s) for c in CRITERIA.values())]
    if unmatched:
        warnings.append(f"Nie rozpoznano kompetencji z OSP: {', '.join(unmatched)}.")
    if not position.get("fromOrganizer"):
        warnings.append("Opis stanowiska jest danymi demonstracyjnymi przygotowanymi na wzór OSP organizatora.")
    return {
        "analyzedAt": analyzed_at,
        "model": ANALYZER_MODEL,
        "recommendedVariant": variant,
        "variantRationale": rationale,
        "variantEvidence": [
            {"text": position["subordinates"]["quote"], "location": "Liczba podległych pracowników"},
            {"text": f"Stanowisko bezpośrednio nadzorujące: {position['supervisedBy']['direct']}",
             "location": "Miejsce stanowiska w strukturze"},
        ],
        "legalBasis": "§ 3 ust. 3 i § 4 ust. 2 rozporządzenia z 2016 r." if variant == "B"
        else "§ 3 ust. 4 i § 4 ust. 3 rozporządzenia z 2016 r.",
        "suggestions": suggestions,
        "warnings": warnings,
    }
