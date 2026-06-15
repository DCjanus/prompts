#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "openai-codex>=0.1.0b2",
#     "pydantic>=2.13.4",
#     "rich>=15.0.0",
#     "typer>=0.26.7",
# ]
# ///

"""通过 Codex Python SDK 汇总过去一周的 Codex sessions。"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Annotated, Any

from openai_codex import Codex, Sandbox
from openai_codex.generated.v2_all import (
    ReasoningEffort,
    SortDirection,
    ThreadSortKey,
    ThreadSourceKind,
)
from pydantic import BaseModel, Field
from rich.console import Console
import typer


app = typer.Typer(no_args_is_help=True)
console = Console()

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "codex-weekly-session-review"
DEFAULT_FAST_MODEL = "gpt-5.3-codex-spark"
DEFAULT_FINAL_MODEL = "gpt-5.5"
DEFAULT_SOURCE_KINDS = [
    ThreadSourceKind.cli,
    ThreadSourceKind.vscode,
    ThreadSourceKind.exec,
    ThreadSourceKind.app_server,
    ThreadSourceKind.unknown,
]


@dataclass
class ThreadListing:
    """thread list 结果和跳过统计。"""

    ids: list[str]
    excluded_counts: dict[str, int] = dataclass_field(default_factory=dict)


class SessionDigest(BaseModel):
    """单个 Codex thread 的确定性抽取结果。"""

    thread_id: str
    session_id: str | None = None
    forked_from_id: str | None = None
    archived: bool
    name: str | None = None
    preview: str
    cwd: str
    source: str | None = None
    created_at: int
    updated_at: int
    evidence_first_at: int
    evidence_last_at: int
    total_turns: int
    evidence_turns: int
    context_buffer_turns: int
    evidence_since: int
    context_since: int
    window_until: int
    item_counts: dict[str, int] = Field(default_factory=dict)
    context_buffer: list[str] = Field(default_factory=list)
    context_compactions_in_evidence: int = 0
    context_compactions_in_buffer: int = 0
    first_user_messages: list[str] = Field(default_factory=list)
    final_answers: list[str] = Field(default_factory=list)
    assistant_messages_tail: list[str] = Field(default_factory=list)
    command_samples: list[str] = Field(default_factory=list)
    file_change_samples: list[str] = Field(default_factory=list)


class CollectionResult(BaseModel):
    """一段时间内的 Codex thread 抽取结果。"""

    generated_at: str
    since: str
    until: str
    evidence_days: int | None = None
    context_days: int | None = None
    include_archived: bool
    limit: int | None = None
    excluded_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    sessions: list[SessionDigest]


class SessionSummary(BaseModel):
    """模型生成的单 session 摘要卡片。"""

    thread_id: str
    title: str
    topic: str
    outcome: str
    repos_or_paths: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    importance: str = "medium"
    evidence: list[str] = Field(default_factory=list)


class SummariesResult(BaseModel):
    """多 session 摘要卡片集合。"""

    generated_at: str
    fast_model: str
    source_collection: CollectionResult
    summaries: list[SessionSummary]


def iso_from_ts(value: int) -> str:
    """把秒级时间戳转成 UTC ISO 字符串。"""

    return utc_iso(datetime.fromtimestamp(value, tz=UTC))


def local_iso_from_ts(value: int) -> str:
    """把秒级时间戳转成本机本地时区 ISO 字符串。"""

    return datetime.fromtimestamp(value, tz=UTC).astimezone().isoformat()


def utc_iso(value: datetime) -> str:
    """把 datetime 转成 jq fromdateiso8601 友好的 UTC ISO 字符串。"""

    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def parse_datetime(value: str) -> datetime:
    """解析 CLI ISO datetime；无时区时按 UTC 处理。"""

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def enum_value(value: Any) -> str:
    """把 SDK enum 或普通值转成稳定字符串。"""

    return str(getattr(value, "value", value))


def item_dict(item: Any) -> dict[str, Any]:
    """把 SDK thread item 转成 JSON 友好的 dict。"""

    if hasattr(item, "model_dump"):
        return item.model_dump(by_alias=True, exclude_none=True, mode="json")
    if isinstance(item, dict):
        return item
    return {}


def source_text(source: Any) -> str | None:
    """格式化 SDK source 字段。"""

    if source is None:
        return None
    if hasattr(source, "model_dump"):
        dumped = source.model_dump(by_alias=True, exclude_none=True, mode="json")
        if isinstance(dumped, str):
            return dumped
        return json.dumps(dumped, ensure_ascii=False, sort_keys=True)
    return enum_value(source)


def path_text(path_value: Any) -> str:
    """格式化 SDK 路径对象。"""

    root = getattr(path_value, "root", None)
    if root:
        return str(root)
    return str(path_value)


def trim_text(value: str, limit: int) -> str:
    """裁剪长文本，避免摘要输入无限膨胀。"""

    normalized = "\n".join(line.rstrip() for line in value.splitlines()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 20].rstrip() + "\n...[truncated]"


def render_user_content(content: Any) -> str:
    """提取 userMessage content 中的文本。"""

    parts: list[str] = []
    for entry in content or []:
        if hasattr(entry, "model_dump"):
            data = entry.model_dump(by_alias=True, exclude_none=True, mode="json")
        elif isinstance(entry, dict):
            data = entry
        else:
            continue
        if data.get("type") == "text" and data.get("text"):
            parts.append(str(data["text"]))
        elif data.get("type"):
            parts.append(json.dumps(data, ensure_ascii=False, sort_keys=True))
    return "\n".join(parts).strip()


def turn_ts(turn: Any, fallback: int) -> int:
    """返回 turn 的代表时间戳。"""

    return int(turn.completed_at or turn.started_at or fallback)


def append_context_buffer(context_buffer: list[str], label: str, text: str) -> None:
    """保留证据窗口前一天的少量上下文原文。"""

    if not text:
        return
    context_buffer.append(trim_text(f"{label}: {text}", 1200))
    del context_buffer[:-8]


def digest_thread(
    codex: Codex,
    thread_id: str,
    archived: bool,
    *,
    evidence_since_ts: int,
    context_since_ts: int,
    until_ts: int,
) -> SessionDigest | None:
    """通过 SDK 读取 thread turns 并生成确定性摘要输入。"""

    thread = codex.thread_resume(thread_id)
    read = thread.read(include_turns=True).thread

    item_counts: dict[str, int] = {}
    first_user_messages: list[str] = []
    final_answers: list[str] = []
    assistant_messages: list[str] = []
    command_samples: list[str] = []
    file_change_samples: list[str] = []
    context_buffer: list[str] = []
    evidence_turn_ids: set[str] = set()
    context_buffer_turn_ids: set[str] = set()
    evidence_first_at: int | None = None
    evidence_last_at: int | None = None
    context_compactions_in_evidence = 0
    context_compactions_in_buffer = 0

    for turn in read.turns:
        current_turn_ts = turn_ts(turn, read.updated_at)
        in_evidence = evidence_since_ts <= current_turn_ts <= until_ts
        in_context_buffer = context_since_ts <= current_turn_ts < evidence_since_ts

        for raw_item in turn.items:
            item = item_dict(raw_item)
            item_type = str(item.get("type") or "unknown")
            if item_type == "contextCompaction":
                if in_evidence:
                    context_compactions_in_evidence += 1
                elif in_context_buffer:
                    context_compactions_in_buffer += 1

            if in_context_buffer:
                context_buffer_turn_ids.add(turn.id)
                if item_type == "userMessage":
                    append_context_buffer(
                        context_buffer,
                        "上下文缓冲用户请求",
                        render_user_content(item.get("content")),
                    )
                elif item_type == "agentMessage":
                    text = str(item.get("text") or "")
                    if enum_value(item.get("phase")) == "final_answer":
                        append_context_buffer(
                            context_buffer, "上下文缓冲最终回复", text
                        )
                continue

            if not in_evidence:
                continue

            if turn.id not in evidence_turn_ids:
                evidence_turn_ids.add(turn.id)
                if evidence_first_at is None or current_turn_ts < evidence_first_at:
                    evidence_first_at = current_turn_ts
                if evidence_last_at is None or current_turn_ts > evidence_last_at:
                    evidence_last_at = current_turn_ts
            item_counts[item_type] = item_counts.get(item_type, 0) + 1

            if item_type == "userMessage":
                text = render_user_content(item.get("content"))
                if text and len(first_user_messages) < 3:
                    first_user_messages.append(trim_text(text, 1200))
            elif item_type == "agentMessage":
                text = str(item.get("text") or "")
                if text:
                    phase = enum_value(item.get("phase"))
                    if phase == "final_answer":
                        final_answers.append(trim_text(text, 2000))
                    assistant_messages.append(trim_text(text, 800))
            elif item_type == "commandExecution":
                command = str(item.get("command") or "").strip()
                cwd = str(item.get("cwd") or "").strip()
                if command and len(command_samples) < 12:
                    prefix = f"{cwd}$ " if cwd else ""
                    command_samples.append(trim_text(prefix + command, 300))
            elif item_type == "fileChange" and len(file_change_samples) < 12:
                file_change_samples.append(
                    trim_text(json.dumps(item, ensure_ascii=False, sort_keys=True), 500)
                )

    if not evidence_turn_ids:
        return None

    if evidence_first_at is None or evidence_last_at is None:
        raise RuntimeError(f"missing evidence timestamps for thread {read.id}")

    return SessionDigest(
        thread_id=read.id,
        session_id=getattr(read, "session_id", None),
        forked_from_id=getattr(read, "forked_from_id", None),
        archived=archived,
        name=read.name,
        preview=trim_text(read.preview, 800),
        cwd=path_text(read.cwd),
        source=source_text(read.source),
        created_at=read.created_at,
        updated_at=read.updated_at,
        evidence_first_at=evidence_first_at,
        evidence_last_at=evidence_last_at,
        total_turns=len(read.turns),
        evidence_turns=len(evidence_turn_ids),
        context_buffer_turns=len(context_buffer_turn_ids),
        evidence_since=evidence_since_ts,
        context_since=context_since_ts,
        window_until=until_ts,
        item_counts=item_counts,
        context_buffer=context_buffer,
        context_compactions_in_evidence=context_compactions_in_evidence,
        context_compactions_in_buffer=context_compactions_in_buffer,
        first_user_messages=first_user_messages,
        final_answers=final_answers[-5:],
        assistant_messages_tail=assistant_messages[-8:],
        command_samples=command_samples,
        file_change_samples=file_change_samples,
    )


def list_recent_threads(
    codex: Codex,
    *,
    context_since_ts: int,
    until_ts: int,
    archived: bool,
    limit: int,
) -> ThreadListing:
    """通过 SDK 分页列出一类 thread id。"""

    ids: list[str] = []
    excluded_counts: dict[str, int] = {}
    cursor: str | None = None
    while True:
        page = codex.thread_list(
            archived=archived,
            cursor=cursor,
            limit=min(limit, 100),
            sort_direction=SortDirection.desc,
            sort_key=ThreadSortKey.updated_at,
            source_kinds=DEFAULT_SOURCE_KINDS,
        )
        for thread in page.data:
            if thread.updated_at < context_since_ts:
                return ThreadListing(ids=ids, excluded_counts=excluded_counts)
            reason = skip_reason(thread)
            if reason is not None:
                excluded_counts[reason] = excluded_counts.get(reason, 0) + 1
                continue
            if thread.updated_at <= until_ts:
                ids.append(thread.id)
                if len(ids) >= limit:
                    return ThreadListing(ids=ids, excluded_counts=excluded_counts)
        if not page.next_cursor:
            return ThreadListing(ids=ids, excluded_counts=excluded_counts)
        cursor = page.next_cursor


def should_skip_thread(thread: Any) -> bool:
    """过滤脚本自身生成的辅助线程和 fork 副本。"""

    return skip_reason(thread) is not None


def skip_reason(thread: Any) -> str | None:
    """返回 thread 被过滤的原因。"""

    if getattr(thread, "forked_from_id", None):
        return "fork"
    preview = str(getattr(thread, "preview", "") or "")
    helper_prefixes = (
        "请把下面这个 Codex session 抽取结果压缩成一张结构化摘要卡片。",
        "请根据下面这些 Codex session 摘要卡片，起草一则简短中文状态更新。",
    )
    if preview.startswith(helper_prefixes):
        return "summary_helper"
    return None


def collect_data(
    *,
    evidence_days: int,
    context_days: int,
    include_archived: bool,
    limit: int,
    until: datetime | None = None,
) -> CollectionResult:
    """通过 Codex SDK 收集过去 N 天的 active/archived threads。"""

    window_until = until or datetime.now(UTC)
    evidence_since = window_until - timedelta(days=evidence_days)
    context_since = window_until - timedelta(days=context_days)
    evidence_since_ts = int(evidence_since.timestamp())
    context_since_ts = int(context_since.timestamp())
    until_ts = int(window_until.timestamp())

    sessions: list[SessionDigest] = []
    excluded_counts: dict[str, dict[str, int]] = {}
    with Codex() as codex:
        active_listing = list_recent_threads(
            codex,
            context_since_ts=context_since_ts,
            until_ts=until_ts,
            archived=False,
            limit=limit,
        )
        excluded_counts["active"] = active_listing.excluded_counts
        sources = [(False, active_listing.ids)]
        if include_archived:
            archived_listing = list_recent_threads(
                codex,
                context_since_ts=context_since_ts,
                until_ts=until_ts,
                archived=True,
                limit=limit,
            )
            excluded_counts["archived"] = archived_listing.excluded_counts
            sources.append((True, archived_listing.ids))

        for archived, thread_ids in sources:
            for thread_id in thread_ids:
                session = digest_thread(
                    codex,
                    thread_id,
                    archived=archived,
                    evidence_since_ts=evidence_since_ts,
                    context_since_ts=context_since_ts,
                    until_ts=until_ts,
                )
                if session is not None and not session.forked_from_id:
                    sessions.append(session)

    sessions.sort(
        key=lambda item: (item.evidence_last_at, item.updated_at),
        reverse=True,
    )
    del sessions[limit:]
    return CollectionResult(
        generated_at=utc_iso(datetime.now(UTC)),
        since=utc_iso(evidence_since),
        until=utc_iso(window_until),
        evidence_days=evidence_days,
        context_days=context_days,
        include_archived=include_archived,
        limit=limit,
        excluded_counts=excluded_counts,
        sessions=sessions,
    )


def write_json(path: Path, payload: BaseModel | dict[str, Any]) -> None:
    """写入格式化 JSON 文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, BaseModel):
        text = payload.model_dump_json(indent=2)
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def read_collection(path: Path) -> CollectionResult:
    """读取 collect 输出。"""

    return CollectionResult.model_validate_json(path.read_text(encoding="utf-8"))


