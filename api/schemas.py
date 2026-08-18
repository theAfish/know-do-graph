from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.memory.memgraph import MemEntry
from core.schemas.edge import Edge
from core.schemas.entry import Entry, EntryType, RemoteSource


class PaginationMeta(BaseModel):
    limit: int
    offset: int = 0
    count: int
    total: int | None = None


class EntryListResponse(BaseModel):
    items: list[Entry]
    pagination: PaginationMeta


class EntrySearchItem(Entry):
    model_config = ConfigDict(populate_by_name=True)

    score: float | None = Field(
        default=None, validation_alias="_score", serialization_alias="_score"
    )


class EntrySearchResponse(BaseModel):
    items: list[EntrySearchItem]
    pagination: PaginationMeta
    query: str | None = None
    tags: list[str] | None = None
    entry_type: EntryType | str | None = None


class EdgeListResponse(BaseModel):
    items: list[Edge]
    pagination: PaginationMeta


class ScriptSummary(BaseModel):
    filename: str
    language: str
    requirements: list[str]
    description: str
    download_url: str


class AssetMetadata(BaseModel):
    folder: str
    filename: str
    path: str
    kind: str
    language: str | None = None
    mime_type: str | None = None
    description: str
    requirements: list[str]
    size: int
    download_url: str
    metadata: dict[str, Any]


class EntryAssetsResponse(BaseModel):
    entry_id: str
    slug: str
    folders: dict[str, list[AssetMetadata]]
    total: int


class AssetFolderResponse(BaseModel):
    entry_id: str
    folder: str
    items: list[AssetMetadata]


class GraphStatsResponse(BaseModel):
    nodes: int
    edges: int
    is_dag: bool
    unreviewed_nodes: int


class GraphPathResponse(BaseModel):
    source: str
    target: str
    paths: list[list[str]]


class GraphDataResponse(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class GraphReloadResponse(BaseModel):
    reloaded: bool
    nodes: int
    edges: int


class ProgressiveEntry(Entry):
    model_config = ConfigDict(populate_by_name=True)

    level: str | None = Field(default=None, validation_alias="_level", serialization_alias="_level")


class MemoryTraceListResponse(BaseModel):
    items: list[MemEntry]
    pagination: PaginationMeta
    session_id: str


class RemoteSyncResult(BaseModel):
    entry_id: str
    title: str
    status: str
    detail: str
    bytes_fetched: int
    new_hash: str | None = None
    fetched_at: str | None = None


class RemoteLinkedEntry(BaseModel):
    entry_id: str
    slug: str
    title: str
    remote_source: RemoteSource


class RemoteSyncAllResponse(BaseModel):
    checked: int
    updated: int
    unchanged: int
    errors: int
    results: list[RemoteSyncResult]


class RemoteSyncOneResponse(BaseModel):
    result: RemoteSyncResult
    remote_source: RemoteSource
    autolink: dict[str, Any] | None = None


class RemoteSourceUpdateResponse(BaseModel):
    remote_source: RemoteSource
    result: RemoteSyncResult | None = None


class RemoteSourceDetachResponse(BaseModel):
    detached: bool
    entry_id: str


class AgentTextResponse(BaseModel):
    response: str


class AgentReviewProgress(BaseModel):
    completed: int
    total: int
    percent: int


class AgentMemoryReviewJob(BaseModel):
    job_id: str
    status: str
    session_id: str | None = None
    progress: AgentReviewProgress
    results: list[dict[str, Any]]
    errors: list[str]
    summary: str


class RemoteChatResponse(BaseModel):
    response: str
    session_id: str


class RemoteEntrySummary(BaseModel):
    id: str
    title: str
    slug: str
    entry_type: str
    tags: list[str]
    aliases: list[str]
    snippet: str


class RemoteGraphOverviewResponse(BaseModel):
    is_dag: bool
    unreviewed_nodes: int
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class RemoteAttachedSearchResponse(BaseModel):
    total_attached: int
    returned: int
    query: str | None = None
    results: list[RemoteEntrySummary]


class RemoteFeedbackResponse(BaseModel):
    id: str
    session_id: str
    stored: bool
    entry_feedback: dict[str, Any] | None = None


class RemoteSubmitResponse(BaseModel):
    submitted: bool
    ids: list[str]
    session_id: str
    tag: str


class RemoteInboxItem(BaseModel):
    id: str
    session_id: str
    title: str
    preview: str
    tags: list[str]
    created_at: str
    source_format: str


class RemoteDistillResponse(BaseModel):
    distilled: int | None = None
    message: str | None = None
    dry_run: bool | None = None
    pending_count: int | None = None
    prompt: str | None = None
    response: str | None = None
