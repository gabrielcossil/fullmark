from typing import Literal
from pydantic import BaseModel, Field


class Protocol(BaseModel):
    question: str = Field(min_length=10, max_length=4000)
    inclusion: list[str] = Field(min_length=1, max_length=20)
    exclusion: list[str] = Field(min_length=1, max_length=20)
    pico: dict[str, str] = Field(default_factory=dict)


class ReviewCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    protocol: Protocol


class SearchCreate(BaseModel):
    query: str = Field(min_length=3, max_length=4000)
    max_records: int = Field(default=50, ge=1, le=200)


class DecisionCreate(BaseModel):
    stage: Literal["title_abstract", "full_text"]
    verdict: Literal["include", "exclude", "uncertain", "not_retrieved"]
    reason: str = Field(min_length=5, max_length=4000)


class Finding(BaseModel):
    article_id: str
    recommendation: Literal["include", "exclude", "uncertain"]
    reason: str = Field(min_length=1, max_length=3000)
    quote: str = Field(max_length=2000)


class BrowserOutput(BaseModel):
    findings: list[Finding] = Field(max_length=200)
    sources: list[str] = Field(default_factory=list, max_length=40)


class ExtractionItem(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)
    page: int = Field(ge=1)
    quote: str = Field(min_length=5, max_length=2000)


class ExtractionCreate(BaseModel):
    items: list[ExtractionItem] = Field(min_length=1, max_length=40)


class PasswordSet(BaseModel):
    password: str = Field(min_length=12, max_length=128)