def json_text(payload: Any, *, pretty: bool = False) -> str:
    """生成 stdout 友好的 JSON 文本。"""

    indent = 2 if pretty else None
    separators = None if pretty else (",", ":")
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    return (
        json.dumps(data, ensure_ascii=False, indent=indent, separators=separators)
        + "\n"
    )


def inspect_rows(result: CollectionResult) -> list[dict[str, Any]]:
    """把 collection 转成 inspect 友好的稳定行。"""

    rows: list[dict[str, Any]] = []
    for session in result.sessions:
        title = session.name or session.preview
        rows.append(
            {
                "updated": iso_from_ts(session.updated_at),
                "updated_epoch": session.updated_at,
                "updated_local": local_iso_from_ts(session.updated_at),
                "evidence_first": iso_from_ts(session.evidence_first_at),
                "evidence_first_epoch": session.evidence_first_at,
                "evidence_first_local": local_iso_from_ts(session.evidence_first_at),
                "evidence_last": iso_from_ts(session.evidence_last_at),
                "evidence_last_epoch": session.evidence_last_at,
                "evidence_last_local": local_iso_from_ts(session.evidence_last_at),
                "archived": session.archived,
                "turns_label": f"{session.evidence_turns}/{session.total_turns}",
                "evidence_turns": session.evidence_turns,
                "context_buffer_turns": session.context_buffer_turns,
                "total_turns": session.total_turns,
                "thread_id": session.thread_id,
                "cwd": session.cwd,
                "title": title.replace("\n", " "),
            }
        )
    return rows


