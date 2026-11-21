import os
import tempfile

# Testy działają bez modeli lokalnych (BM25) i bez klucza API; poszczególne testy podstawiają model.
os.environ.setdefault("KOMPAS_DENSE_ENABLED", "false")
os.environ.setdefault("KOMPAS_USE_RERANKER", "false")

# Każde uruchomienie zaczyna od pustej pamięci rozmów i pustych przestrzeni roboczych.
_runtime = tempfile.mkdtemp(prefix="kompas-tests-")
os.environ.setdefault("KOMPAS_SESSIONS_DB", os.path.join(_runtime, "sessions.sqlite"))
os.environ.setdefault("KOMPAS_TRACES_PATH", os.path.join(_runtime, "traces.jsonl"))
os.environ.setdefault("KOMPAS_WORKSPACES_DB", os.path.join(_runtime, "workspaces.sqlite"))
