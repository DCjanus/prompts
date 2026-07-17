#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pydantic>=2.13.4",
#     "rich>=15.0.0",
#     "typer>=0.27.0",
# ]
# ///

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Iterable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, ValidationError, field_validator
from rich.console import Console
from rich.table import Table
import typer

console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=True)

SourceKind = Literal["live", "archived", "custom"]
DEFAULT_FALLBACK_MODEL = "gpt-5"
LITELLM_PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
PRICING_CACHE_MAX_AGE = timedelta(days=7)
MODEL_ALIASES = {
    "gpt-5-codex": "gpt-5",
    "gpt-5.3-codex": "gpt-5.2-codex",
}
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


class Usage(BaseModel):
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_raw(cls, value: Any) -> Usage | None:
        if not isinstance(value, dict):
            return None
        input_tokens = ensure_int(value.get("input_tokens"))
        cached_input_tokens = ensure_int(
            value.get("cached_input_tokens", value.get("cache_read_input_tokens"))
        )
        output_tokens = ensure_int(value.get("output_tokens"))
        reasoning_output_tokens = ensure_int(value.get("reasoning_output_tokens"))
        total_tokens = ensure_int(value.get("total_tokens"))
        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens
        return cls(
            input_tokens=input_tokens,
            cached_input_tokens=min(cached_input_tokens, input_tokens),
            output_tokens=output_tokens,
            reasoning_output_tokens=reasoning_output_tokens,
            total_tokens=total_tokens,
        )

    def subtract(self, previous: Usage | None) -> Usage:
        if previous is None:
            return self
        return Usage(
            input_tokens=max(self.input_tokens - previous.input_tokens, 0),
            cached_input_tokens=max(
                self.cached_input_tokens - previous.cached_input_tokens, 0
            ),
            output_tokens=max(self.output_tokens - previous.output_tokens, 0),
            reasoning_output_tokens=max(
                self.reasoning_output_tokens - previous.reasoning_output_tokens, 0
            ),
            total_tokens=max(self.total_tokens - previous.total_tokens, 0),
        )

    def is_empty(self) -> bool:
        return (
            self.input_tokens == 0
            and self.cached_input_tokens == 0
            and self.output_tokens == 0
            and self.reasoning_output_tokens == 0
        )

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.output_tokens += other.output_tokens
        self.reasoning_output_tokens += other.reasoning_output_tokens
        self.total_tokens += other.total_tokens

    def to_json(self) -> dict[str, int]:
        return {field: getattr(self, field) for field in TOKEN_FIELDS}


class SessionDirectory(BaseModel):
    path: Path
    source: SourceKind

    @field_validator("path")
    @classmethod
    def expand_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()


class LoadSpec(BaseModel):
    codex_home: Path | None = Field(default=None)
    session_dirs: list[Path] = Field(default_factory=list)
    live: bool = True
    archived: bool = True

    @field_validator("codex_home")
    @classmethod
    def expand_codex_home(cls, value: Path | None) -> Path | None:
        if value is None:
            return value
        return value.expanduser().resolve()

    @field_validator("session_dirs")
    @classmethod
    def expand_session_dirs(cls, value: list[Path]) -> list[Path]:
        return [path.expanduser().resolve() for path in value]

    @field_validator("archived")
    @classmethod
    def ensure_at_least_one_source(cls, value: bool, info) -> bool:
        live = info.data.get("live", True)
        if not live and not value:
            raise ValueError("live 与 archived 不能同时关闭")
        return value


@dataclass
class UsageEvent:
    session_id: str
    timestamp: datetime
    source: SourceKind
    path: Path
    model: str
    cwd: str | None
    usage: Usage
    is_fallback_model: bool = False


@dataclass
class LoadResult:
    events: list[UsageEvent]
    scanned_files: int
    missing_dirs: list[Path]
    skipped_lines: int


class PricingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pricing:
    input_cost_per_token: float
    cached_input_cost_per_token: float
    output_cost_per_token: float

    @classmethod
    def from_raw(cls, value: Any) -> Pricing | None:
        if not isinstance(value, dict):
            return None
        input_cost = ensure_float(value.get("input_cost_per_token"))
        cached_cost = ensure_float(
            value.get("cache_read_input_token_cost", value.get("input_cost_per_token"))
        )
        output_cost = ensure_float(value.get("output_cost_per_token"))
        if input_cost <= 0 and cached_cost <= 0 and output_cost <= 0:
            return None
        return cls(
            input_cost_per_token=input_cost,
            cached_input_cost_per_token=cached_cost,
            output_cost_per_token=output_cost,
        )