def inspect_payload(result: CollectionResult) -> dict[str, Any]:
    """返回 inspect 的机器可读输出。"""

    shown_active = sum(1 for session in result.sessions if not session.archived)
    shown_archived = len(result.sessions) - shown_active
    scanned_excluded_counts = normalize_excluded_counts(result.excluded_counts)
    scanned_excluded_total = sum(
        count for group in scanned_excluded_counts.values() for count in group.values()
    )
    return {
        "schema_version": 1,
        "output_version": 1,
        "generated_at": result.generated_at,
        "generated_at_epoch": int(parse_datetime(result.generated_at).timestamp()),
        "since": result.since,
        "since_epoch": int(parse_datetime(result.since).timestamp()),
        "since_local": parse_datetime(result.since).astimezone().isoformat(),
        "until": result.until,
        "until_epoch": int(parse_datetime(result.until).timestamp()),
        "until_local": parse_datetime(result.until).astimezone().isoformat(),
        "evidence_days": result.evidence_days,
        "context_days": result.context_days,
        "include_archived": result.include_archived,
        "limit": result.limit,
        "ordered_by": ["evidence_last_desc", "updated_desc"],
        "shown_count": len(result.sessions),
        "counts_are_after_limit": True,
        "counts_scope": "shown_after_limit",
        "scanned_excluded_scope": "scanned_until_limit",
        "maybe_more_than_limit": (
            result.limit is not None and len(result.sessions) >= result.limit
        ),
        "shown_active_count": shown_active,
        "shown_archived_count": shown_archived,
        "scanned_excluded_total": scanned_excluded_total,
        "scanned_excluded_counts": scanned_excluded_counts,
        "threads": inspect_rows(result),
    }


