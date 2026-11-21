import os
os.environ.update(KOMPAS_LLM_PROVIDER="mock", KOMPAS_USE_RERANKER="false", KOMPAS_DENSE_ENABLED="false",
                  KOMPAS_SESSIONS_DB="data/test_sessions.sqlite")
from fastapi.testclient import TestClient
from app.main import app


def test_chat_and_memory(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "llm_provider", "mock")
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "ok"
        r = c.post("/api/v1/chat", json={"session_id": "t1", "message": "Ile kryteriów dodatkowych mogę wybrać?",
                                         "context": {"process": "okresowa", "arkusz": "C"}})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["citations"] and body["citations"][0]["chunk_id"]
        assert not body["abstained"]
        # follow-up uses session history (condense is mocked -> returns raw question)
        r2 = c.post("/api/v1/chat", json={"session_id": "t1", "message": "A kto o tym decyduje?"})
        assert r2.status_code == 200
        hist = c.get("/api/v1/sessions/t1").json()["messages"]
        assert [m["role"] for m in hist] == ["user", "assistant", "user", "assistant"]
        src = c.get(f"/api/v1/sources/{body['citations'][0]['chunk_id']}")
        assert src.status_code == 200 and src.json()["text"]
        # trap -> abstain path works when nothing matches
        r3 = c.post("/api/v1/chat", json={"session_id": "t2", "message": "xyzzy qwerty blorp"})
        assert r3.json()["abstained"] is True
