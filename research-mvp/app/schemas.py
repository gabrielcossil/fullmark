from typing import Literal
from pydantic import BaseModel, Field
from .research import Filters


class Protocol(BaseModel):
    question: str = Field(min_length=10, max_length=4000)
    inclusion: list[str] = Field(min_length=1, max_length=20)
    exclusion: list[str] = Field(min_length=1, max_length=20)
    pico: dict[str, str] = Field(default_factory=dict)
    database: Literal["pubmed"] = "pubmed"
    observations: str = Field(default="", max_length=5000)
    max_records: int = Field(default=50, ge=1, le=200)
    filters: Filters = Field(default_factory=Filters)
    source_document: dict[str, str | int | bool] = Field(default_factory=dict, max_length=8)
    clickup_task_id: str = Field(default="", max_length=100)
    auto_search: bool = False


class ReviewCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    protocol: Protocol


class SearchCreate(BaseModel):
    query: str = Field(min_length=3, max_length=4000)
    max_records: int = Field(default=50, ge=1, le=200)
    filters: Filters | None = None
    automatic_screening: bool = False


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


class Concept(BaseModel):
    label: str = Field(max_length=200)
    mesh: list[str] = Field(default_factory=list, max_length=5)
    synonyms: list[str] = Field(default_factory=list, max_length=8)


class Strategy(BaseModel):
    label: str = Field(max_length=200)
    query: str = Field(min_length=3, max_length=4000)
    rationale: str = Field(max_length=1000)


class PlanningOutput(BaseModel):
    themes: list[str] = Field(min_length=1, max_length=5)
    question: str = Field(min_length=10, max_length=4000)
    inclusion: list[str] = Field(min_length=1, max_length=20)
    exclusion: list[str] = Field(min_length=1, max_length=20)
    pico: dict[str, str] = Field(default_factory=dict)
    filters: Filters = Field(default_factory=Filters)
    concepts: list[Concept] = Field(min_length=1, max_length=6)
    strategies: list[Strategy] = Field(min_length=1, max_length=4)
    cautions: list[str] = Field(default_factory=list, max_length=10)


class BulkDecision(BaseModel):
    article_ids: list[str] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=5, max_length=4000)


class IntakeAttachment(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=10, max_length=4000)


class IntakeCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    task_id: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    production_text: str = Field(default="", max_length=20000)
    attachments: list[IntakeAttachment] = Field(default_factory=list, max_length=20)
    max_records: int = Field(default=50, ge=1, le=200)