def normalize_excluded_counts(
    counts: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    """补齐已知排除计数，方便 Agent 直接消费。"""

    normalized: dict[str, dict[str, int]] = {}
    for scope in ("active", "archived"):
        group = counts.get(scope, {})
        normalized[scope] = {
            "fork": group.get("fork", 0),
            "summary_helper": group.get("summary_helper", 0),
        }
    return normalized


def inspect_schema() -> dict[str, Any]:
    """返回 inspect JSON 输出的机器可读 schema。"""

    string_schema = {"type": "string"}
    datetime_schema = {"type": "string", "format": "date-time"}
    integer_schema = {"type": "integer", "minimum": 0}
    boolean_schema = {"type": "boolean"}
    thread_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "updated",
            "updated_epoch",
            "updated_local",
            "evidence_first",
            "evidence_first_epoch",
            "evidence_first_local",
            "evidence_last",
            "evidence_last_epoch",
            "evidence_last_local",
            "archived",
            "turns_label",
            "evidence_turns",
            "context_buffer_turns",
            "total_turns",
            "thread_id",
            "cwd",
            "title",
        ],
        "properties": {
            "updated": {
                **datetime_schema,
                "description": "Thread metadata updated_at timestamp, not the evidence-window turn timestamp.",
            },
            "updated_epoch": integer_schema,
            "updated_local": {
                **datetime_schema,
                "description": "Thread metadata updated_at rendered in local timezone.",
            },
            "evidence_first": {
                **datetime_schema,
                "description": "Earliest turn timestamp in the evidence window for this thread.",
            },
            "evidence_first_epoch": integer_schema,
            "evidence_first_local": {
                **datetime_schema,
                "description": "Earliest evidence-window turn timestamp in local timezone.",
            },
            "evidence_last": {
                **datetime_schema,
                "description": "Latest turn timestamp in the evidence window for this thread.",
            },
            "evidence_last_epoch": integer_schema,
            "evidence_last_local": {
                **datetime_schema,
                "description": "Latest evidence-window turn timestamp in local timezone.",
            },
            "archived": boolean_schema,
            "turns_label": {
                **string_schema,
                "description": "Display-only evidence_turns/total_turns label.",
            },
            "evidence_turns": {
                **integer_schema,
                "description": "Number of turns inside the evidence window.",
            },
            "context_buffer_turns": {
                **integer_schema,
                "description": "Number of turns in the context buffer before the evidence window.",
            },
            "total_turns": {
                **integer_schema,
                "description": "Total turns read from the thread.",
            },
            "thread_id": string_schema,
            "cwd": string_schema,
            "title": string_schema,
        },
    }
    excluded_reason_counts_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["fork", "summary_helper"],
        "properties": {
            "fork": integer_schema,
            "summary_helper": integer_schema,
        },
    }
    counts_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["active", "archived"],
        "properties": {
            "active": excluded_reason_counts_schema,
            "archived": excluded_reason_counts_schema,
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "output_version",
            "generated_at",
            "generated_at_epoch",
            "since",
            "since_epoch",
            "since_local",
            "until",
            "until_epoch",
            "until_local",
            "evidence_days",
            "context_days",
            "include_archived",
            "limit",
            "ordered_by",
            "shown_count",
            "counts_are_after_limit",
            "counts_scope",
            "scanned_excluded_scope",
            "maybe_more_than_limit",
            "shown_active_count",
            "shown_archived_count",
            "scanned_excluded_total",
            "scanned_excluded_counts",
            "threads",
        ],
        "properties": {
            "schema_version": {"const": 1},
            "output_version": {"const": 1},
            "generated_at": datetime_schema,
            "generated_at_epoch": integer_schema,
            "since": datetime_schema,
            "since_epoch": integer_schema,
            "since_local": datetime_schema,
            "until": datetime_schema,
            "until_epoch": integer_schema,
            "until_local": datetime_schema,
            "evidence_days": integer_schema,
            "context_days": integer_schema,
            "include_archived": boolean_schema,
            "limit": integer_schema,
            "ordered_by": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["evidence_last_desc", "updated_desc"],
                },
                "description": "Ordering applied to the returned threads.",
            },
            "shown_count": integer_schema,
            "counts_are_after_limit": boolean_schema,
            "counts_scope": {"type": "string", "enum": ["shown_after_limit"]},
            "scanned_excluded_scope": {
                "type": "string",
                "enum": ["scanned_until_limit"],
            },
            "maybe_more_than_limit": boolean_schema,
            "shown_active_count": integer_schema,
            "shown_archived_count": integer_schema,
            "scanned_excluded_total": integer_schema,
            "scanned_excluded_counts": counts_schema,
            "threads": {"type": "array", "items": thread_schema},
        },
    }


