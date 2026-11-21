from typing import Literal, Optional
from pydantic import BaseModel, Field

DocType = Literal["akt_prawny", "poradnik", "model_kompetencji", "arkusz", "faq", "regula_narzedzia"]
Process = Literal["okresowa", "pierwsza", "both"]


class Chunk(BaseModel):
    id: str
    text: str                                   # text that is embedded (with context prefix)
    source_id: str
    source_title: str
    doc_type: DocType
    process: Process = "both"
    citation: str = ""                          # "§ 11 ust. 1", "art. 81 ust. 7", "rozdz. 5.1", "Rzetelność / wskaźnik 2"
    page: Optional[int] = None
    parent_id: Optional[str] = None
    parent_text: Optional[str] = None           # kept for parent expansion (not embedded)
    chunk_type: str = "section"                 # ustep | pkt | przypis | section | example | indicator_full | competency_overview | model_rules | faq
    authority: int = 2                          # 3 akt prawny, 2 poradnik/model/arkusz, 1 faq
    extra: dict = Field(default_factory=dict)

    def chroma_metadata(self) -> dict:
        m = {
            "source_id": self.source_id,
            "source_title": self.source_title,
            "doc_type": self.doc_type,
            "process": self.process,
            "citation": self.citation,
            "chunk_type": self.chunk_type,
            "authority": self.authority,
            "parent_id": self.parent_id or "",
            "page": self.page if self.page is not None else -1,
        }
        return m


class Citation(BaseModel):
    n: int
    chunk_id: str
    source_title: str
    citation: str
    snippet: str
    doc_type: str
    page: Optional[int] = None
    score: float = 0.0


class ChatRequest(BaseModel):
    session_id: str
    message: str
    mode: Literal["formal", "conversation"] = "formal"
    context: dict = Field(default_factory=dict)   # {"process": "okresowa", "arkusz": "C", "step": "kryteria", ...}


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    abstained: bool
    confidence: Literal["high", "medium", "low"]
    rewritten_query: str
    latency_ms: int
    trace_id: str
