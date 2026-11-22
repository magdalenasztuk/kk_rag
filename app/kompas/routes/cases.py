"""Sprawy oceny: tworzenie, autozapis sekcji, kroki, obserwacje, oceny cząstkowe, dokumenty, funkcje AI."""
from __future__ import annotations

import copy

from app.domain.criteria import additional_criteria_candidates, criterion_name
from app.domain.dates import format_pl, is_after, is_before, is_iso_date
from app.domain.deadlines import objection_deadline
from app.domain.result import format_score
from app.domain.scales import is_valid_points
from app.domain.scoring import suggest_criterion_score
from app.domain.text import new_id
from app.domain.workflow import (blocking_issues, case_criteria, case_outcome, case_result, is_step_completed,
                                 is_step_reachable, step_definition, steps_for, validate_step)
from app.kompas import reference as ref
from app.kompas.access import CASE_FORBIDDEN, can_see_case, present_case, require_editor, require_hr
from app.kompas.ai import enrich
from app.kompas.cases import create_case, history_event, summarize_case
from app.kompas.engines import drafts
from app.kompas.engines.position import analyze_position
from app.kompas.errors import bad_request, conflict, forbidden, not_found, unprocessable
from app.kompas.router import RouteContext, Router

SECTION_STEP = {
    "positionReview": "stanowisko",
    "criteria": "kryteria",
    "preliminary": "rozmowa-wstepna",
    "preparatoryService": "sluzba-przygotowawcza",
    "report": "sprawozdanie",
    "review": "rozmowa-oceniajaca",
    "conclusion": "podsumowanie",
}
SHEET_CONTENT_FIELDS = ("justification", "developmentPlan", "promotionRequest", "promotionJustification", "draftedAt")
SHEET_KINDS = ("arkusz-okresowy", "arkusz-pierwszej-oceny")
OBSERVATION_LIMIT = 1200


def _step_label(c: dict, step_id: str) -> str:
    return (step_definition(c["path"], step_id) or {}).get("label", step_id)


def _load(ctx: RouteContext) -> dict:
    c = ctx.ws.find_case(ctx.params.get("caseId", ""))
    if not can_see_case(c, ctx.user):
        raise forbidden(CASE_FORBIDDEN)
    return c


def _editable(ctx: RouteContext) -> dict:
    c = _load(ctx)
    require_editor(c, ctx.user)
    return copy.deepcopy(c)


def _require_step_open(c: dict, step_id: str) -> None:
    if not any(s["id"] == step_id for s in steps_for(c["path"])):
        raise bad_request("Ten krok nie występuje w tej ścieżce oceny.")
    if not is_step_reachable(c, step_id):
        raise conflict(f"Najpierw zakończ wcześniejsze kroki — „{_step_label(c, step_id)}” jest jeszcze niedostępny.")
    if is_step_completed(c, step_id):
        raise conflict(f"Krok „{_step_label(c, step_id)}” jest zakończony — zmiany są zablokowane.")


def _visible_cases(ctx: RouteContext, scope: str) -> list[dict]:
    if scope == "all":
        require_hr(ctx.user)
        return ctx.ws.cases
    uid = ctx.user["id"]
    return [c for c in ctx.ws.cases if c["evaluator"]["id"] == uid or (c.get("headOfUnit") or {}).get("id") == uid]


def _upsert_document(c: dict, kind: str, title: str, status: str, at: str) -> list[dict]:
    docs = c["documents"]
    existing = next((d for d in docs if d["kind"] == kind), None)
    if existing:
        return [{**d, "title": title, "status": status, "createdAt": at, "version": d["version"] + 1}
                if d["kind"] == kind else d for d in docs]
    return [*docs, {"id": new_id("doc"), "kind": kind, "title": title, "status": status, "createdAt": at, "version": 1}]


def _actor(ctx: RouteContext) -> dict:
    return ref.person_ref(ctx.user)


# — Tworzenie sprawy —