class PricingSource:
    def __init__(self) -> None:
        self._dataset: dict[str, Any] | None = None
        self.source = "unloaded"
        self.cache_path = pricing_cache_path()

    def load(self) -> dict[str, Any]:
        if self._dataset is not None:
            return self._dataset

        cached = self._load_fresh_cache()
        if cached is not None:
            self._dataset = cached
            self.source = "cache"
            return cached

        fetched = self._fetch_pricing()
        self._write_cache(fetched)
        self._dataset = fetched
        self.source = "network"
        return fetched

    def get(self, model: str) -> Pricing:
        dataset = self.load()
        for candidate in pricing_candidates(model):
            pricing = Pricing.from_raw(dataset.get(candidate))
            if pricing is not None:
                return pricing
        raise PricingError(f"未找到模型价格：{model}")

    def _load_fresh_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.is_file():
            return None
        mtime = datetime.fromtimestamp(self.cache_path.stat().st_mtime, tz=timezone.utc)
        if datetime.now(timezone.utc) - mtime > PRICING_CACHE_MAX_AGE:
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _fetch_pricing(self) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(LITELLM_PRICING_URL, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise PricingError(f"拉取价格接口失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise PricingError("价格接口返回格式不是 JSON object")
        return payload

    def _write_cache(self, payload: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.cache_path.parent,
            prefix=f".{self.cache_path.name}.",
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, sort_keys=True)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.cache_path)


def ensure_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return 0


def ensure_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def pricing_cache_path() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return root / "codex_usage" / "litellm_model_prices.json"


def pricing_candidates(model: str) -> list[str]:
    candidates = [model]
    for prefix in ("openai/", "azure/", "openrouter/openai/"):
        if model.startswith(prefix):
            candidates.append(model.removeprefix(prefix))
    alias = MODEL_ALIASES.get(model)
    if alias is not None:
        candidates.append(alias)
    return list(dict.fromkeys(candidates))


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or value.strip() == "":
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def extract_non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def extract_model(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None

    info = value.get("info")
    if isinstance(info, dict):
        for candidate in (info.get("model"), info.get("model_name")):
            model = extract_non_empty_string(candidate)
            if model is not None:
                return model
        metadata = info.get("metadata")
        if isinstance(metadata, dict):
            model = extract_non_empty_string(metadata.get("model"))
            if model is not None:
                return model

    model = extract_non_empty_string(value.get("model"))
    if model is not None:
        return model

    metadata = value.get("metadata")
    if isinstance(metadata, dict):
        return extract_non_empty_string(metadata.get("model"))

    return None


def discover_directories(spec: LoadSpec) -> list[SessionDirectory]:
    if spec.session_dirs:
        return [
            SessionDirectory(path=path, source="custom") for path in spec.session_dirs
        ]

    if spec.codex_home is not None:
        codex_home = spec.codex_home
    elif os.environ.get("CODEX_HOME"):
        codex_home = Path(os.environ["CODEX_HOME"]).expanduser().resolve()
    else:
        codex_home = Path.home() / ".codex"
    dirs: list[SessionDirectory] = []
    if spec.live:
        dirs.append(SessionDirectory(path=codex_home / "sessions", source="live"))
    if spec.archived:
        dirs.append(
            SessionDirectory(path=codex_home / "archived_sessions", source="archived")
        )
    return dirs


def iter_jsonl_files(
    directories: Iterable[SessionDirectory],
) -> tuple[list[tuple[Path, SessionDirectory]], list[Path]]:
    files: list[tuple[Path, SessionDirectory]] = []
    missing: list[Path] = []
    for directory in directories:
        if not directory.path.is_dir():
            missing.append(directory.path)
            continue
        files.extend(
            (path, directory) for path in sorted(directory.path.rglob("*.jsonl"))
        )
    return files, missing


def parse_session_file(
    path: Path, directory: SessionDirectory
) -> tuple[list[UsageEvent], int]:
    session_id = path.relative_to(directory.path).with_suffix("").as_posix()
    events: list[UsageEvent] = []
    skipped_lines = 0
    previous_totals: Usage | None = None
    current_model: str | None = None
    current_model_is_fallback = False
    cwd: str | None = None

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events, 1

    for line in lines:
        if line.strip() == "":
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            skipped_lines += 1
            continue
        if not isinstance(entry, dict):
            skipped_lines += 1
            continue

        entry_type = entry.get("type")
        payload = entry.get("payload")
        if entry_type == "session_meta" and isinstance(payload, dict):
            session_id = extract_non_empty_string(payload.get("id")) or session_id
            cwd = extract_non_empty_string(payload.get("cwd")) or cwd
            continue

        if entry_type == "turn_context" and isinstance(payload, dict):
            cwd = extract_non_empty_string(payload.get("cwd")) or cwd
            model = extract_model(payload)
            if model is not None:
                current_model = model
                current_model_is_fallback = False
            continue

        if entry_type != "event_msg" or not isinstance(payload, dict):
            continue
        if payload.get("type") != "token_count":
            continue

        timestamp = parse_timestamp(entry.get("timestamp"))
        info = payload.get("info")
        if timestamp is None or not isinstance(info, dict):
            continue

        last_usage = Usage.from_raw(info.get("last_token_usage"))
        total_usage = Usage.from_raw(info.get("total_token_usage"))
        usage = last_usage
        if usage is None and total_usage is not None:
            usage = total_usage.subtract(previous_totals)
        if total_usage is not None:
            previous_totals = total_usage
        if usage is None or usage.is_empty():
            continue

        extraction_source = dict(payload)
        extraction_source["info"] = info
        extracted_model = extract_model(extraction_source)
        if extracted_model is not None:
            current_model = extracted_model
            current_model_is_fallback = False

        is_fallback_model = False
        model = extracted_model or current_model
        if model is None:
            model = DEFAULT_FALLBACK_MODEL
            current_model = model
            current_model_is_fallback = True
            is_fallback_model = True
        elif extracted_model is None and current_model_is_fallback:
            is_fallback_model = True

        events.append(
            UsageEvent(
                session_id=session_id,
                timestamp=timestamp,
                source=directory.source,
                path=path,
                model=model,
                cwd=cwd,
                usage=usage,
                is_fallback_model=is_fallback_model,
            )
        )

    return events, skipped_lines


def load_events(spec: LoadSpec) -> LoadResult:
    files, missing_dirs = iter_jsonl_files(discover_directories(spec))
    events: list[UsageEvent] = []
    skipped_lines = 0
    for path, directory in files:
        file_events, file_skipped = parse_session_file(path, directory)
        events.extend(file_events)
        skipped_lines += file_skipped
    return LoadResult(
        events=events,
        scanned_files=len(files),
        missing_dirs=missing_dirs,
        skipped_lines=skipped_lines,
    )


def parse_date(value: str | None, *, is_until: bool) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) == 8 and normalized.isdigit():
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    try:
        day = datetime.strptime(normalized, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise typer.BadParameter("日期格式应为 YYYY-MM-DD 或 YYYYMMDD") from exc
    if is_until:
        return day + timedelta(days=1)
    return day


def parse_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise typer.BadParameter(f"未知时区: {value}") from exc


def filter_events(
    events: Iterable[UsageEvent],
    *,
    since: str | None,
    until: str | None,
    target_timezone: ZoneInfo,
) -> list[UsageEvent]:
    since_dt = parse_date(since, is_until=False)
    until_dt = parse_date(until, is_until=True)
    filtered: list[UsageEvent] = []
    for event in events:
        local_timestamp = event.timestamp.astimezone(target_timezone)
        local_day = datetime(
            local_timestamp.year,
            local_timestamp.month,
            local_timestamp.day,
            tzinfo=timezone.utc,
        )
        if since_dt is not None and local_day < since_dt:
            continue
        if until_dt is not None and local_day >= until_dt:
            continue
        filtered.append(event)
    return filtered


def aggregate_usage(events: Iterable[UsageEvent]) -> Usage:
    total = Usage()
    for event in events:
        total.add(event.usage)
    return total


def calculate_cost(usage: Usage, pricing: Pricing) -> float:
    cached_tokens = min(usage.cached_input_tokens, usage.input_tokens)
    non_cached_tokens = max(usage.input_tokens - cached_tokens, 0)
    return (
        non_cached_tokens * pricing.input_cost_per_token
        + cached_tokens * pricing.cached_input_cost_per_token
        + usage.output_tokens * pricing.output_cost_per_token
    )


def calculate_events_cost(
    events: Iterable[UsageEvent], pricing_source: PricingSource
) -> float:
    total = 0.0
    for event in events:
        total += calculate_cost(event.usage, pricing_source.get(event.model))
    return total


def format_number(value: int) -> str:
    return f"{value:,}"


def make_table(title: str) -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("group", style="cyan", no_wrap=True)
    table.add_column("sessions", justify="right")
    table.add_column("input", justify="right")
    table.add_column("cached", justify="right")
    table.add_column("output", justify="right")
    table.add_column("reasoning", justify="right")
    table.add_column("total", justify="right", style="green")
    table.add_column("cost", justify="right", style="magenta")
    return table


def add_usage_row(
    table: Table, group: str, session_count: int, usage: Usage, cost_usd: float
) -> None:
    table.add_row(
        group,
        format_number(session_count),
        format_number(usage.input_tokens),
        format_number(usage.cached_input_tokens),
        format_number(usage.output_tokens),
        format_number(usage.reasoning_output_tokens),
        format_number(usage.total_tokens),
        f"${cost_usd:,.2f}",
    )


def render_grouped_report(
    rows: list[tuple[str, set[str], Usage, float]],
    title: str,
    *,
    json_output: bool,
    pricing_source: PricingSource,
) -> None:
    totals = Usage()
    total_cost = 0.0
    for _, _, usage, cost_usd in rows:
        totals.add(usage)
        total_cost += cost_usd

    if json_output:
        console.print_json(
            data={
                "rows": [
                    {
                        "group": group,
                        "session_count": len(session_ids),
                        **usage.to_json(),
                        "cost_usd": cost_usd,
                    }
                    for group, session_ids, usage, cost_usd in rows
                ],
                "totals": totals.to_json(),
                "cost_usd": total_cost,
                "pricing_source": pricing_source.source,
                "pricing_cache": str(pricing_source.cache_path),
            }
        )
        return

    table = make_table(title)
    for group, session_ids, usage, cost_usd in rows:
        add_usage_row(table, group, len(session_ids), usage, cost_usd)
    table.add_section()
    all_sessions = (
        set().union(*(session_ids for _, session_ids, _, _ in rows)) if rows else set()
    )
    add_usage_row(table, "TOTAL", len(all_sessions), totals, total_cost)
    console.print(table)
    console.print(
        f"[dim]pricing source: {pricing_source.source}; cache: {pricing_source.cache_path}[/dim]"
    )


def build_load_spec(
    codex_home: Path | None,
    session_dir: list[Path],
    live_only: bool,
    archived_only: bool,
) -> LoadSpec:
    try:
        return LoadSpec(
            codex_home=codex_home,
            session_dirs=session_dir,
            live=not archived_only,
            archived=not live_only,
        )
    except ValidationError as exc:
        for err in exc.errors():
            console.print(f"[red]{err['msg']}[/red]")
        raise typer.Exit(code=1)


def load_filtered_events(
    *,
    codex_home: Path | None,
    session_dir: list[Path],
    live_only: bool,
    archived_only: bool,
    since: str | None,
    until: str | None,
    timezone_name: str,
    json_output: bool,
) -> tuple[list[UsageEvent], LoadResult, ZoneInfo]:
    target_timezone = parse_timezone(timezone_name)
    spec = build_load_spec(codex_home, session_dir, live_only, archived_only)
    result = load_events(spec)
    events = filter_events(
        result.events, since=since, until=until, target_timezone=target_timezone
    )
    if not json_output:
        for path in result.missing_dirs:
            console.print(f"[yellow]目录不存在，已跳过：{path}[/yellow]")
    return events, result, target_timezone


CommonSince = Annotated[
    str | None,
    typer.Option("--since", "-s", help="起始日期，格式 YYYY-MM-DD 或 YYYYMMDD"),
]
CommonUntil = Annotated[
    str | None,
    typer.Option(
        "--until", "-u", help="结束日期（包含当天），格式 YYYY-MM-DD 或 YYYYMMDD"
    ),
]
CommonTimezone = Annotated[
    str,
    typer.Option("--timezone", "-z", help="按日期分组时使用的 IANA 时区"),
]
CommonCodexHome = Annotated[
    Path | None,
    typer.Option("--codex-home", help="Codex home，默认读取 CODEX_HOME 或 ~/.codex"),
]
CommonSessionDir = Annotated[
    list[Path],
    typer.Option("--session-dir", help="直接扫描指定 JSONL 目录，可重复传入"),
]
CommonLiveOnly = Annotated[
    bool,
    typer.Option("--live-only", help="只统计 ~/.codex/sessions"),
]
CommonArchivedOnly = Annotated[
    bool,
    typer.Option("--archived-only", help="只统计 ~/.codex/archived_sessions"),
]
CommonJson = Annotated[bool, typer.Option("--json", "-j", help="输出 JSON")]


@app.command(help="按天统计 Codex token 用量。")
def daily(
    since: CommonSince = None,
    until: CommonUntil = None,
    timezone_name: CommonTimezone = "Asia/Shanghai",
    codex_home: CommonCodexHome = None,
    session_dir: CommonSessionDir = [],
    live_only: CommonLiveOnly = False,
    archived_only: CommonArchivedOnly = False,
    json_output: CommonJson = False,
) -> None:
    events, _, target_timezone = load_filtered_events(
        codex_home=codex_home,
        session_dir=session_dir,
        live_only=live_only,
        archived_only=archived_only,
        since=since,
        until=until,
        timezone_name=timezone_name,
        json_output=json_output,
    )
    pricing_source = PricingSource()
    grouped_events: dict[str, list[UsageEvent]] = defaultdict(list)
    grouped: dict[str, tuple[set[str], Usage]] = defaultdict(lambda: (set(), Usage()))
    for event in events:
        key = event.timestamp.astimezone(target_timezone).strftime("%Y-%m-%d")
        grouped_events[key].append(event)
        session_ids, usage = grouped[key]
        session_ids.add(event.session_id)
        usage.add(event.usage)
    try:
        rows = [
            (
                key,
                *grouped[key],
                calculate_events_cost(grouped_events[key], pricing_source),
            )
            for key in sorted(grouped)
        ]
    except PricingError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    render_grouped_report(
        rows,
        "Codex usage by day",
        json_output=json_output,
        pricing_source=pricing_source,
    )


@app.command(help="按月统计 Codex token 用量。")
def monthly(
    since: CommonSince = None,
    until: CommonUntil = None,
    timezone_name: CommonTimezone = "Asia/Shanghai",
    codex_home: CommonCodexHome = None,
    session_dir: CommonSessionDir = [],
    live_only: CommonLiveOnly = False,
    archived_only: CommonArchivedOnly = False,
    json_output: CommonJson = False,
) -> None:
    events, _, target_timezone = load_filtered_events(
        codex_home=codex_home,
        session_dir=session_dir,
        live_only=live_only,
        archived_only=archived_only,
        since=since,
        until=until,
        timezone_name=timezone_name,
        json_output=json_output,
    )
    pricing_source = PricingSource()
    grouped_events: dict[str, list[UsageEvent]] = defaultdict(list)
    grouped: dict[str, tuple[set[str], Usage]] = defaultdict(lambda: (set(), Usage()))
    for event in events:
        key = event.timestamp.astimezone(target_timezone).strftime("%Y-%m")
        grouped_events[key].append(event)
        session_ids, usage = grouped[key]
        session_ids.add(event.session_id)
        usage.add(event.usage)
    try:
        rows = [
            (
                key,
                *grouped[key],
                calculate_events_cost(grouped_events[key], pricing_source),
            )
            for key in sorted(grouped)
        ]
    except PricingError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    render_grouped_report(
        rows,
        "Codex usage by month",
        json_output=json_output,
        pricing_source=pricing_source,
    )


@app.command(help="按 session 统计 Codex token 用量。")
def session(
    since: CommonSince = None,
    until: CommonUntil = None,
    timezone_name: CommonTimezone = "Asia/Shanghai",
    codex_home: CommonCodexHome = None,
    session_dir: CommonSessionDir = [],
    live_only: CommonLiveOnly = False,
    archived_only: CommonArchivedOnly = False,
    json_output: CommonJson = False,
) -> None:
    events, _, _ = load_filtered_events(
        codex_home=codex_home,
        session_dir=session_dir,
        live_only=live_only,
        archived_only=archived_only,
        since=since,
        until=until,
        timezone_name=timezone_name,
        json_output=json_output,
    )
    pricing_source = PricingSource()
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        record = grouped.setdefault(
            event.session_id,
            {
                "source": event.source,
                "cwd": event.cwd,
                "models": set(),
                "usage": Usage(),
                "first_seen": event.timestamp,
                "last_seen": event.timestamp,
                "path": str(event.path),
                "events": [],
            },
        )
        record["events"].append(event)
        record["models"].add(event.model)
        record["usage"].add(event.usage)
        record["first_seen"] = min(record["first_seen"], event.timestamp)
        record["last_seen"] = max(record["last_seen"], event.timestamp)
        record["cwd"] = record["cwd"] or event.cwd

    rows = sorted(grouped.items(), key=lambda item: item[1]["last_seen"], reverse=True)
    totals = Usage()
    total_cost = 0.0
    try:
        for _, record in rows:
            totals.add(record["usage"])
            record["cost_usd"] = calculate_events_cost(record["events"], pricing_source)
            total_cost += record["cost_usd"]
    except PricingError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    if json_output:
        console.print_json(
            data={
                "sessions": [
                    {
                        "session_id": session_id,
                        "source": record["source"],
                        "cwd": record["cwd"],
                        "models": sorted(record["models"]),
                        "first_seen": record["first_seen"].isoformat(),
                        "last_seen": record["last_seen"].isoformat(),
                        "path": record["path"],
                        **record["usage"].to_json(),
                        "cost_usd": record["cost_usd"],
                    }
                    for session_id, record in rows
                ],
                "totals": totals.to_json(),
                "cost_usd": total_cost,
                "pricing_source": pricing_source.source,
                "pricing_cache": str(pricing_source.cache_path),
            }
        )
        return

    table = Table(title="Codex usage by session", show_lines=False)
    table.add_column("last", no_wrap=True, style="cyan")
    table.add_column("source", no_wrap=True)
    table.add_column("session", overflow="fold")
    table.add_column("models", overflow="fold")
    table.add_column("total", justify="right", style="green")
    table.add_column("cost", justify="right", style="magenta")
    table.add_column("cwd", overflow="fold")
    for session_id, record in rows:
        table.add_row(
            record["last_seen"].astimezone().strftime("%Y-%m-%d %H:%M"),
            record["source"],
            session_id,
            ", ".join(sorted(record["models"])),
            format_number(record["usage"].total_tokens),
            f"${record['cost_usd']:,.2f}",
            record["cwd"] or "-",
        )
    table.add_section()
    table.add_row(
        "",
        "",
        "TOTAL",
        "",
        format_number(totals.total_tokens),
        f"${total_cost:,.2f}",
        "",
    )
    console.print(table)
    console.print(
        f"[dim]pricing source: {pricing_source.source}; cache: {pricing_source.cache_path}[/dim]"
    )


@app.command(help="显示扫描范围和可解析事件数量。")
def doctor(
    codex_home: CommonCodexHome = None,
    session_dir: CommonSessionDir = [],
    live_only: CommonLiveOnly = False,
    archived_only: CommonArchivedOnly = False,
    json_output: CommonJson = False,
) -> None:
    spec = build_load_spec(codex_home, session_dir, live_only, archived_only)
    result = load_events(spec)
    source_counts: dict[str, int] = defaultdict(int)
    for event in result.events:
        source_counts[event.source] += 1

    payload = {
        "scanned_files": result.scanned_files,
        "event_count": len(result.events),
        "missing_dirs": [str(path) for path in result.missing_dirs],
        "skipped_lines": result.skipped_lines,
        "event_count_by_source": dict(sorted(source_counts.items())),
    }
    if json_output:
        console.print_json(data=payload)
        return

    console.print(f"scanned files: [cyan]{payload['scanned_files']}[/cyan]")
    console.print(f"token events: [cyan]{payload['event_count']}[/cyan]")
    console.print(f"skipped lines: [cyan]{payload['skipped_lines']}[/cyan]")
    for source, count in payload["event_count_by_source"].items():
        console.print(f"{source}: [cyan]{count}[/cyan]")
    for path in result.missing_dirs:
        console.print(f"[yellow]missing: {path}[/yellow]")


if __name__ == "__main__":
    app()
