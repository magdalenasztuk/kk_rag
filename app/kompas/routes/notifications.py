from __future__ import annotations

from app.domain.text import new_id
from app.kompas import reference as ref
from app.kompas.access import require_hr
from app.kompas.cases import history_event
from app.kompas.errors import bad_request, not_found
from app.kompas.reminders import reminder_candidates
from app.kompas.router import RouteContext, Router

MAX_NOTE_LENGTH = 400


def _list(ctx: RouteContext) -> list[dict]:
    mine = [n for n in ctx.ws.state["notifications"] if n["recipientId"] == ctx.user["id"]]
    return sorted(mine, key=lambda n: n["createdAt"], reverse=True)


def _read_all(ctx: RouteContext) -> dict:
    now = ctx.ws.now()
    for n in ctx.ws.state["notifications"]:
        if n["recipientId"] == ctx.user["id"] and not n.get("readAt"):
            n["readAt"] = now
            ctx.ws.touch()
    return {"ok": True}


def _read(ctx: RouteContext) -> dict:
    target = next((n for n in ctx.ws.state["notifications"]
                   if n["id"] == ctx.params["id"] and n["recipientId"] == ctx.user["id"]), None)
    if not target:
        raise not_found("powiadomienie")
    if not target.get("readAt"):
        target["readAt"] = ctx.ws.now()
        ctx.ws.touch()
    return target


def _rules(ctx: RouteContext) -> list[dict]:
    require_hr(ctx.user)
    return ctx.ws.state["reminderRules"]


def _update_rule(ctx: RouteContext) -> dict:
    require_hr(ctx.user)
    rule = next((r for r in ctx.ws.state["reminderRules"] if r["id"] == ctx.params["id"]), None)
    if not rule:
        raise not_found("reguła przypomnień")
    body = ctx.json()
    if isinstance(body.get("enabled"), bool):
        rule["enabled"] = body["enabled"]
    if isinstance(body.get("daysBefore"), list):
        days = [d for d in body["daysBefore"] if isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 60]
        rule["daysBefore"] = sorted(days, reverse=True)
    ctx.ws.touch()
    return rule


def _candidates(ctx: RouteContext) -> list[dict]:
    require_hr(ctx.user)
    s = ctx.ws.state
    return reminder_candidates(s["cases"], s["reminderRules"], s["reminderLog"], s["today"])


def _log(ctx: RouteContext) -> list[dict]:
    require_hr(ctx.user)
    read_at = {n["id"]: n.get("readAt") for n in ctx.ws.state["notifications"]}
    entries = [{**e, "readAt": read_at[e["id"]]} if read_at.get(e["id"]) else e for e in ctx.ws.state["reminderLog"]]
    return sorted(entries, key=lambda e: e["sentAt"], reverse=True)


def _send(ctx: RouteContext) -> dict:
    require_hr(ctx.user)
    body = ctx.json()
    ids = [i for i in body.get("candidateIds") or [] if isinstance(i, str)] if isinstance(body.get("candidateIds"), list) else []
    if not ids:
        raise bad_request("Wybierz co najmniej jedno przypomnienie.")
    note = body["note"].strip()[:MAX_NOTE_LENGTH] if isinstance(body.get("note"), str) else ""
    s = ctx.ws.state
    selected = [c for c in reminder_candidates(s["cases"], s["reminderRules"], s["reminderLog"], s["today"])
                if c["id"] in ids]
    now = ctx.ws.now()
    sender = ref.person_ref(ctx.user)
    notifications, log = [], []
    for candidate in selected:
        nid = new_id("n")
        notifications.append({"id": nid, "recipientId": candidate["recipient"]["id"], "kind": "przypomnienie",
                              "title": candidate["title"],
                              "body": f"{candidate['message']}\n\n{note}" if note else candidate["message"],
                              "createdAt": now, "caseId": candidate["caseId"], "link": f"/oceny/{candidate['caseId']}",
                              "sender": sender})
        log.append({"id": nid, "sentAt": now, "sender": sender, "recipient": candidate["recipient"],
                    "caseId": candidate["caseId"], "employeeName": candidate["employeeName"],
                    "title": candidate["title"], "channel": "aplikacja"})
    s["notifications"] = notifications + s["notifications"]
    s["reminderLog"] = log + s["reminderLog"]
    for c in s["cases"]:
        for candidate in (x for x in selected if x["caseId"] == c["id"]):
            c["history"].append(history_event(
                now, sender, "przypomnienie",
                f"Kadry wysłały przypomnienie do {candidate['recipient']['fullName']}: {candidate['title']}."))
    ctx.ws.touch()
    return {"sent": len(selected)}


def register(router: Router) -> None:
    (router
     .get("/notifications", _list)
     .post("/notifications/read-all", _read_all)
     .post("/notifications/:id/read", _read)
     .get("/reminders/rules", _rules)
     .put("/reminders/rules/:id", _update_rule)
     .get("/reminders/candidates", _candidates)
     .get("/reminders/log", _log)
     .post("/reminders/send", _send))
