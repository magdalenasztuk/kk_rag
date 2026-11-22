import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
ON_VERCEL = bool(os.environ.get("VERCEL"))
# Na Vercelu system plików jest tylko do odczytu poza /tmp.
RUNTIME_DIR = Path("/tmp/kompas") if ON_VERCEL else ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_prefix="KOMPAS_", extra="ignore")

    # --- paths ---
    data_dir: Path = ROOT / "data"
    chunks_path: Path = ROOT / "data" / "chunks.jsonl"
    chroma_dir: Path = ROOT / "data" / "chroma"
    sessions_db: Path = RUNTIME_DIR / "sessions.sqlite"
    traces_path: Path = RUNTIME_DIR / "traces.jsonl"
    workspaces_db: Path = RUNTIME_DIR / "workspaces.sqlite"

    # --- application state (workspaces) ---
    database_url: str = Field(default="", validation_alias=AliasChoices(
        "KOMPAS_DATABASE_URL", "DATABASE_URL", "POSTGRES_URL"))

    # --- retrieval ---
    dense_enabled: bool = not ON_VERCEL            # False -> BM25-only (offline fallback, Vercel)
    embedding_model: str = "BAAI/bge-m3"          # alt: Qwen/Qwen3-Embedding-0.6B, sdadas/mmlw-retrieval-roberta-large
    embedding_provider: str = "local"              # local | voyage
    voyage_model: str = "voyage-3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # alt: sdadas/polish-reranker-roberta-v2
    use_reranker: bool = not ON_VERCEL
    collection_name: str = "kompas_v1"
    dense_top_k: int = 20
    bm25_top_k: int = 20
    final_top_k: int = 5
    rrf_k: int = 60
    faq_boost: float = 1.3
    faq_linked_pin: int = 1                       # after rerank, keep N best FAQ-cited legal chunks right below the FAQ hit
    min_legal_in_top: int = 2                     # reserve slots in final top-k for the best akt_prawny chunks
    abstain_threshold: float = 0.30               # reranker score; calibrate on golden set
    multi_query: bool = True                      # bez modelu dense: LLM dopisuje 2 parafrazy z terminologią przepisów

    # --- generation (litellm model strings; provider "anthropic" calls the Anthropic SDK directly) ---
    llm_provider: str = "anthropic"                # anthropic | gemini | ollama | mock (offline smoke test)
    answer_model: str = "anthropic/claude-sonnet-5-5"
    fast_model: str = "anthropic/claude-haiku-5-5"   # condense, judge, multi-query, drafts
    gemini_answer_model: str = "gemini/gemini-2.5-flash"
    ollama_answer_model: str = "ollama/bielik"
    max_history_messages: int = 6
    answer_max_tokens: int = 2000                   # 900 truncated longer legal answers mid-JSON; 1500 was borderline
    temperature: float = 0.0
    llm_timeout_s: float = 45.0

    # --- api ---
    admin_token: str = "change-me"
    auth_secret: str = ""  # podpis tokenów sesji; pusty → domyślny sekret demo (ustaw na Vercel)
    auth_ttl_hours: int = 12
    cors_origins: list[str] = [
        "http://localhost:3000", "http://localhost:4200", "http://localhost:4300", "http://localhost:5173",
        "http://127.0.0.1:4300", "https://kompas-kompetencji.vercel.app",
    ]

    def resolved_answer_model(self) -> str:
        return {"anthropic": self.answer_model, "mock": "mock",
                "gemini": self.gemini_answer_model,
                "ollama": self.ollama_answer_model}[self.llm_provider]

    def resolved_fast_model(self) -> str:
        return self.fast_model if self.llm_provider == "anthropic" else self.resolved_answer_model()

    def llm_available(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(os.environ.get("ANTHROPIC_API_KEY"))
        return self.llm_provider in ("gemini", "ollama", "mock")


settings = Settings()

# .env is read by pydantic only for KOMPAS_* fields; the SDK reads ANTHROPIC_API_KEY from the environment.
if not os.environ.get("ANTHROPIC_API_KEY") and (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY=") and line.split("=", 1)[1].strip():
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()
