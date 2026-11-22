"""Kadry widzą przebieg. Narracja arkusza dochodzi dopiero, gdy dokument jest w aktach."""
from app.kompas.access import history_summary_for_hr, present_case

HR = {"id": "u-marta", "roles": ["hr"]}
EVALUATOR = {"id": "u-piotr", "roles": ["manager"]}


def _case() -> dict:
    return {
        "status": "w-toku",
        "evaluator": {"id": "u-piotr"},
        "observations": [{"id": "o", "title": "Incydent"}],
        "preliminary": {
            "notes": "notatka",
            "expectations": [{"criterionId": "c1", "text": "sekret"}],
            "goals": [{"id": "g", "text": "cel", "measure": "m"}],
        },
        "review": {"notes": "rozmowa", "employeePerspective": "p", "developmentNeeds": "d"},
        "positionReview": {"confirmedVariant": "C", "overrideReason": "bo tak"},
        "ratings": [{
            "criterionId": "c1",
            "indicators": [{"level": 4}],
            "decision": {"points": 7, "rationale": "dlatego"},
        }],
        "conclusion": {
            "justification": "uzasadnienie",
            "developmentPlan": "plan",
            "promotionJustification": "awans",
            "promotionRequest": "tak",
            "justificationAiDraft": True,
        },
        "history": [
            {"id": "h1", "kind": "obserwacja", "summary": "Dodano obserwację: Incydent na dyżurze."},
            {"id": "h2", "kind": "odstepstwo", "summary": "Zatwierdzono arkusz B wbrew rekomendacji (C): bo tak"},
            {"id": "h3", "kind": "odstepstwo", "summary": "Komunikacja: 7 pkt — odstępstwo od sugestii narzędzia (5 pkt)."},
            {"id": "h4", "kind": "decyzja", "summary": "Ocena cząstkowa 5 pkt (c1) zgodna z sugestią."},
            {"id": "h5", "kind": "krok", "summary": "Zakończono krok."},
        ],
    }


def test_hr_keeps_process_and_hides_working_narrative():
    view = present_case(_case(), HR)
    assert view["access"]["redacted"] is True
    assert view["observations"] == []
    assert view["preliminary"]["notes"] == ""
    assert view["preliminary"]["expectations"] == []
    assert view["preliminary"]["goals"] == []
    assert view["review"]["notes"] == ""
    assert "overrideReason" not in view["positionReview"]
    assert view["ratings"][0]["indicators"] == []
    assert view["ratings"][0]["decision"]["points"] == 7
    assert view["ratings"][0]["decision"]["rationale"] == ""
    assert view["conclusion"]["justification"] == ""
    assert view["conclusion"]["developmentPlan"] == ""
    assert view["conclusion"]["promotionJustification"] == ""
    assert "promotionRequest" not in view["conclusion"]
    assert "justificationAiDraft" not in view["conclusion"]
    assert view["history"][0]["summary"] == "Dodano obserwację."
    assert view["history"][1]["summary"] == "Zatwierdzono inny arkusz niż wynika z opisu stanowiska."
    assert "5 pkt" not in view["history"][2]["summary"]
    assert view["history"][3]["summary"] == "Zapisano ocenę cząstkową 5 pkt."
    assert view["history"][4]["summary"] == "Zakończono krok."


def test_signed_documents_reach_hr():
    case = _case()
    case["preliminary"]["employeeAcknowledgedAt"] = "2026-01-05"
    part_one = present_case(case, HR)
    assert part_one["preliminary"]["expectations"][0]["text"] == "sekret"
    assert part_one["preliminary"]["goals"][0]["text"] == "cel"
    assert part_one["preliminary"]["notes"] == ""
    assert part_one["conclusion"]["justification"] == ""

    case["conclusion"]["employeeAcknowledgedAt"] = "2026-11-20"
    filed = present_case(case, HR)
    assert filed["conclusion"]["justification"] == "uzasadnienie"
    assert filed["conclusion"]["developmentPlan"] == "plan"
    assert filed["conclusion"]["promotionRequest"] == "tak"
    assert filed["conclusion"]["justificationAiDraft"] is True


def test_evaluator_sees_the_full_case():
    view = present_case(_case(), EVALUATOR)
    assert view["access"]["redacted"] is False
    assert view["observations"][0]["title"] == "Incydent"
    assert view["conclusion"]["justification"] == "uzasadnienie"
    assert view["positionReview"]["overrideReason"] == "bo tak"


def test_hr_history_redaction_is_stable():
    once = history_summary_for_hr({"kind": "obserwacja", "summary": "Dodano obserwację: Incydent."})
    assert history_summary_for_hr({"kind": "obserwacja", "summary": once}) == once
