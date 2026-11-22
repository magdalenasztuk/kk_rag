"""Równoległe zapisy tej samej oceny nie mogą kasować sobie pól."""
from app.kompas.merge import merge_state


def _case(**sections):
    base = {
        "id": "case-1",
        "preliminary": {"notes": "", "topics": {}, "goals": [], "expectations": []},
        "criteria": {"additional": [], "rejectedSuggestions": []},
        "observations": [],
        "ratings": [],
        "documents": [],
        "history": [],
        "steps": {},
    }
    base.update(sections)
    return base


def test_parallel_preliminary_edits_keep_both_fields():
    before = {"cases": [_case()], "employees": [], "notifications": []}
    notes = _case()
    notes["preliminary"] = {**notes["preliminary"], "notes": "Ustaliliśmy termin sprawozdania."}
    topics = _case()
    topics["preliminary"] = {**topics["preliminary"], "topics": {"obowiazki": "omowiono"}}
    fresh = {"cases": [notes], "employees": [], "notifications": []}
    merged = merge_state(fresh, before, {"cases": [topics], "employees": [], "notifications": []})
    preliminary = merged["cases"][0]["preliminary"]
    assert preliminary["notes"] == "Ustaliliśmy termin sprawozdania."
    assert preliminary["topics"]["obowiazki"] == "omowiono"


def test_parallel_observation_and_rating_both_stay():
    before = {"cases": [_case()], "employees": [], "notifications": []}
    with_obs = _case(observations=[{"id": "obs-1", "title": "Konferencja"}])
    with_rating = _case(ratings=[{"criterionId": "c01", "decision": {"points": 7}}])
    fresh = {"cases": [with_obs], "employees": [], "notifications": []}
    merged = merge_state(fresh, before, {"cases": [with_rating], "employees": [], "notifications": []})
    case = merged["cases"][0]
    assert case["observations"][0]["id"] == "obs-1"
    assert case["ratings"][0]["criterionId"] == "c01"


def test_completed_step_survives_a_later_section_edit():
    before = {"cases": [_case()], "employees": [], "notifications": []}
    stepped = _case(steps={"stanowisko": {"completedAt": "2026-11-21T10:00:00.000Z"}})
    noted = _case()
    noted["preliminary"] = {**noted["preliminary"], "notes": "Notatka"}
    fresh = {"cases": [stepped], "employees": [], "notifications": []}
    merged = merge_state(fresh, before, {"cases": [noted], "employees": [], "notifications": []})
    case = merged["cases"][0]
    assert "stanowisko" in case["steps"]
    assert case["preliminary"]["notes"] == "Notatka"
