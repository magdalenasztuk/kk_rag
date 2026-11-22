"""Szkice deterministyczne: plan rozmowy, uzasadnienie, wnioski IPRZ, oczekiwania.

To wersje bazowe (działają bez modelu językowego). `app.kompas.ai.enrich` używa ich jako szkieletu
i faktów dla Claude, a przy błędzie modelu zwraca właśnie je.
"""
from __future__ import annotations

import re

from app.domain.criteria import criterion_name
from app.domain.dates import format_pl
from app.domain.result import format_score
from app.domain.scales import points_label
from app.domain.text import collapse_whitespace, fold, truncate
from app.domain.workflow import case_criteria, case_result, decision_points, review_topics_for
from app.kompas import reference as ref

_CLAUSE = re.compile(r"\s*[;.]+\s*")
_AND = re.compile(r"\s+i\s+")
_KIND_RANK = {"contrast": 0, "choice": 1, "timing": 2, "result": 3}
_FOLLOW = {
    "contrast": (
        "Czego konkretnie zabrakło i jak uzupełnimy to następnym razem?",
        "Co mimo tego braku udało się doprowadzić do końca?",
    ),
    "choice": (
        "Którą możliwość wybrano i co o tym zdecydowało?",
        "Jakie były skutki możliwości, której nie użyto?",
    ),
    "timing": (
        "Co z tego zdążyło dojść na czas, a co nie?",
        "Kto poza Tobą musiał zareagować na ten sygnał?",
    ),
    "result": (
        "Jaki był skutek dla osób, które na tym polegały?",
        "Co z tego warto powtórzyć w kolejnym okresie?",
        "Co w tej sytuacji zależało od innych osób, a co od Ciebie?",
    ),
}
_OPENING = (
    "W sytuacji „{title}” ({date}) {fact}. {ask}",
    "Wracając do sytuacji „{title}” ({date}): {fact}. {ask}",
    "{date}, „{title}” — {fact}. {ask}",
)
_GAP = (
    "Opowiedz o jednej sytuacji z tego okresu, w której było widać: „{text}”.",
    "Kiedy ostatnio nie wyszło coś w tym rodzaju: „{text}”? Co stanęło na przeszkodzie?",
    "Jak to wygląda u Ciebie na co dzień: „{text}”? Podaj przykład z okresu oceny.",
)


def _observations_for(c: dict, criterion_id: str) -> list[dict]:
    return sorted((o for o in c["observations"] if criterion_id in o["criterionIds"]), key=lambda o: o["date"])


def _clauses(text: str) -> list[str]:
    rough = [collapse_whitespace(part).strip(" .;") for part in _CLAUSE.split(text or "") if collapse_whitespace(part).strip(" .;")]
    out: list[str] = []
    for part in rough:
        if _kind(part) == "contrast":
            out.append(part)
            continue
        bits = [bit.strip(" .;") for bit in _AND.split(part) if len(bit.strip(" .;")) >= 12]
        out.extend(bits or [part])
    return out or ["tę sytuację"]


def _lead(clause: str) -> str:
    text = clause.strip().rstrip(".")
    if not text:
        return "tę sytuację"
    return text[0].lower() + text[1:] if text[0].isalpha() else text


def _kind(clause: str) -> str:
    low = f" {fold(clause)} "
    if any(token in low for token in (" ale ", " jednak ", " niepeln", " mimo ", " brak ")):
        return "contrast"
    if any(token in low for token in ("wariant", "zaproponow", "rozwiaz")):
        return "choice"
    if any(token in low for token in ("wczesniej", "termin", "ryzyk", "opozn")):
        return "timing"
    return "result"


def observation_question(observation: dict, use: int) -> str:
    """Inny fakt i inna forma pytania przy każdym użyciu tej samej obserwacji."""
    clauses = _clauses(observation.get("description") or "")
    order = sorted(range(len(clauses)), key=lambda i: (_KIND_RANK[_kind(clauses[i])], -len(clauses[i])))
    clause = clauses[order[use % len(order)]]
    ask = _FOLLOW[_kind(clause)][use % len(_FOLLOW[_kind(clause)])]
    return _OPENING[use % len(_OPENING)].format(
        title=observation["title"], date=format_pl(observation["date"]), fact=_lead(clause), ask=ask)


def gap_question(indicator_text: str, use: int) -> str:
    return _GAP[use % len(_GAP)].format(text=truncate(indicator_text, 90))