def render_inspect(result: CollectionResult, *, pretty: bool = False) -> str:
    """渲染 inspect JSON 输出。"""

    return json_text(inspect_payload(result), pretty=pretty)


def cache_key(session: SessionDigest, model: str) -> str:
    """生成 session 摘要缓存 key。"""

    raw = json.dumps(
        {
            "model": model,
            "thread_id": session.thread_id,
            "evidence_since": session.evidence_since,
            "context_since": session.context_since,
            "window_until": session.window_until,
            "evidence_turns": session.evidence_turns,
            "item_counts": session.item_counts,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def session_summary_schema() -> dict[str, Any]:
    """返回单 session 摘要 JSON schema。"""

    return strict_json_schema(SessionSummary.model_json_schema())


def weekly_update_schema() -> dict[str, Any]:
    """返回最终周报 JSON schema。"""

    return strict_json_schema(
        {
            "type": "object",
            "properties": {
                "status_update": {"type": "string"},
                "basis": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["status_update", "basis"],
            "additionalProperties": False,
        }
    )


def strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """把 Pydantic schema 转成 Responses API 需要的 strict object schema。"""

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                props = node.get("properties")
                if isinstance(props, dict):
                    node["required"] = list(props.keys())
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    copied = json.loads(json.dumps(schema))
    visit(copied)
    return copied


def summarize_one_session(
    codex: Codex,
    session: SessionDigest,
    *,
    model: str,
    effort: ReasoningEffort,
) -> SessionSummary:
    """用指定模型生成单 session 摘要卡片。"""

    prompt = f"""请把下面这个 Codex session 抽取结果压缩成一张结构化摘要卡片。

要求：
- 使用中文。
- 只总结 evidence_since 到 window_until 之间发生的 turns。
- context_since 到 evidence_since 之间的 context_buffer 只能作为上下文，不得写成本周完成或 deliverables。
- 聚焦用户真正完成的工作，不要复述 AGENTS 或系统上下文。
- 如果 context_buffer 显示这是跨周长 session，要在 evidence 中说明“本周窗口内继续推进”。
- outcome 写成一句话，说明最终结果。
- deliverables 只写实际产出，例如代码改动、PR/MR/issue、评论、报告、排查结论、自动化。
- blockers 只写仍然阻塞或未完成的事，没有就空数组。
- evidence 放 1-5 条可核对依据，例如 final answer、路径、命令、thread 名称。
- importance 只能用 high/medium/low。

Session JSON:
{session.model_dump_json(indent=2)}
"""
    thread = codex.thread_start(model=model, sandbox=Sandbox.read_only, ephemeral=True)
    result = thread.run(
        prompt,
        effort=effort,
        output_schema=session_summary_schema(),
        sandbox=Sandbox.read_only,
    )
    return SessionSummary.model_validate_json(result.final_response)


def load_or_summarize_sessions(
    collection: CollectionResult,
    *,
    cache_dir: Path,
    model: str,
    effort: ReasoningEffort,
    refresh: bool,
) -> list[SessionSummary]:
    """对 collection 中的 session 生成带缓存的摘要卡片。"""

    cache_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[SessionSummary] = []
    with Codex() as codex:
        for index, session in enumerate(collection.sessions, start=1):
            path = cache_dir / f"{cache_key(session, model)}.json"
            if path.exists() and not refresh:
                summaries.append(
                    SessionSummary.model_validate_json(path.read_text(encoding="utf-8"))
                )
                continue
            summary = summarize_one_session(codex, session, model=model, effort=effort)
            if summary.thread_id != session.thread_id:
                summary.thread_id = session.thread_id
            write_json(path, summary)
            summaries.append(summary)
    return summaries


def draft_final_update(
    summaries: SummariesResult,
    *,
    model: str,
    effort: ReasoningEffort,
) -> dict[str, Any]:
    """用最终模型把 session 卡片聚合成状态更新。"""

    prompt = f"""请根据下面这些 Codex session 摘要卡片，起草一则简短中文状态更新。

要求：
- 输出适合直接发给团队或上级。
- 主体包含三段或三个小节：本周完成、当前进展/阻塞、下周重点。
- 合并相同主题，不要逐条罗列 thread。
- 不要夸大，只写摘要卡片能支持的内容。
- basis 列出 3-8 条主要依据主题，方便人工校对。

Session summaries:
{summaries.model_dump_json(indent=2)}
"""
    with Codex() as codex:
        thread = codex.thread_start(
            model=model, sandbox=Sandbox.read_only, ephemeral=True
        )
        result = thread.run(
            prompt,
            effort=effort,
            output_schema=weekly_update_schema(),
            sandbox=Sandbox.read_only,
        )
    return json.loads(result.final_response)


@app.command()
def collect(
    evidence_days: Annotated[int, typer.Option(help="证据窗口天数。")] = 7,
    context_days: Annotated[int, typer.Option(help="上下文窗口天数。")] = 8,
    include_archived: Annotated[bool, typer.Option(help="包含 archived。")] = True,
    limit: Annotated[int, typer.Option(help="合并排序后的 thread 上限。")] = 200,
    until: Annotated[
        str | None,
        typer.Option(help="固定窗口结束时间 ISO；无时区按 UTC。"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="JSON 输出路径；不传则输出到 stdout。"),
    ] = None,
    pretty: Annotated[bool, typer.Option(help="stdout 输出 pretty JSON。")] = False,
) -> None:
    """通过 Codex Python SDK 收集 session 摘要输入。"""

    result = collect_data(
        evidence_days=evidence_days,
        context_days=context_days,
        include_archived=include_archived,
        limit=limit,
        until=parse_datetime(until) if until else None,
    )
    if output:
        write_json(output, result)
    else:
        console.file.write(json_text(result, pretty=pretty))
        console.file.flush()


@app.command("summarize-sessions")
def summarize_sessions(
    input_path: Annotated[
        Path,
        typer.Option("--input", "-i", help="collect 生成的 JSON 文件。"),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="摘要卡片 JSON 输出路径。"),
    ] = None,
    cache_dir: Annotated[
        Path,
        typer.Option(help="session 摘要缓存目录。"),
    ] = DEFAULT_CACHE_DIR / "session-summaries",
    model: Annotated[
        str, typer.Option(help="单 session 摘要使用的快速模型。")
    ] = DEFAULT_FAST_MODEL,
    effort: Annotated[
        ReasoningEffort, typer.Option(help="单 session 摘要推理强度。")
    ] = ReasoningEffort.low,
    refresh: Annotated[bool, typer.Option(help="忽略缓存，强制重算。")] = False,
    pretty: Annotated[bool, typer.Option(help="stdout 输出 pretty JSON。")] = False,
) -> None:
    """用快速模型生成每个 session 的结构化摘要卡片。"""

    collection = read_collection(input_path)
    summaries = load_or_summarize_sessions(
        collection,
        cache_dir=cache_dir,
        model=model,
        effort=effort,
        refresh=refresh,
    )
    result = SummariesResult(
        generated_at=utc_iso(datetime.now(UTC)),
        fast_model=model,
        source_collection=collection,
        summaries=summaries,
    )
    if output:
        write_json(output, result)
    else:
        console.file.write(json_text(result, pretty=pretty))
        console.file.flush()


@app.command("draft-update")
def draft_update(
    evidence_days: Annotated[int, typer.Option(help="证据窗口天数。")] = 7,
    context_days: Annotated[int, typer.Option(help="上下文窗口天数。")] = 8,
    include_archived: Annotated[bool, typer.Option(help="包含 archived。")] = True,
    limit: Annotated[int, typer.Option(help="合并排序后的 thread 上限。")] = 200,
    until: Annotated[
        str | None,
        typer.Option(help="固定窗口结束时间 ISO；无时区按 UTC。"),
    ] = None,
    cache_dir: Annotated[Path, typer.Option(help="缓存目录。")] = DEFAULT_CACHE_DIR,
    fast_model: Annotated[
        str, typer.Option(help="单 session 摘要使用的快速模型。")
    ] = DEFAULT_FAST_MODEL,
    final_model: Annotated[
        str, typer.Option(help="最终周报聚合使用的模型。")
    ] = DEFAULT_FINAL_MODEL,
    fast_effort: Annotated[
        ReasoningEffort, typer.Option(help="快速摘要推理强度。")
    ] = ReasoningEffort.low,
    final_effort: Annotated[
        ReasoningEffort, typer.Option(help="最终聚合推理强度。")
    ] = ReasoningEffort.medium,
    refresh: Annotated[bool, typer.Option(help="忽略 session 摘要缓存。")] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="最终 JSON 输出路径。"),
    ] = None,
    pretty: Annotated[bool, typer.Option(help="stdout 输出 pretty JSON。")] = False,
) -> None:
    """收集 session、生成摘要卡片，并起草中文状态更新。"""

    collection = collect_data(
        evidence_days=evidence_days,
        context_days=context_days,
        include_archived=include_archived,
        limit=limit,
        until=parse_datetime(until) if until else None,
    )
    summaries = load_or_summarize_sessions(
        collection,
        cache_dir=cache_dir / "session-summaries",
        model=fast_model,
        effort=fast_effort,
        refresh=refresh,
    )
    summary_result = SummariesResult(
        generated_at=utc_iso(datetime.now(UTC)),
        fast_model=fast_model,
        source_collection=collection,
        summaries=summaries,
    )
    final = draft_final_update(summary_result, model=final_model, effort=final_effort)
    if output:
        write_json(output, final)
    else:
        console.file.write(json_text(final, pretty=pretty))
        console.file.flush()


