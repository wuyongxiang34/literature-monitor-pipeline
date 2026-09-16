from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Paper:
    title: str
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    publication_date: str = ""
    doi: str = ""
    arxiv_id: str = ""
    openalex_id: str = ""
    semantic_scholar_id: str = ""
    wos_id: str = ""
    url: str = ""
    pdf_url: str = ""
    institutions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    document_type: str = "article"
    citation_count: int = 0
    sources: list[str] = field(default_factory=list)
    reading_depth: str = "Metadata only"
    matched_terms: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)
    score_total: int = 0
    score_rationale: str = ""
    classification: str = "E_暂存低优先"
    sci_status: str = "Unverified"
    corresponding_author: str = ""
    corresponding_author_email: str = ""
    abstract_cn: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Paper":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value[key] for key in allowed if key in value})