def build_conversation_plan(c: dict, generated_at: str) -> dict:
    items = []
    seen: dict[str, int] = {}
    gap_uses = 0
    for cid in case_criteria(c):
        observations = _observations_for(c, cid)
        competency = ref.competency(cid) or {"indicators": []}
        covered = {iid for o in observations for iid in o["indicatorIds"]}
        missing = [i for i in competency["indicators"] if i["id"] not in covered][:2]
        gaps = [f"Brak obserwacji: „{truncate(i['text'], 90)}” — zapytaj o przykład z okresu oceny." for i in missing]
        questions = []
        for observation in observations[-2:]:
            questions.append(observation_question(observation, seen.get(observation["id"], 0)))
            seen[observation["id"]] = seen.get(observation["id"], 0) + 1
        for indicator in missing[:1] if questions else missing:
            questions.append(gap_question(indicator["text"], gap_uses))
            gap_uses += 1
        items.append({
            "criterionId": cid,
            "facts": [{"observationId": o["id"], "date": o["date"], "text": f"{o['title']}: {truncate(o['description'], 140)}"}
                      for o in observations],
            "gaps": gaps,
            "questions": questions,
        })
    weakest = [criterion_name(i["criterionId"]).lower() for i in items if not i["facts"] or len(i["gaps"]) > 1]
    start = c["preliminary"].get("employeeAcknowledgedAt")
    return {
        "generatedAt": generated_at,
        "opening": (f"Cel rozmowy: podsumować okres {'od ' + format_pl(start) if start else 'oceny'} na podstawie "
                    "konkretnych przykładów i wspólnie zaplanować rozwój. Zacznij od pytania o własną ocenę pracownika "
                    "— rozmowa ma być dialogiem."),
        "agenda": [{"topic": t["label"], "legalRef": t["legalRef"]} for t in review_topics_for(c["path"])],
        "items": items,
        "developmentQuestions": [
            "Które zadania z opisu stanowiska chcesz realizować samodzielnie w kolejnym okresie?",
            f"Jakiego wsparcia potrzebujesz w obszarach: {', '.join(weakest[:2])}?" if weakest
            else "W jakim obszarze chcesz się rozwijać w kolejnym okresie?",
            "Jaka forma rozwoju będzie najbardziej skuteczna: szkolenie, mentoring, udział w ćwiczeniach?",
        ],
        "closing": "Podsumuj ustalenia, poinformuj o kolejnych krokach: sporządzenie oceny na piśmie, zapoznanie z oceną "
                   "i wnioski do IPRZ.",
        "cautions": [
            "Mów o zachowaniach i ich skutkach, nie o cechach osoby.",
            "Brak obserwacji nie jest dowodem słabości — zapytaj o przykład.",
            "Sugestie narzędzia nie są oceną. Ocenę cząstkową wybierasz po rozmowie.",
        ],
    }


def draft_justification(c: dict, generated_at: str) -> dict:
    result = case_result(c)
    scored = [(cid, decision_points(c, cid)) for cid in case_criteria(c)]
    scored = [(cid, p) for cid, p in scored if p is not None]
    strengths = [(cid, p) for cid, p in scored if p >= 7]
    development = [(cid, p) for cid, p in scored if p <= (3 if c["path"] == "first" else 5)]

    def example(cid: str) -> str:
        obs = _observations_for(c, cid)
        return f" (np. {obs[-1]['title'].lower()}, {format_pl(obs[-1]['date'])})" if obs else ""

    start = c["preliminary"].get("employeeAcknowledgedAt")
    lines = [f"{'W okresie od ' + format_pl(start) if start else 'W okresie podlegającym ocenie'} osoba oceniana "
             f"({c['employee']['fullName']}) realizowała główne obowiązki wynikające z opisu stanowiska {c['position']['code']}."]
    if strengths:
        lines.append("Najwyżej oceniono: " + "; ".join(
            f"{criterion_name(cid).lower()} — {points_label(p).lower()}{example(cid)}" for cid, p in strengths) + ".")
    if development:
        lines.append("Obszary do dalszej pracy: " + "; ".join(
            f"{criterion_name(cid).lower()}{example(cid)}" for cid, _ in development) + ".")
    periodic = result.get("periodic")
    if periodic and periodic["mean"] is not None and periodic["level"]:
        lines.append(f"Średnia ocen cząstkowych wynosi {format_score(periodic['mean'])}, co odpowiada poziomowi "
                     f"„{periodic['level']['label'].lower()}”.")
        if periodic["vetoCriteria"]:
            lines.append(f"Ocena cząstkowa 1 pkt w kryterium „{criterion_name(periodic['vetoCriteria'][0]).lower()}” "
                         "przesądza o ocenie negatywnej (§ 11 ust. 1 pkt 4). [Uzupełnij fakty, które uzasadniają tę ocenę.]")
    return {"text": " ".join(lines),
            "basedOn": ["Decyzje w ocenach cząstkowych", f"{len(c['observations'])} obserwacji", "Wnioski z rozmowy oceniającej"],
            "generatedAt": generated_at}


def development_areas(c: dict) -> list[str]:
    threshold = 3 if c["path"] == "first" else 5
    return [cid for cid in case_criteria(c) if (p := decision_points(c, cid)) is not None and p <= threshold]


def draft_development_plan(c: dict, generated_at: str) -> dict:
    lines = []
    areas = development_areas(c)
    if areas:
        lines.append(f"Obszary do doskonalenia: {', '.join(criterion_name(a).lower() for a in areas)}.")
    needs = (c["review"].get("developmentNeeds") or "").strip()
    if needs:
        lines.append(f"Potrzeby zgłoszone w rozmowie oceniającej: {needs}")
    lines.append("Proponowane formy: szkolenie specjalistyczne, udział w ćwiczeniach z rolą koordynatora, mentoring "
                 "doświadczonego pracownika wydziału.")
    lines.append("Termin przeglądu postępów: za 6 miesięcy w rozmowie z przełożonym.")
    return {"text": "\n".join(lines),
            "basedOn": ["Oceny cząstkowe", "Rozmowa oceniająca", "Poradnik KPRM, rozdz. 6.2.5.4"],
            "generatedAt": generated_at}


def draft_expectations(c: dict) -> list[dict]:
    out = []
    for cid in case_criteria(c):
        competency = ref.competency(cid)
        standard = []
        for indicator in (competency or {}).get("indicators", [])[:2]:
            behavior = next((b for b in indicator["behaviors"] if b.get("level_index") == 3), None)
            if behavior and behavior.get("description"):
                standard.append(behavior["description"])
        text = ""
        if standard:
            text = "Oczekuję, że: " + " ".join(s[:1].lower() + s[1:] if i == 0 else s for i, s in enumerate(standard))
        out.append({"criterionId": cid, "text": text})
    return out
