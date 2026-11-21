from __future__ import annotations

from app.kompas import reference as ref
from app.kompas.errors import not_found
from app.kompas.router import RouteContext, Router
from app.kompas.workspace import Workspace

STAGES = ["nowe", "weryfikacja", "rozmowa", "decyzja"]
RATINGS = ["spelnia", "do-poglebienia", "powyzej", "nie-spelnia"]
MAX_NOTE_LENGTH = 2000


def _with_counts(ws: Workspace, recruitment: dict) -> dict:
    candidates = [c for c in ws.state["candidates"] if c["recruitmentId"] == recruitment["id"]]
    return {**recruitment, "candidateCount": len(candidates),
            "stageCounts": {s: sum(1 for c in candidates if c["stage"] == s) for s in STAGES}}


def _find_recruitment(ws: Workspace, recruitment_id: str) -> dict:
    found = next((r for r in ref.recruitments() if r["id"] == recruitment_id), None)
    if not found:
        raise not_found("nabór")
    return _with_counts(ws, found)


def _find_candidate(ws: Workspace, candidate_id: str) -> dict:
    found = next((c for c in ws.state["candidates"] if c["id"] == candidate_id), None)
    if not found:
        raise not_found("kandydat")
    return found


def _recruitment(ctx: RouteContext) -> dict:
    recruitment = _find_recruitment(ctx.ws, ctx.params["id"])
    candidates = [c for c in ctx.ws.state["candidates"] if c["recruitmentId"] == recruitment["id"]]
    return {"recruitment": recruitment, "candidates": sorted(candidates, key=lambda c: c["appliedAt"])}


def _candidate(ctx: RouteContext) -> dict:
    candidate = _find_candidate(ctx.ws, ctx.params["id"])
    return {"candidate": candidate, "recruitment": _find_recruitment(ctx.ws, candidate["recruitmentId"])}


def _patch_candidate(ctx: RouteContext) -> dict:
    candidate = _find_candidate(ctx.ws, ctx.params["id"])
    body = ctx.json()
    if body.get("stage") in STAGES:
        candidate["stage"] = body["stage"]
    if isinstance(body.get("committeeNote"), str):
        candidate["committeeNote"] = body["committeeNote"][:MAX_NOTE_LENGTH]
    ratings = {r.get("competencyId"): r.get("rating") for r in body.get("ratings") or [] if isinstance(r, dict)}
    for item in candidate["evidence"]:
        if item["competencyId"] not in ratings:
            continue
        rating = ratings[item["competencyId"]]
        if rating in RATINGS:
            item["rating"] = rating
        else:
            item.pop("rating", None)
    ctx.ws.touch()
    return candidate


def register(router: Router) -> None:
    (router
     .get("/recruitments", lambda ctx: [_with_counts(ctx.ws, r) for r in ref.recruitments()])
     .get("/recruitments/:id", _recruitment)
     .get("/candidates/:id", _candidate)
     .patch("/candidates/:id", _patch_candidate))
