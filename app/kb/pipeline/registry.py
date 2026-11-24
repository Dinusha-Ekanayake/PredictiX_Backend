"""The source registry (kb/sources.yaml): schema and validation.

Validation is strict on purpose. A typo in a licence, an unknown warehouse
code or a missing audience stops the run before anything is downloaded.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.kb.pipeline.config import REGISTRY_PATH

Audience = Literal["user", "admin", "super_admin"]
Jurisdiction = Literal["US", "UK", "LK", "INT"]
DocType = Literal[
    "regulation", "legislation", "guidance", "code_of_practice", "technical_manual",
    "handbook", "review_article", "internal_sop", "internal_data",
]
Feature = Literal["warehouse_reports", "asset_reports", "chatbot", "prediction_explanations", "compliance"]
AssetCategory = Literal["road_vehicle", "forklift"]
Component = Literal[
    "engine", "oil", "cooling", "brakes", "tyres", "battery", "hydraulics",
    "steering", "suspension", "electrical", "lifting", "general",
]

WAREHOUSE_CODES = ("LL-COL", "LL-GLE", "LL-BDL")
_SOURCE_ID = re.compile(r"^(S\d{2}|D\d{2}|W-[A-Z]{3}-\d{2})$")
_PUBLISHED = re.compile(r"^(n\.d\.|\d{4}(-\d{2}(-\d{2})?)?)$")
_PAGES = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")
_STORAGE_PATH = re.compile(r"^incoming/[A-Za-z0-9_-]+(/[A-Za-z0-9_.-]+)+\.(pdf|md)$")


class FetchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Public documents are downloaded from `url`; internal formats
    # (db_ticket_patterns) are built from the PredictiX database and have none.
    url: Optional[str] = None
    # Internal documents uploaded by the team: a path under incoming/ in the
    # private kb-sources bucket. Allowed only for W- (internal) sources.
    storage_path: Optional[str] = None
    format: Literal["pdf", "ecfr_xml", "markdown", "db_ticket_patterns"]
    pages: Optional[str] = None
    # How PDF section headings are recognised: `auto` (numbered or capitalised
    # titles), `multilevel` (only "8.1.6.2."-style numbers), or `none` (the
    # document's headings do not survive text extraction; cite by page).
    headings: Literal["auto", "multilevel", "none"] = "auto"
    # Keep only these sections (exact labels), when the selected pages also
    # carry the ends of neighbouring, out-of-scope sections.
    include_sections: Optional[list[str]] = None

    @field_validator("url")
    @classmethod
    def _https(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith("https://"):
            raise ValueError("fetch URLs must use https")
        return v

    @field_validator("storage_path")
    @classmethod
    def _storage_path(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (not _STORAGE_PATH.match(v) or ".." in v):
            raise ValueError("storage_path must look like incoming/<folder>/<file>.pdf or .md")
        return v

    @model_validator(mode="after")
    def _location_matches_format(self) -> "FetchSpec":
        if self.format.startswith("db_"):
            if self.url or self.storage_path:
                raise ValueError("an internal (db_*) format is built from the database and takes no url or path")
            return self
        if bool(self.url) == bool(self.storage_path):
            raise ValueError(f"format {self.format} needs exactly one of url or storage_path")
        if self.format == "markdown" and self.url:
            raise ValueError("markdown is supported for uploaded internal documents only")
        return self

    @property
    def internal(self) -> bool:
        return self.format.startswith("db_")

    @field_validator("pages")
    @classmethod
    def _pages(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            parse_pages(v)
        return v


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str = Field(min_length=3)
    container: Optional[str] = None
    publisher: str
    authors: list[str] = Field(default_factory=list)
    edition: Optional[str] = None
    identifiers: list[str] = Field(default_factory=list)
    published: str
    url: str            # public page of the source, or a predictix:// reference for internal data
    doi: Optional[str] = None
    fetch: list[FetchSpec] = Field(min_length=1)
    licence: str = Field(min_length=3)
    licence_url: Optional[str] = None
    licence_evidence: str = Field(min_length=10)
    attribution: str = Field(min_length=10)
    jurisdiction: Jurisdiction
    doc_type: DocType
    applicability: str = Field(min_length=20)
    scope: Literal["network", "warehouse"] = "network"
    warehouses: list[str] = Field(default_factory=list)
    audience: list[Audience] = Field(min_length=1)
    supports: list[Feature] = Field(min_length=1)
    asset_categories: list[AssetCategory] = Field(min_length=1)
    components: list[Component] = Field(min_length=1)
    status: Literal["active", "withdrawn"] = "active"
    review_due: date

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _SOURCE_ID.match(v):
            raise ValueError("id must look like S01 (published), D01 (derived from PredictiX data) or W-COL-01 (internal document)")
        return v

    @field_validator("published")
    @classmethod
    def _published(cls, v: str) -> str:
        if not _PUBLISHED.match(v):
            raise ValueError("published must be YYYY, YYYY-MM, YYYY-MM-DD or n.d.")
        return v

    @field_validator("warehouses")
    @classmethod
    def _warehouses(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(WAREHOUSE_CODES))
        if unknown:
            raise ValueError(f"unknown warehouse codes: {unknown}")
        return v

    @model_validator(mode="after")
    def _internal_documents(self) -> "Source":
        uploaded = any(f.storage_path for f in self.fetch)
        if uploaded and not self.id.startswith("W-"):
            raise ValueError("only W- internal sources may load uploaded files")
        if self.id.startswith("W-") and self.scope != "warehouse":
            raise ValueError("a W- internal source must be scoped to its warehouse")
        return self

    @model_validator(mode="after")
    def _scope(self) -> "Source":
        if self.scope == "network" and self.warehouses:
            raise ValueError("a network-scoped source must not list warehouses")
        if self.scope == "warehouse" and not self.warehouses:
            raise ValueError("a warehouse-scoped source must list at least one warehouse")
        return self

    @property
    def short_title(self) -> str:
        """The title up to the first colon or dash, for passage headings."""
        return re.split(r"\s[-:]\s|:\s", self.title, maxsplit=1)[0][:80]


class ExcludedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    url: str
    reason: str = Field(min_length=10)
    decided: date


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_version: int
    sources: list[Source]
    excluded: list[ExcludedSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> "Registry":
        ids = [s.id for s in self.sources]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate source ids: {dupes}")
        return self

    def get(self, source_id: str) -> Source:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise KeyError(source_id)

    @property
    def active(self) -> list[Source]:
        return [s for s in self.sources if s.status == "active"]


def parse_pages(spec: str) -> list[int]:
    """'4-6,10' -> [4, 5, 6, 10] (1-based, sorted, unique)."""
    if not _PAGES.match(spec):
        raise ValueError(f"bad page spec {spec!r}; use e.g. '4-24,35-43'")
    pages: set[int] = set()
    for part in spec.split(","):
        start, _, end = part.partition("-")
        lo, hi = int(start), int(end or start)
        if lo < 1 or hi < lo:
            raise ValueError(f"bad page range {part!r}")
        pages.update(range(lo, hi + 1))
    return sorted(pages)


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    with open(path, encoding="utf-8") as fh:
        return Registry.model_validate(yaml.safe_load(fh))