def _start_case(ctx: RouteContext) -> dict:
    body = ctx.json()
    user = ctx.user
    employee = ctx.ws.employee(str(body.get("employeeId") or ""))
    if "hr" not in user["roles"] and employee["supervisorId"] != user["id"]:
        raise forbidden("Ocenę uruchamiają kadry albo bezpośredni przełożony.")
    path = "first" if body.get("path") == "first" else "periodic"
    if path == "first" and employee["employment"]["basis"] != "pierwsza-umowa":
        raise unprocessable("Pierwsza ocena dotyczy osób zatrudnionych na pierwszą umowę na czas określony.")
    if any(c["employee"]["id"] == employee["id"] and c["status"] == "w-toku" for c in ctx.ws.cases):
        raise conflict(f"{employee['fullName']} ma już ocenę w toku.")
    evaluator = ref.user(employee["supervisorId"])
    unit = ref.org_unit(employee["orgUnitId"])
    head = (next((u for u in ref.users() if u["orgUnitId"] == unit["parentId"]), None)
            if path == "first" and unit.get("parentId") else None)
    created = create_case(path=path, employee=employee, position=ref.position(employee["positionId"]),
                          evaluator=ref.person_ref(evaluator), head_of_unit=ref.person_ref(head) if head else None,
                          org_unit_name=unit["name"], created_at=ctx.ws.now(), created_by=_actor(ctx))
    saved = ctx.ws.save_case(created)
    first_step = steps_for(path)[0]
    ctx.ws.notify({
        "recipientId": evaluator["id"], "kind": "proces",
        "title": f"Uruchomiono {'pierwszą ocenę' if path == 'first' else 'ocenę okresową'}: {employee['fullName']}",
        "body": f"Pierwszy krok: {first_step['label']}. Rozmowa wstępna do {format_pl(saved['deadlines']['preliminaryDueDate'])}.",
        "caseId": saved["id"], "link": f"/oceny/{saved['id']}", "sender": _actor(ctx),
    })
    return summarize_case(saved, ctx.ws.today)


# — Dokument OSP przypisany do oceny —

def _position_options(ctx: RouteContext) -> list[dict]:
    c = _editable(ctx)
    return [{k: p[k] for k in ("id", "code", "title", "documentName", "fromOrganizer")}
            for p in ref.positions_in_unit(c["position"]["orgUnitId"])]