@app.command()
def inspect(
    evidence_days: Annotated[int, typer.Option(help="证据窗口天数。")] = 7,
    context_days: Annotated[int, typer.Option(help="上下文窗口天数。")] = 8,
    include_archived: Annotated[bool, typer.Option(help="包含 archived。")] = True,
    limit: Annotated[int, typer.Option(help="合并排序后的 thread 上限。")] = 50,
    until: Annotated[
        str | None,
        typer.Option(help="固定窗口结束时间 ISO；无时区按 UTC。"),
    ] = None,
    schema: Annotated[
        bool,
        typer.Option("--schema", help="只输出 inspect JSON Schema，不读取 sessions。"),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="JSON 输出路径；不传则输出到 stdout。"),
    ] = None,
    pretty: Annotated[bool, typer.Option(help="stdout 输出 pretty JSON。")] = False,
) -> None:
    """以 JSON 列出将被处理的 thread，便于 Agent 确认范围。"""

    if schema:
        rendered = json_text(inspect_schema(), pretty=pretty)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered, encoding="utf-8")
            return
        console.file.write(rendered)
        console.file.flush()
        return

    result = collect_data(
        evidence_days=evidence_days,
        context_days=context_days,
        include_archived=include_archived,
        limit=limit,
        until=parse_datetime(until) if until else None,
    )
    rendered = render_inspect(result, pretty=pretty)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        return

    console.file.write(rendered)
    console.file.flush()


if __name__ == "__main__":
    app()
