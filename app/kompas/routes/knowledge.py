from __future__ import annotations

from app.kompas import knowledge
from app.kompas import reference as ref
from app.kompas.access import can_see_case
from app.kompas.ai import assistant
from app.kompas.engines.assistant_rules import suggested_questions
from app.kompas.errors import bad_request
from app.kompas.router import RouteContext, Router

MAX_QUESTION_LENGTH = 500


def _path(value: str | None) -> str | None:
    return value if value in ("periodic", "first") else None


def _mode(value) -> str:
    return "rozmowa" if value == "rozmowa" else "formalny"


def _ask(ctx: RouteContext) -> dict:
    body = ctx.json()
    question = str(body.get("question") or "").strip()
    if not question:
        raise bad_request("Wpisz pytanie.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise bad_request(f"Pytanie może mieć najwyżej {MAX_QUESTION_LENGTH} znaków.")
    context = body.get("context") if isinstance(body.get("context"), dict) else None
    payload = {"question": question, "mode": _mode(body.get("mode")),
               **({"context": context} if context else {}),
               **({"history": body["history"]} if isinstance(body.get("history"), list) else {})}
    case = None
    case_id = (context or {}).get("caseId")
    if case_id:
        found = next((c for c in ctx.ws.cases if c["id"] == case_id), None)
        # Kadry widzą przebieg sprawy bez treści — model też nie dostaje treści.
        if found and can_see_case(found, ctx.user) and "hr" not in ctx.user["roles"]:
            case = found
    return assistant.ask(payload, ctx.ws.now(), case)


def register(router: Router) -> None:
    (router
     .get("/reference/competency-model", lambda ctx: ref.competency_model())
     .get("/knowledge/sources", lambda ctx: knowledge.sources())
     .get("/knowledge/fragments", lambda ctx: knowledge.fragments(ctx.query.get("sourceId"), ctx.query.get("q")))
     .get("/knowledge/fragments/:id", lambda ctx: knowledge.fragment(ctx.params["id"]))
     .get("/assistant/suggestions",
          lambda ctx: suggested_questions(_path(ctx.query.get("path")), _mode(ctx.query.get("mode"))))
     .get("/assistant/status", lambda ctx: assistant.status())
     .post("/assistant/ask", _ask, ai=True))