def _assign_position(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    _require_step_open(c, "stanowisko")
    position_id = ctx.json().get("positionId")
    if not isinstance(position_id, str):
        raise bad_request("Wskaż dokument OSP.")
    position = ref.position(position_id)
    if position["orgUnitId"] != c["position"]["orgUnitId"]:
        raise unprocessable("Przypisz OSP stanowiska z komórki, w której pracuje oceniany.")
    if position["id"] == c["position"]["id"]:
        return present_case(c, ctx.user)
    now = ctx.ws.now()
    analysis = analyze_position(position, now)
    previous_doc = c["position"]["documentName"]
    c["position"] = position
    c["positionReview"] = {"analysis": analysis}
    c["history"].append(history_event(
        now, _actor(ctx), "krok",
        f"Zmieniono przypisany dokument: {previous_doc} → {position['documentName']}. Asystent przeanalizował nowy OSP "
        f"— rekomendacja: arkusz {analysis['recommendedVariant']}.", "stanowisko"))
    return present_case(ctx.ws.save_case(c), ctx.user)


# — Autozapis sekcji —

def _patch_case(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    patch = ctx.json()
    for section in patch:
        step_id = SECTION_STEP.get(section)
        if not step_id:
            raise bad_request(f"Nieznana sekcja: {section}.")
        _require_step_open(c, step_id)
    sections = {k: v for k, v in patch.items() if isinstance(v, dict)}

    if "positionReview" in sections:
        c["positionReview"] = {**c["positionReview"], **sections["positionReview"]}
        variant = c["positionReview"].get("confirmedVariant")
        if variant:
            allowed = additional_criteria_candidates(variant)
            c["criteria"]["additional"] = [cid for cid in c["criteria"]["additional"] if cid in allowed]
    for section in ("criteria", "preliminary", "preparatoryService", "report", "review"):
        if section in sections:
            c[section] = {**c[section], **sections[section]}
    if "conclusion" in sections:
        if c["conclusion"].get("employeeAcknowledgedAt"):
            raise conflict("Oceniany zapoznał się już z oceną — treści arkusza nie można zmieniać.")
        change = sections["conclusion"]
        merged = {**c["conclusion"], **change}
        changed = any(f in change and change[f] != c["conclusion"].get(f) for f in SHEET_CONTENT_FIELDS)
        if changed and c["conclusion"].get("sheetGeneratedAt"):
            merged.pop("sheetGeneratedAt", None)
            c["conclusion"] = merged
            c["documents"] = [{**d, "status": "szkic"} if d["kind"] in SHEET_KINDS else d for d in c["documents"]]
            c["history"].append(history_event(
                ctx.ws.now(), _actor(ctx), "dokument",
                "Zmieniono treść oceny po wygenerowaniu arkusza — arkusz wymaga ponownego wygenerowania.", "podsumowanie"))
        else:
            c["conclusion"] = merged
    return present_case(ctx.ws.save_case(c), ctx.user)


# — Ukończenie kroku —

def _complete_step(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    step_id = ctx.params["stepId"]
    _require_step_open(c, step_id)
    blocking = blocking_issues(validate_step(c, step_id))
    if blocking:
        raise unprocessable(f"Nie można zakończyć kroku „{_step_label(c, step_id)}”.", [i["message"] for i in blocking])

    now = ctx.ws.now()
    actor = _actor(ctx)
    original = copy.deepcopy(c)
    c["steps"] = {**c["steps"], step_id: {"completedAt": now, "completedById": ctx.user["id"]}}
    events = []
    if step_id == "stanowisko":
        variant = original["positionReview"].get("confirmedVariant")
        recommended = (original["positionReview"].get("analysis") or {}).get("recommendedVariant")
        c["positionReview"]["confirmedAt"] = now
        if recommended and variant != recommended:
            events.append(history_event(now, actor, "odstepstwo",
                                        f"Zatwierdzono arkusz {variant} wbrew rekomendacji ({recommended}): "
                                        f"{original['positionReview'].get('overrideReason') or ''}", step_id))
        else:
            events.append(history_event(now, actor, "krok", f"Zatwierdzono arkusz {variant}"
                                        f"{' zgodnie z rekomendacją asystenta' if recommended else ''}.", step_id))
    elif step_id == "kryteria":
        c["criteria"]["approvedAt"] = now
        names = ", ".join(criterion_name(cid) for cid in original["criteria"]["additional"]) or "brak"
        events.append(history_event(now, actor, "krok", f"Zatwierdzono kryteria dodatkowe: {names}.", step_id))
    elif step_id == "rozmowa-wstepna":
        title = ("Pierwsza ocena — ustalenia rozmowy wstępnej i termin sprawozdania" if c["path"] == "first"
                 else f"Arkusz {original['positionReview'].get('confirmedVariant') or ''} — część I (kryteria i termin)")
        c["documents"] = _upsert_document(c, "czesc-i", title, "podpisany", now)
        events.append(history_event(now, actor, "krok",
                                    "Zapisano rozmowę wstępną; oceniany potwierdził zapoznanie podpisem.", step_id))
    elif step_id == "podsumowanie":
        outcome = case_outcome(original)
        result = case_result(original)
        mean = result["first"]["mean"] if result["path"] == "first" else result["periodic"]["mean"]
        mean_txt = f" ({format_score(mean)})" if mean is not None else ""
        c["status"] = "zakonczona"
        c["documents"] = [{**d, "status": "podpisany"} if d["kind"] in SHEET_KINDS else d for d in c["documents"]]
        events.append(history_event(now, actor, "krok", f"Ocena zakończona — {outcome or 'brak wyniku'}{mean_txt}.", step_id))
        for hr in (u for u in ref.users() if "hr" in u["roles"]):
            ctx.ws.notify({
                "recipientId": hr["id"], "kind": "proces", "title": f"Zakończono ocenę: {original['employee']['fullName']}",
                "body": f"Wynik: {outcome or '—'}{f', średnia {format_score(mean)}' if mean is not None else ''}. "
                        "Arkusz podpisany — do akt osobowych.",
                "caseId": c["id"], "link": f"/oceny/{c['id']}/podsumowanie", "sender": actor,
            })
    else:
        events.append(history_event(now, actor, "krok", f"Zakończono krok „{_step_label(c, step_id)}”.", step_id))
    c["history"] = [*c["history"], *events]
    return present_case(ctx.ws.save_case(c), ctx.user)


# — Obserwacje —

def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _parse_observation(body: dict, c: dict, today: str) -> dict:
    date = _text(body.get("date"))
    issues = []
    if not is_iso_date(date):
        issues.append("Podaj datę sytuacji.")
    elif is_after(date, today):
        issues.append("Data obserwacji nie może być z przyszłości.")
    if not _text(body.get("title")):
        issues.append("Dodaj krótki tytuł obserwacji.")
    description = _text(body.get("description"))
    if not description:
        issues.append("Opisz zadanie i zachowanie osoby ocenianej.")
    elif len(description) > OBSERVATION_LIMIT:
        issues.append(f"Opis może mieć najwyżej {OBSERVATION_LIMIT} znaków.")
    criteria = case_criteria(c)
    criterion_ids = [cid for cid in (body.get("criterionIds") if isinstance(body.get("criterionIds"), list) else [])
                     if cid in criteria]
    if not criterion_ids:
        issues.append("Powiąż obserwację z co najmniej jednym kryterium.")
    if issues:
        raise unprocessable("Obserwacja wymaga uzupełnienia.", issues)
    indicator_ids = [iid for iid in (body.get("indicatorIds") if isinstance(body.get("indicatorIds"), list) else [])
                     if isinstance(iid, str) and any(iid.startswith(f"{cid}-") for cid in criterion_ids)]
    task_id = _text(body.get("positionTaskId"))
    out = {"date": date, "title": _text(body.get("title"))}
    if task_id and any(t["id"] == task_id for t in c["position"]["tasks"]):
        out["positionTaskId"] = task_id
    return {**out, "description": description, "criterionIds": criterion_ids, "indicatorIds": indicator_ids}


def _require_observations_open(c: dict) -> None:
    if not is_step_reachable(c, "obserwacje"):
        raise conflict("Obserwacje zbiera się od zapoznania ocenianego z kryteriami — najpierw zakończ wcześniejsze kroki.")
    if is_step_completed(c, "ocena"):
        raise conflict("Oceny cząstkowe są zatwierdzone — obserwacji nie można już zmieniać.")


def _add_observation(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    _require_observations_open(c)
    data = _parse_observation(ctx.json(), c, ctx.ws.today)
    now = ctx.ws.now()
    observation = {**data, "id": new_id("obs"), "authorId": ctx.user["id"], "createdAt": now, "updatedAt": now}
    c["observations"].append(observation)
    c["history"].append(history_event(now, _actor(ctx), "obserwacja",
                                      f"Dodano obserwację „{observation['title']}” ({format_pl(observation['date'])}).",
                                      "obserwacje"))
    return present_case(ctx.ws.save_case(c), ctx.user)


def _find_observation(c: dict, observation_id: str) -> dict:
    found = next((o for o in c["observations"] if o["id"] == observation_id), None)
    if not found:
        raise not_found("obserwacja")
    return found


def _update_observation(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    _require_observations_open(c)
    existing = _find_observation(c, ctx.params["observationId"])
    data = _parse_observation(ctx.json(), c, ctx.ws.today)
    updated = {"id": existing["id"], "authorId": existing["authorId"], "createdAt": existing["createdAt"], **data,
               "updatedAt": ctx.ws.now()}
    c["observations"] = [updated if o["id"] == existing["id"] else o for o in c["observations"]]
    return present_case(ctx.ws.save_case(c), ctx.user)


def _delete_observation(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    _require_observations_open(c)
    existing = _find_observation(c, ctx.params["observationId"])
    c["observations"] = [o for o in c["observations"] if o["id"] != existing["id"]]
    for rating in c["ratings"]:
        for item in rating["indicators"]:
            item["observationIds"] = [i for i in item["observationIds"] if i != existing["id"]]
    c["history"].append(history_event(ctx.ws.now(), _actor(ctx), "obserwacja",
                                      f"Usunięto obserwację „{existing['title']}”.", "obserwacje"))
    return present_case(ctx.ws.save_case(c), ctx.user)


def _observation_analysis(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    body = ctx.json()
    text = lambda v: v if isinstance(v, str) else ""  # noqa: E731
    if not text(body.get("description")).strip():
        raise bad_request("Opisz zadanie i zachowanie, aby asystent mógł zaproponować powiązania.")
    draft = {"date": text(body.get("date")), "title": text(body.get("title")), "description": text(body.get("description"))}
    return enrich.analyze_observation(draft, case_criteria(c), c["position"]["tasks"], ctx.ws.now())


# — Oceny cząstkowe —

def _save_rating(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    _require_step_open(c, "ocena")
    criterion_id = ctx.params["criterionId"]
    if criterion_id not in case_criteria(c):
        raise bad_request("To kryterium nie należy do tej oceny.")
    body = ctx.json()
    observation_ids = {o["id"] for o in c["observations"]}
    indicators = []
    for item in body.get("indicators") or []:
        if not isinstance(item, dict) or not isinstance(item.get("indicatorId"), str) \
                or not item["indicatorId"].startswith(f"{criterion_id}-"):
            continue
        no_basis = item.get("noBasis") is True
        level = item.get("level")
        valid_level = (not no_basis and isinstance(level, int) and not isinstance(level, bool) and 1 <= level <= 5)
        indicators.append({"indicatorId": item["indicatorId"], "level": level if valid_level else None,
                           "noBasis": no_basis,
                           "observationIds": [i for i in item.get("observationIds") or [] if i in observation_ids]})

    suggestion = suggest_criterion_score(c["path"], indicators, ref.indicator_count(criterion_id))
    previous = next((r for r in c["ratings"] if r["criterionId"] == criterion_id), None)
    previous_decision = (previous or {}).get("decision") or None
    now = ctx.ws.now()
    decision = None
    raw = body.get("decision")
    if isinstance(raw, dict) and isinstance(raw.get("points"), (int, float)) and not isinstance(raw.get("points"), bool):
        points = raw["points"]
        if not is_valid_points(c["path"], points):
            raise unprocessable("Ocena spoza skali tej ścieżki.",
                                [f"Dozwolone wartości: {'3, 5, 7' if c['path'] == 'first' else '1, 3, 5, 7, 9'}."])
        points = int(points)
        unchanged = previous_decision and previous_decision.get("points") == points
        decision = {"points": points, "rationale": str(raw.get("rationale") or "").strip(),
                    "decidedAt": previous_decision["decidedAt"] if unchanged else now,
                    "decidedById": ctx.user["id"], "suggestedPoints": suggestion["points"],
                    "suggestedAverage": suggestion["average"]}

    rating = {"criterionId": criterion_id, "indicators": indicators, "decision": decision}
    if decision and decision["points"] != (previous_decision or {}).get("points"):
        deviates = decision["suggestedPoints"] is not None and decision["points"] != decision["suggestedPoints"]
        name = criterion_name(criterion_id)
        c["history"].append(history_event(
            now, _actor(ctx), "odstepstwo" if deviates else "decyzja",
            f"{name}: {decision['points']} pkt — odstępstwo od sugestii narzędzia ({decision['suggestedPoints']} pkt)."
            if deviates else f"{name}: {decision['points']} pkt.", "ocena"))
    c["ratings"] = ([rating if r["criterionId"] == criterion_id else r for r in c["ratings"]] if previous
                    else [*c["ratings"], rating])
    ctx.ws.save_case(c)
    return rating


# — Analiza OSP —

def _position_analysis(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    _require_step_open(c, "stanowisko")
    now = ctx.ws.now()
    analysis = analyze_position(c["position"], now)
    c["positionReview"] = {**c["positionReview"], "analysis": analysis}
    c["history"].append(history_event(
        now, _actor(ctx), "krok",
        f"Asystent przeanalizował OSP — rekomendacja: arkusz {analysis['recommendedVariant']}, "
        f"{len(analysis['suggestions'])} propozycje kryteriów dodatkowych.", "stanowisko"))
    return present_case(ctx.ws.save_case(c), ctx.user)


# — Dokumenty —

def _generate_document(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    kind = ctx.json().get("kind")
    now = ctx.ws.now()
    actor = _actor(ctx)
    if kind in SHEET_KINDS:
        _require_step_open(c, "podsumowanie")
        c["conclusion"] = {**c["conclusion"], "draftedAt": c["conclusion"].get("draftedAt") or ctx.ws.today}
        issues = [i for i in blocking_issues(validate_step(c, "podsumowanie"))
                  if not i["message"].startswith("Wygeneruj arkusz") and not i["message"].startswith("Odnotuj datę zapoznania")]
        if issues:
            raise unprocessable("Uzupełnij podsumowanie przed wygenerowaniem arkusza.", [i["message"] for i in issues])
        title = (f"Arkusz oceny okresowej {c['positionReview'].get('confirmedVariant') or ''} — części I–III"
                 if kind == "arkusz-okresowy" else "Arkusz pierwszej oceny")
        c["conclusion"]["sheetGeneratedAt"] = now
        c["documents"] = _upsert_document(c, kind, title, "wygenerowany", now)
        c["history"].append(history_event(now, actor, "dokument", f"Wygenerowano {title.lower()} do podpisu.", "podsumowanie"))
        return present_case(ctx.ws.save_case(c), ctx.user)
    if kind == "zawiadomienie-o-terminie":
        pending = [e for e in c["deadlines"]["extensions"] if not e.get("employeeNotifiedAt")]
        if not pending:
            raise conflict("Brak przedłużeń terminu wymagających zawiadomienia.")
        for e in pending:
            e["employeeNotifiedAt"] = ctx.ws.today
        c["documents"] = _upsert_document(c, kind, "Zawiadomienie o nowym terminie oceny (§ 8)", "wygenerowany", now)
        c["history"].append(history_event(now, actor, "termin",
                                          f"Zawiadomiono ocenianego o nowym terminie oceny: {format_pl(c['deadlines']['dueDate'])}."))
        return present_case(ctx.ws.save_case(c), ctx.user)
    raise bad_request("Nieobsługiwany rodzaj dokumentu.")


def _acknowledge(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    _require_step_open(c, "podsumowanie")
    date = ctx.json().get("date")
    if not c["conclusion"].get("sheetGeneratedAt"):
        raise conflict("Najpierw wygeneruj arkusz do podpisu.")
    if not date or not is_iso_date(date):
        raise unprocessable("Podaj datę zapoznania.", ["Data zapoznania jest wymagana."])
    drafted = c["conclusion"].get("draftedAt")
    if is_after(date, ctx.ws.today) or (drafted and is_before(date, drafted)):
        raise unprocessable("Nieprawidłowa data zapoznania.",
                            ["Data zapoznania musi przypadać między sporządzeniem oceny a dniem dzisiejszym."])
    c["conclusion"]["employeeAcknowledgedAt"] = date
    c["history"].append(history_event(
        ctx.ws.now(), _actor(ctx), "zapoznanie",
        f"Oceniany zapoznał się z oceną {format_pl(date)} i otrzymał kopię. Termin na sprzeciw: "
        f"{format_pl(objection_deadline(date))}." if c["path"] == "periodic"
        else f"Oceniany zapoznał się z pierwszą oceną {format_pl(date)}.", "podsumowanie"))
    return present_case(ctx.ws.save_case(c), ctx.user)


# — Funkcje AI —

def _conversation_plan(ctx: RouteContext) -> dict:
    c = _editable(ctx)
    now = ctx.ws.now()
    plan = enrich.conversation_plan(c, now)
    c["review"] = {**c["review"], "planGeneratedAt": now}
    c["documents"] = _upsert_document(c, "plan-rozmowy", "Plan rozmowy oceniającej (materiał roboczy)", "szkic", now)
    ctx.ws.save_case(c)
    return plan


def register(router: Router) -> None:
    (router
     .get("/cases", lambda ctx: [summarize_case(c, ctx.ws.today)
                                 for c in _visible_cases(ctx, "all" if ctx.query.get("scope") == "all" else "mine")])
     .post("/cases", _start_case)
     .get("/cases/:caseId", lambda ctx: present_case(_load(ctx), ctx.user))
     .patch("/cases/:caseId", _patch_case)
     .post("/cases/:caseId/steps/:stepId/complete", _complete_step)
     .post("/cases/:caseId/observations", _add_observation)
     .put("/cases/:caseId/observations/:observationId", _update_observation)
     .delete("/cases/:caseId/observations/:observationId", _delete_observation)
     .post("/cases/:caseId/observation-analysis", _observation_analysis, ai=True)
     .put("/cases/:caseId/ratings/:criterionId", _save_rating)
     .post("/cases/:caseId/position-analysis", _position_analysis, ai=True)
     .get("/cases/:caseId/position-options", _position_options)
     .put("/cases/:caseId/position", _assign_position, ai=True)
     .post("/cases/:caseId/documents", _generate_document)
     .post("/cases/:caseId/acknowledgement", _acknowledge)
     .post("/cases/:caseId/conversation-plan", _conversation_plan, ai=True)
     .post("/cases/:caseId/drafts/justification", lambda ctx: enrich.justification(_editable(ctx), ctx.ws.now()), ai=True)
     .post("/cases/:caseId/drafts/development-plan",
           lambda ctx: enrich.development_plan(_editable(ctx), ctx.ws.now()), ai=True)
     .post("/cases/:caseId/drafts/expectations", lambda ctx: drafts.draft_expectations(_editable(ctx)), ai=True))
