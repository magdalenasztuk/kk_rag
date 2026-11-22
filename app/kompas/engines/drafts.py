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
# Pytania awaryjne, gdy model nie odpowie. Mówione na głos, bez cytowania wskaźnika.
_GAP_BY_CRITERION = {
    "c01": (
        "Opowiedz o sytuacji z okresu oceny, w której szczególnie liczyła się rzetelność: przepis, termin albo jakość pracy. Co zrobiłeś i jaki był skutek?",
        "Kiedy w tym okresie coś nie zostało dopięte tak, jak powinno? Co stanęło na przeszkodzie i jak to naprawiłeś?",
    ),
    "c02": (
        "Opowiedz o rozmowie albo piśmie z tego okresu, w którym musiałeś coś wyjaśnić innej osobie. Co powiedziałeś i czy rozmówca Cię zrozumiał?",
        "Kiedy informacja, którą przekazałeś, okazała się niejasna albo spóźniona? Co byś następnym razem zrobił inaczej?",
    ),
    "c03": (
        "Opowiedz o zadaniu z tego okresu, do którego brakowało Ci wiedzy albo umiejętności. Jak je uzupełniłeś i co z tego zostało w pracy?",
        "Czego nauczyłeś się w tym okresie i przy jakim zadaniu z tego skorzystałeś? Podaj jeden przykład.",
    ),
    "c04": (
        "Opowiedz o zadaniu z tego okresu, które miało termin i kilka zależnych czynności. Jak ułożyłeś pracę i co udało się skończyć na czas?",
        "Kiedy nie udało się dotrzymać terminu albo ułożona kolejność prac się zmieniła? Co wtedy zrobiłeś, żeby dojść do celu?",
    ),
    "c05": (
        "Opowiedz o problemie z tego okresu, który rozwiązałeś inaczej niż zwykle. Na czym polegał pomysł i czy się sprawdził?",
        "Kiedy utknąłeś w znanym sposobie działania? Co pomogło ruszyć dalej?",
    ),
    "c06": (
        "Opowiedz o sprawie z tego okresu, którą prowadziłeś razem z kimś innym. Jaki był Twój wkład i jak podzieliliście się robotą?",
        "Kiedy współpraca szła opornie? Co zrobiłeś, żeby ją ułożyć?",
    ),
    "c07": (
        "Opowiedz o sprawie z tego okresu, w której musiałeś rozłożyć problem na części, zanim coś zaproponowałeś. Jak do tego doszedłeś?",
        "Kiedy wniosek okazał się nietrafiony, bo zabrakło jakiejś informacji? Czego wtedy nie sprawdziłeś?",
    ),
    "c08": (
        "Opowiedz o uzgodnieniu z tego okresu, w którym strony chciały czegoś innego. Do czego doszliście i czym się kierowałeś?",
        "Kiedy nie udało się dojść do porozumienia? Co stanęło na przeszkodzie?",
    ),
    "c09": (
        "Opowiedz o wystąpieniu albo prezentacji z tego okresu. Dla kogo mówiłeś, co było najważniejsze i jak to zostało przyjęte?",
        "Kiedy wystąpienie nie poszło tak, jak chciałeś? Co byś następnym razem zmienił?",
    ),
    "c10": (
        "Opowiedz o kontakcie z interesantem albo inną osobą z zewnątrz z tego okresu. O co prosiła i jak sprawę zakończyłeś?",
        "Kiedy nie udało się odpowiedzieć tak, jak ktoś oczekiwał? Co było przyczyną i co zrobiłeś dalej?",
    ),
    "c11": (
        "Opowiedz o nagłej albo trudnej sytuacji z tego okresu. Co zrobiłeś w pierwszej kolejności i jaki był skutek?",
        "Czego w takiej sytuacji zabrakło — informacji, ludzi, decyzji? Jak to nadrobiłeś?",
    ),
    "c12": (
        "Opowiedz o zadaniu z tego okresu, które wykraczało poza bieżączkę i dotyczyło dłuższego celu. Jak je połączyłeś z pracą wydziału?",
        "Kiedy bieżące sprawy odsunęły coś ważniejszego na później? Jak wtedy wybrałeś, czym się zająć?",
    ),
    "c13": (
        "Opowiedz o sytuacji z tego okresu, w której od Twojej decyzji zależała praca innych osób. Co ustaliłeś i jak to sprawdziłeś?",
        "Kiedy ktoś z zespołu nie dostał od Ciebie na czas tego, czego potrzebował? Co wtedy zmieniłeś?",
    ),
    "c14": (
        "Opowiedz o decyzji z tego okresu, którą podjąłeś sam. Na czym ją oparłeś i jakie miała skutki?",
        "Kiedy wahałeś się z decyzją albo oddałeś ją komuś innemu? Co o tym zdecydowało?",
    ),
}


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


def _thin_observation_question(observation: dict, use: int) -> str:
    title = observation.get("title") or "tę sytuację"
    date = format_pl(observation["date"])
    options = (
        f"{date} zapisałeś sytuację „{title}”. Opowiedz, co dokładnie wtedy zrobiłeś i jaki był skutek.",
        f"Wracając do „{title}” ({date}): co w tej sytuacji zależało od Ciebie, a co od innych osób?",
        f"Czego sytuacja „{title}” ({date}) uczy na kolejny okres? Co warto powtórzyć, a czego uniknąć?",
    )
    return options[use % len(options)]


def observation_question(observation: dict, use: int) -> str:
    """Inny fakt i inna forma pytania przy każdym użyciu tej samej obserwacji."""
    description = collapse_whitespace(observation.get("description") or "")
    title = collapse_whitespace(observation.get("title") or "")
    if len(description) < 40 or fold(description) == fold(title):
        return _thin_observation_question(observation, use)
    clauses = _clauses(description)
    order = sorted(range(len(clauses)), key=lambda i: (_KIND_RANK[_kind(clauses[i])], -len(clauses[i])))
    clause = clauses[order[use % len(order)]]
    ask = _FOLLOW[_kind(clause)][use % len(_FOLLOW[_kind(clause)])]
    return _OPENING[use % len(_OPENING)].format(
        title=observation["title"], date=format_pl(observation["date"]), fact=_lead(clause), ask=ask)


def gap_question(criterion_id: str, use: int) -> str:
    options = _GAP_BY_CRITERION.get(criterion_id)
    if not options:
        name = criterion_name(criterion_id).lower()
        options = (
            f"Opowiedz o jednej sytuacji z okresu oceny związanej z obszarem „{name}”. Co zrobiłeś i jaki był skutek?",
            f"Przypomnij sytuację z tego okresu, w której w obszarze „{name}” coś poszło nie tak. Co stanęło na przeszkodzie?",
        )
    return options[use % len(options)]


def build_conversation_plan(c: dict, generated_at: str) -> dict:
    items = []
    seen: dict[str, int] = {}
    gap_uses = 0
    for cid in case_criteria(c):
        observations = _observations_for(c, cid)
        competency = ref.competency(cid) or {"indicators": []}
        covered = {iid for o in observations for iid in o["indicatorIds"]}
        missing = [i for i in competency["indicators"] if i["id"] not in covered][:2]
        gaps = [f"Brak przykładu dotyczącego: {truncate(i['text'], 90)}." for i in missing]
        questions = []
        for observation in observations[-2:]:
            questions.append(observation_question(observation, seen.get(observation["id"], 0)))
            seen[observation["id"]] = seen.get(observation["id"], 0) + 1
        if not questions:
            questions.append(gap_question(cid, gap_uses))
            gap_uses += 1
            if len(missing) > 1:
                questions.append(gap_question(cid, gap_uses))
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
