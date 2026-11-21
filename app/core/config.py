from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_prefix="KOMPAS_", extra="ignore")

    # --- paths ---
    data_dir: Path = ROOT / "data"
    chunks_path: Path = ROOT / "data" / "chunks.jsonl"
    chroma_dir: Path = ROOT / "data" / "chroma"
    sessions_db: Path = ROOT / "data" / "sessions.sqlite"
    traces_path: Path = ROOT / "data" / "traces.jsonl"

    # --- retrieval ---
    dense_enabled: bool = True                     # False -> BM25-only (offline fallback)
    embedding_model: str = "BAAI/bge-m3"          # alt: Qwen/Qwen3-Embedding-0.6B, sdadas/mmlw-retrieval-roberta-large
    embedding_provider: str = "local"              # local | voyage
    voyage_model: str = "voyage-3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"  # alt: sdadas/polish-reranker-roberta-v2
    use_reranker: bool = True
    collection_name: str = "kompas_v1"
    dense_top_k: int = 20
    bm25_top_k: int = 20
    final_top_k: int = 5
    rrf_k: int = 60
    faq_boost: float = 1.3
    abstain_threshold: float = 0.30               # reranker score; calibrate on golden set

    # --- generation (litellm model strings) ---
    llm_provider: str = "anthropic"                # anthropic | gemini | ollama | mock (offline smoke test)
    answer_model: str = "anthropic/claude-sonnet-5-5"
    fast_model: str = "anthropic/claude-haiku-5-5"   # condense, judge
    gemini_answer_model: str = "gemini/gemini-2.5-flash"
    ollama_answer_model: str = "ollama/bielik"
    max_history_messages: int = 6
    answer_max_tokens: int = 900
    temperature: float = 0.0

    # --- api ---
    admin_token: str = "change-me"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    def resolved_answer_model(self) -> str:
        return {"anthropic": self.answer_model, "mock": "mock",
                "gemini": self.gemini_answer_model,
                "ollama": self.ollama_answer_model}[self.llm_provider]

    def resolved_fast_model(self) -> str:
        return self.fast_model if self.llm_provider == "anthropic" else self.resolved_answer_model()


settings = Settings()
