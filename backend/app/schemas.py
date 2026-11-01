from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10_000)
    session_id: UUID | None = None
    provider: Literal["openai", "ollama"] | None = None
    mode: Literal["normal", "rag"] = "rag"


class Source(BaseModel):
    filename: str
    chunk_index: int
    content: str


class QueryResponse(BaseModel):
    session_id: UUID
    response: str
    sources: list[Source]