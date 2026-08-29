#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "duckdb>=1.5.5",
#     "kittytgp>=0.0.2",
#     "resvg-py>=0.5.0",
#     "rich>=15.0.0",
#     "typer>=0.27.2",
# ]
# ///

"""展示 ChatGPT Codex 额度、本地 Token 用量与 API 等价成本。"""

from __future__ import annotations

import json
import mmap
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from html import escape
from math import ceil
from pathlib import Path
from typing import Annotated, Any, TextIO

import duckdb
import typer
from kittytgp import render_png
from resvg_py import svg_to_bytes
from rich.console import Console
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

APP_NAME = "chatgpt-usage"
APP_VERSION = "0.2.0"
SVG_WIDTH = 1440
IMAGE_SCALE = 2
DEFAULT_IMAGE_WIDTH_RATIO = 1.0
DEFAULT_HISTORY_DAYS = 7
USAGE_EVENT_BATCH_SIZE = 2_048
USAGE_SCAN_WORKERS = 4
USAGE_CACHE_SCHEMA_VERSION = 6
PRICING_UPDATED_AT = "2026-08-26"
MODELS_DEV_URL = "https://models.dev/api.json"
PRICING_CACHE_VERSION = 1
PRICING_CACHE_TTL = timedelta(hours=24)
PRICING_FETCH_TIMEOUT = 5.0
THREAD_ID_PATTERN = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$",
    re.IGNORECASE,
)
TIMESTAMP_PATTERN = re.compile(rb'"timestamp"\s*:\s*"([^"]+)"')
ROLLOUT_DATE_PATTERN = re.compile(r"rollout-(\d{4}-\d{2}-\d{2})T")
console = Console()
error_console = Console(stderr=True)
app = typer.Typer(add_completion=False, no_args_is_help=False)


class UsageError(RuntimeError):
    """表示无法读取或解析额度信息。"""


@dataclass(frozen=True)
class UsageWindow:
    """描述一个滚动额度窗口。"""

    used_percent: float
    duration_minutes: int | None
    resets_at: int | None


@dataclass(frozen=True)
class LimitBucket:
    """描述服务端返回的一个独立额度桶。"""

    limit_id: str
    name: str | None
    plan_type: str | None
    windows: tuple[UsageWindow, ...]


@dataclass(frozen=True)
class WindowProgress:
    """记录额度与时间的可比较剩余进度。"""

    quota_remaining_percent: float
    time_remaining_percent: float | None
    pace_delta: float | None
    remaining_seconds: float | None


@dataclass(frozen=True)
class DailyTokenUsage:
    """记录一天的本地 Codex Token 用量。"""

    day: date
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    models: tuple[ModelTokenUsage, ...] = ()

    @property
    def cache_hit_percent(self) -> float | None:
        """返回模型输入缓存命中率。"""
        if self.input_tokens <= 0:
            return None
        return self.cached_input_tokens / self.input_tokens * 100

    @property
    def estimated_cost_usd(self) -> float:
        """返回已知模型价格对应的 API 等价成本。"""
        return sum(model.estimated_cost_usd or 0.0 for model in self.models)

    @property
    def unpriced_tokens(self) -> int:
        """返回因模型价格未知而未能估价的 Token 数。"""
        if not self.models:
            return self.total_tokens
        return sum(
            model.total_tokens
            for model in self.models
            if model.estimated_cost_usd is None
        )


@dataclass(frozen=True)
class ModelTokenUsage:
    """记录一天内单个模型的 Token 用量与 API 等价成本。"""

    model: str
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None
    fast_tokens: int = 0
    non_fast_tokens: int = 0


@dataclass(frozen=True)
class ModelPricing:
    """描述模型每百万 Token 的标准 API 美元价格。"""

    input_per_million: float
    cached_input_per_million: float | None
    output_per_million: float
    cache_write_per_million: float | None = None
    long_context_threshold: int | None = None
    long_input_per_million: float | None = None
    long_cached_input_per_million: float | None = None
    long_output_per_million: float | None = None
    long_cache_write_per_million: float | None = None


@dataclass(frozen=True)
class PricingMetadata:
    """描述本次估价所用价格目录的来源。"""

    source: str
    fetched_at: datetime | None
    stale: bool
    error: str | None = None


@dataclass(frozen=True)
class PricingCatalog:
    """保存可用于估价的模型价格和来源元数据。"""

    prices: dict[str, ModelPricing]
    metadata: PricingMetadata


@dataclass(frozen=True)
class ScanStats:
    """记录本地 Thread 增量索引情况。"""

    total_files: int
    cache_hits: int
    full_scans: int
    incremental_scans: int


@dataclass(frozen=True)
class UsageHistory:
    """记录按天汇总的 Token 用量与索引状态。"""

    days: tuple[DailyTokenUsage, ...]
    scan: ScanStats
    pricing: PricingMetadata | None = None

    @property
    def total_tokens(self) -> int:
        """返回当前时间范围内的 Token 总量。"""
        return sum(day.total_tokens for day in self.days)

    @property
    def estimated_cost_usd(self) -> float:
        """返回当前时间范围内已知模型的 API 等价成本。"""
        return sum(day.estimated_cost_usd for day in self.days)

    @property
    def unpriced_tokens(self) -> int:
        """返回当前时间范围内未能估价的 Token 数。"""
        return sum(day.unpriced_tokens for day in self.days)


@dataclass(frozen=True)
class _RolloutState:
    """记录单个 rollout 的增量解析位点。"""

    path: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    parsed_bytes: int
    last_total: tuple[int, int, int, int, int, int] | None
    last_model: str | None
    last_service_tier: str


@dataclass(frozen=True)
class _UsageEvent:
    """记录一条已归属模型的 Token 增量。"""

    thread_id: str
    event_key: str
    day: date
    model: str
    service_tier: str
    usage: tuple[int, int, int, int, int, int]


@dataclass(frozen=True)
class _RolloutScanJob:
    """描述一个可独立并行处理的 rollout 扫描任务。"""

    path: Path
    thread_id: str
    stat: os.stat_result
    state: _RolloutState | None
    can_append: bool


def _jsonrpc_input() -> str:
    """构造 Codex app-server 初始化与只读查询请求。"""
    messages = [
        {
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {
                    "name": APP_NAME,
                    "title": "ChatGPT Usage",
                    "version": APP_VERSION,
                },
                "capabilities": {"experimentalApi": True},
            },
        },
        {"method": "initialized"},
        {"id": 2, "method": "account/rateLimits/read"},
    ]
    return (
        "\n".join(json.dumps(message, separators=(",", ":")) for message in messages)
        + "\n"
    )


def _write_message(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    """向 app-server 写入一条 JSON-RPC 消息。"""
    if process.stdin is None:
        raise UsageError("Codex app-server 的标准输入不可用")
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read_response(
    lines: queue.Queue[str], request_id: int, deadline: float
) -> dict[str, Any]:
    """忽略通知并等待指定请求的响应。"""
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty as error:
            raise UsageError("等待 Codex app-server 响应超时") from error
        if not line:
            raise UsageError("Codex app-server 在返回响应前退出")
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            return message
    raise UsageError("等待 Codex app-server 响应超时")


def fetch_rate_limits(codex_bin: Path, timeout: float) -> dict[str, Any]:
    """通过 Codex app-server 复用当前登录态读取额度。"""
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file:
        return _fetch_rate_limits_process(codex_bin, timeout, stderr_file)


def _fetch_rate_limits_process(
    codex_bin: Path, timeout: float, stderr_file: TextIO
) -> dict[str, Any]:
    """管理一次 Codex app-server 子进程查询。"""
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            [str(codex_bin), "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            bufsize=1,
        )
    except OSError as error:
        raise UsageError(f"无法启动 Codex CLI：{error}") from error

    lines: queue.Queue[str] = queue.Queue()

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put("")

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    try:
        messages = [json.loads(line) for line in _jsonrpc_input().splitlines()]
        _write_message(process, messages[0])
        initialize = _read_response(lines, 1, deadline)
        if "error" in initialize:
            raise UsageError(f"Codex app-server 初始化失败：{initialize['error']}")

        _write_message(process, messages[1])
        _write_message(process, messages[2])
        response = _read_response(lines, 2, deadline)
        if "error" in response:
            error = response["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise UsageError(f"读取额度失败：{message}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise UsageError("Codex app-server 返回了无法识别的额度响应")
        return result
    except UsageError as error:
        stderr_file.flush()
        stderr_file.seek(0)
        detail = stderr_file.read().strip()
        if detail and str(error).endswith("响应前退出"):
            raise UsageError(f"{error}：{detail}") from error
        raise
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        reader.join(timeout=1)
        if process.stdout is not None:
            process.stdout.close()


def _parse_window(value: Any) -> UsageWindow | None:
    """解析单个服务端额度窗口。"""
    if not isinstance(value, dict):
        return None
    used_percent = value.get("usedPercent")
    if not isinstance(used_percent, (int, float)):
        return None
    duration = value.get("windowDurationMins")
    resets_at = value.get("resetsAt")
    return UsageWindow(
        used_percent=float(used_percent),
        duration_minutes=duration if isinstance(duration, int) else None,
        resets_at=resets_at if isinstance(resets_at, int) else None,
    )


def parse_rate_limits(result: dict[str, Any]) -> list[LimitBucket]:
    """把 app-server 响应整理为不重复的额度桶。"""
    raw_by_id = result.get("rateLimitsByLimitId")
    if isinstance(raw_by_id, dict) and raw_by_id:
        raw_buckets = list(raw_by_id.items())
    else:
        raw_buckets = [("codex", result.get("rateLimits"))]

    buckets: list[LimitBucket] = []
    for fallback_id, value in raw_buckets:
        if not isinstance(value, dict):
            continue
        windows = tuple(
            window
            for raw_window in (value.get("primary"), value.get("secondary"))
            if (window := _parse_window(raw_window)) is not None
        )
        limit_id = value.get("limitId")
        buckets.append(
            LimitBucket(
                limit_id=limit_id if isinstance(limit_id, str) else str(fallback_id),
                name=value.get("limitName")
                if isinstance(value.get("limitName"), str)
                else None,
                plan_type=value.get("planType")
                if isinstance(value.get("planType"), str)
                else None,
                windows=windows,
            )
        )

    buckets.sort(
        key=lambda bucket: (bucket.limit_id != "codex", bucket.name or bucket.limit_id)
    )
    if not buckets:
        raise UsageError("额度响应中没有可展示的额度桶")
    return buckets


def default_codex_home() -> Path:
    """返回当前 Codex 本地数据目录。"""
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def default_usage_cache_path() -> Path:
    """返回用量增量索引的默认 DuckDB 路径。"""
    if configured := os.environ.get("XDG_CACHE_HOME"):
        root = Path(configured).expanduser()
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    elif os.name == "nt" and (configured := os.environ.get("LOCALAPPDATA")):
        root = Path(configured).expanduser()
    else:
        root = Path.home() / ".cache"
    return root / APP_NAME / "usage.duckdb"


def default_pricing_cache_path() -> Path:
    """返回 models.dev 价格目录缓存的默认路径。"""
    return default_usage_cache_path().with_name(
        f"models-dev-v{PRICING_CACHE_VERSION}.json"
    )


def _visible_buckets(buckets: list[LimitBucket], *, verbose: bool) -> list[LimitBucket]:
    """默认隐藏低价值的 Spark 额度桶。"""
    if verbose:
        return buckets
    return [
        bucket
        for bucket in buckets
        if "spark" not in f"{bucket.limit_id} {bucket.name or ''}".lower()
    ]


def _usage_tuple(value: Any) -> tuple[int, int, int, int, int, int] | None:
    """把 Token usage 对象解析为固定顺序的整数元组。"""
    if not isinstance(value, dict):
        return None
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )
    values = tuple(value.get(field, 0) for field in fields)
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in values):
        return None
    return tuple(max(0, item) for item in values)


# 当前标准 API 单价快照。GPT-5.6 采用 OpenAI 2026-08-25 公布价格，其余
# Codex 模型沿用 CodexBar 的内置映射；缓存写入价缺失时按普通输入计费。
MODEL_PRICING: dict[str, ModelPricing] = {
    "gpt-5": ModelPricing(1.25, 0.125, 10.0),
    "gpt-5-codex": ModelPricing(1.25, 0.125, 10.0),
    "gpt-5-mini": ModelPricing(0.25, 0.025, 2.0),
    "gpt-5-nano": ModelPricing(0.05, 0.005, 0.4),
    "gpt-5-pro": ModelPricing(15.0, None, 120.0),
    "gpt-5.1": ModelPricing(1.25, 0.125, 10.0),
    "gpt-5.1-codex": ModelPricing(1.25, 0.125, 10.0),
    "gpt-5.1-codex-max": ModelPricing(1.25, 0.125, 10.0),
    "gpt-5.1-codex-mini": ModelPricing(0.25, 0.025, 2.0),
    "gpt-5.2": ModelPricing(1.75, 0.175, 14.0),
    "gpt-5.2-codex": ModelPricing(1.75, 0.175, 14.0),
    "gpt-5.2-pro": ModelPricing(21.0, None, 168.0),
    "gpt-5.3-codex": ModelPricing(1.75, 0.175, 14.0),
    "gpt-5.3-codex-spark": ModelPricing(0.0, 0.0, 0.0),
    "gpt-5.4": ModelPricing(
        2.5,
        0.25,
        15.0,
        long_context_threshold=272_000,
        long_input_per_million=5.0,
        long_cached_input_per_million=0.5,
        long_output_per_million=22.5,
    ),
    "gpt-5.4-mini": ModelPricing(0.75, 0.075, 4.5),
    "gpt-5.4-nano": ModelPricing(0.2, 0.02, 1.25),
    "gpt-5.4-pro": ModelPricing(30.0, None, 180.0),
    "gpt-5.5": ModelPricing(
        5.0,
        0.5,
        30.0,
        long_context_threshold=272_000,
        long_input_per_million=10.0,
        long_cached_input_per_million=1.0,
        long_output_per_million=45.0,
    ),
    "gpt-5.5-pro": ModelPricing(30.0, None, 180.0),
    "gpt-5.6-sol": ModelPricing(
        4.0,
        0.4,
        20.0,
        cache_write_per_million=5.0,
        long_context_threshold=272_000,
        long_input_per_million=8.0,
        long_cached_input_per_million=0.8,
        long_output_per_million=30.0,
        long_cache_write_per_million=10.0,
    ),
    "gpt-5.6-terra": ModelPricing(
        2.0,
        0.2,
        12.0,
        cache_write_per_million=2.5,
        long_context_threshold=272_000,
        long_input_per_million=4.0,
        long_cached_input_per_million=0.4,
        long_output_per_million=18.0,
        long_cache_write_per_million=5.0,
    ),
    "gpt-5.6-luna": ModelPricing(
        0.2,
        0.02,
        1.2,
        cache_write_per_million=0.25,
        long_context_threshold=272_000,
        long_input_per_million=0.4,
        long_cached_input_per_million=0.04,
        long_output_per_million=1.8,
        long_cache_write_per_million=0.5,
    ),
}

FAST_PRICE_MULTIPLIERS = {"gpt-5.6-sol": 2.0}


def _price_number(value: Any) -> float | None:
    """解析非负的每百万 Token 价格。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        return None
    return float(value)


def _models_dev_providers(payload: Any) -> dict[str, Any]:
    """兼容 models.dev 顶层 provider 映射与 providers 包装格式。"""
    if not isinstance(payload, dict):
        return {}
    providers = payload.get("providers", payload)
    return providers if isinstance(providers, dict) else {}


def _provider_has_pricing(provider: Any) -> bool:
    """判断 provider 是否至少包含一个完整输入/输出价格。"""
    models = provider.get("models") if isinstance(provider, dict) else None
    if not isinstance(models, dict):
        return False
    return any(
        isinstance(model, dict)
        and isinstance(model.get("cost"), dict)
        and _price_number(model["cost"].get("input")) is not None
        and _price_number(model["cost"].get("output")) is not None
        for model in models.values()
    )


def _models_dev_prices(payload: bytes) -> dict[str, ModelPricing]:
    """校验并解析 models.dev 的 OpenAI 模型价格。"""
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UsageError(f"models.dev 返回了无效 JSON：{error}") from error
    providers = _models_dev_providers(decoded)
    if not all(
        _provider_has_pricing(providers.get(provider_id))
        for provider_id in ("anthropic", "openai")
    ):
        raise UsageError("models.dev 价格目录不完整")
    openai = providers["openai"]
    prices: dict[str, ModelPricing] = {}
    for map_key, model in openai["models"].items():
        if not isinstance(model, dict) or not isinstance(model.get("cost"), dict):
            continue
        cost = model["cost"]
        input_rate = _price_number(cost.get("input"))
        output_rate = _price_number(cost.get("output"))
        if input_rate is None or output_rate is None:
            continue
        raw_model_id = model.get("id", map_key)
        if not isinstance(raw_model_id, str) or not raw_model_id.strip():
            continue
        model_id = raw_model_id.strip().removeprefix("openai/")
        base = MODEL_PRICING.get(_normalize_model(model_id))
        long_cost = cost.get("context_over_200k")
        has_long_cost = isinstance(long_cost, dict)
        cached_rate = _price_number(cost.get("cache_read"))
        cache_write_rate = _price_number(cost.get("cache_write"))
        prices[model_id] = ModelPricing(
            input_per_million=input_rate,
            cached_input_per_million=(
                cached_rate
                if cached_rate is not None
                else (base.cached_input_per_million if base else None)
            ),
            output_per_million=output_rate,
            cache_write_per_million=(
                cache_write_rate
                if cache_write_rate is not None
                else (base.cache_write_per_million if base else None)
            ),
            long_context_threshold=(
                base.long_context_threshold
                if base and base.long_context_threshold is not None
                else (200_000 if has_long_cost else None)
            ),
            long_input_per_million=(
                _price_number(long_cost.get("input")) if has_long_cost else None
            ),
            long_cached_input_per_million=(
                _price_number(long_cost.get("cache_read")) if has_long_cost else None
            ),
            long_output_per_million=(
                _price_number(long_cost.get("output")) if has_long_cost else None
            ),
            long_cache_write_per_million=(
                _price_number(long_cost.get("cache_write")) if has_long_cost else None
            ),
        )
    if not prices:
        raise UsageError("models.dev 的 OpenAI 价格目录为空")
    return prices


def _pricing_cache_load(
    cache_path: Path,
) -> tuple[datetime, dict[str, ModelPricing]] | None:
    """读取并校验本地价格目录缓存。"""
    try:
        artifact = json.loads(cache_path.read_text(encoding="utf-8"))
        if artifact.get("version") != PRICING_CACHE_VERSION:
            return None
        fetched_at = datetime.fromisoformat(artifact["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        raw_prices = artifact["prices"]
        if not isinstance(raw_prices, dict):
            return None
        prices = {
            model: ModelPricing(**value)
            for model, value in raw_prices.items()
            if isinstance(model, str) and isinstance(value, dict)
        }
        return (fetched_at, prices) if prices else None
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _pricing_cache_save(
    cache_path: Path, *, fetched_at: datetime, prices: dict[str, ModelPricing]
) -> None:
    """原子写入价格目录缓存。"""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "version": PRICING_CACHE_VERSION,
        "fetched_at": fetched_at.isoformat(),
        "prices": {model: asdict(price) for model, price in prices.items()},
    }
    descriptor, temporary_name = tempfile.mkstemp(
        dir=cache_path.parent, prefix=f".{cache_path.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_text(
            json.dumps(artifact, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary_path, cache_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _fetch_models_dev(url: str, timeout: float) -> bytes:
    """通过 HTTPS 获取 models.dev 价格目录。"""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _pricing_catalog(
    remote_prices: dict[str, ModelPricing], metadata: PricingMetadata
) -> PricingCatalog:
    """让在线目录优先，并保留内置价格作为逐模型回退。"""
    return PricingCatalog(prices={**MODEL_PRICING, **remote_prices}, metadata=metadata)


def load_pricing_catalog(
    cache_path: Path,
    *,
    now: datetime,
    timeout: float = PRICING_FETCH_TIMEOUT,
    fetcher: Callable[[str, float], bytes] = _fetch_models_dev,
) -> PricingCatalog:
    """加载价格目录：新鲜缓存优先，过期时刷新，失败则安全回退。"""
    aware_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    cached = _pricing_cache_load(cache_path)
    if cached is not None:
        fetched_at, cached_prices = cached
        if aware_now - fetched_at <= PRICING_CACHE_TTL:
            return _pricing_catalog(
                cached_prices,
                PricingMetadata("models.dev_cache", fetched_at, False),
            )
    try:
        refreshed = _models_dev_prices(fetcher(MODELS_DEV_URL, timeout))
        if cached is not None:
            refreshed = {**cached[1], **refreshed}
        _pricing_cache_save(cache_path, fetched_at=aware_now, prices=refreshed)
        return _pricing_catalog(
            refreshed, PricingMetadata("models.dev", aware_now, False)
        )
    except (OSError, RuntimeError, TypeError, ValueError, UsageError) as error:
        message = str(error) or error.__class__.__name__
        if cached is not None:
            return _pricing_catalog(
                cached[1],
                PricingMetadata("models.dev_cache", cached[0], True, message),
            )
        return PricingCatalog(
            prices=dict(MODEL_PRICING),
            metadata=PricingMetadata(
                "built_in",
                datetime.fromisoformat(PRICING_UPDATED_AT).replace(tzinfo=UTC),
                True,
                message,
            ),
        )


def _normalize_model(raw: str | None) -> str:
    """把 Codex 记录中的模型别名归一化到价目表键。"""
    if not raw:
        return "unknown"
    model = raw.strip()
    if model.startswith("openai/"):
        model = model.removeprefix("openai/")
    if model == "gpt-5.6":
        return "gpt-5.6-sol"
    if model in MODEL_PRICING:
        return model
    base = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model)
    return base if base in MODEL_PRICING else model


def _normalize_service_tier(raw: str | None) -> str:
    """把 Codex 的 service tier 归一化为稳定的用量维度。"""
    if not raw:
        return "standard"
    tier = raw.strip().lower()
    if tier in {"fast", "priority"}:
        return "fast"
    if tier in {"default", "auto", "standard"}:
        return "standard"
    return tier


def estimate_api_cost(
    model: str,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    cache_write_input_tokens: int,
    output_tokens: int,
    service_tier: str = "standard",
    prices: dict[str, ModelPricing] | None = None,
) -> float | None:
    """按当前 API 单价估算单次请求的美元成本。"""
    catalog = MODEL_PRICING if prices is None else prices
    normalized = _normalize_model(model)
    candidates = [normalized]
    if normalized.startswith("openai/"):
        candidates.append(normalized.removeprefix("openai/"))
    dated_base = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", normalized)
    if dated_base not in candidates:
        candidates.append(dated_base)
    pricing = next((catalog[key] for key in candidates if key in catalog), None)
    if pricing is None:
        return None
    total_input = max(0, input_tokens)
    cached = min(max(0, cached_input_tokens), total_input)
    remaining = total_input - cached
    cache_write = min(max(0, cache_write_input_tokens), remaining)
    uncached = remaining - cache_write
    long_context = (
        pricing.long_context_threshold is not None
        and total_input > pricing.long_context_threshold
    )
    if long_context:
        input_rate = (
            pricing.long_input_per_million
            if pricing.long_input_per_million is not None
            else pricing.input_per_million
        )
        cached_rate = (
            pricing.long_cached_input_per_million
            if pricing.long_cached_input_per_million is not None
            else (
                pricing.cached_input_per_million
                if pricing.cached_input_per_million is not None
                else input_rate
            )
        )
        cache_write_rate = (
            pricing.long_cache_write_per_million
            if pricing.long_cache_write_per_million is not None
            else (
                pricing.cache_write_per_million
                if pricing.cache_write_per_million is not None
                else input_rate
            )
        )
        output_rate = (
            pricing.long_output_per_million
            if pricing.long_output_per_million is not None
            else pricing.output_per_million
        )
    else:
        input_rate = pricing.input_per_million
        cached_rate = (
            pricing.cached_input_per_million
            if pricing.cached_input_per_million is not None
            else input_rate
        )
        cache_write_rate = (
            pricing.cache_write_per_million
            if pricing.cache_write_per_million is not None
            else input_rate
        )
        output_rate = pricing.output_per_million
    cost = (
        uncached * input_rate
        + cached * cached_rate
        + cache_write * cache_write_rate
        + max(0, output_tokens) * output_rate
    ) / 1_000_000
    if _normalize_service_tier(service_tier) == "fast":
        cost *= FAST_PRICE_MULTIPLIERS.get(normalized, 1.0)
    return cost


def _usage_contribution(
    current: tuple[int, int, int, int, int, int],
    previous: tuple[int, int, int, int, int, int] | None,
    last: tuple[int, int, int, int, int, int] | None,
) -> tuple[int, int, int, int, int, int]:
    """从累计快照提取本次真实增量。"""
    if previous is None or current[-1] < previous[-1]:
        return last or current
    if current[-1] == previous[-1]:
        return (0, 0, 0, 0, 0, 0)
    return tuple(max(0, value - old) for value, old in zip(current, previous))


def _parse_event_timestamp(value: Any, timezone: Any) -> datetime | None:
    """解析 rollout 事件时间并转换为本地时区。"""
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(timezone)


def _create_usage_tables(connection: duckdb.DuckDBPyConnection) -> None:
    """创建当前版本的用量索引表。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS rollout_files (
            thread_id VARCHAR PRIMARY KEY,
            path VARCHAR NOT NULL,
            device UBIGINT NOT NULL,
            inode UBIGINT NOT NULL,
            size UBIGINT NOT NULL,
            mtime_ns UBIGINT NOT NULL,
            parsed_bytes UBIGINT NOT NULL,
            last_input BIGINT,
            last_cached_input BIGINT,
            last_cache_write_input BIGINT,
            last_output BIGINT,
            last_reasoning_output BIGINT,
            last_total BIGINT,
            last_model VARCHAR,
            last_service_tier VARCHAR NOT NULL
        );
        CREATE TABLE IF NOT EXISTS token_usage_events (
            thread_id VARCHAR NOT NULL,
            event_key VARCHAR NOT NULL,
            usage_date DATE NOT NULL,
            model VARCHAR NOT NULL,
            service_tier VARCHAR NOT NULL,
            input_tokens BIGINT NOT NULL,
            cached_input_tokens BIGINT NOT NULL,
            cache_write_input_tokens BIGINT NOT NULL,
            output_tokens BIGINT NOT NULL,
            reasoning_output_tokens BIGINT NOT NULL,
            total_tokens BIGINT NOT NULL,
            PRIMARY KEY (thread_id, event_key)
        );
        """
    )


def _ensure_usage_cache(
    connection: duckdb.DuckDBPyConnection, *, days: int, timezone_name: str
) -> int:
    """初始化索引，并在请求更长时间范围时扩展缓存覆盖范围。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_cache_metadata (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL
        );
        """
    )
    _create_usage_tables(connection)
    existing = dict(
        connection.execute("SELECT key, value FROM usage_cache_metadata").fetchall()
    )
    try:
        coverage_days = int(existing.get("coverage_days", "0"))
    except ValueError:
        coverage_days = 0
    static_metadata_matches = (
        existing.get("schema_version") == str(USAGE_CACHE_SCHEMA_VERSION)
        and existing.get("timezone") == timezone_name
        and coverage_days >= 1
    )
    needs_rebuild = not static_metadata_matches
    needs_expansion = static_metadata_matches and days > coverage_days
    if needs_rebuild:
        coverage_days = days
        connection.execute("DROP TABLE rollout_files")
        connection.execute("DROP TABLE IF EXISTS token_usage_daily")
        connection.execute("DROP TABLE token_usage_events")
        _create_usage_tables(connection)
    elif needs_expansion:
        coverage_days = days
        connection.execute("DELETE FROM rollout_files")
        connection.execute("DELETE FROM token_usage_events")
    if needs_rebuild or needs_expansion:
        connection.execute("DELETE FROM usage_cache_metadata")
        connection.executemany(
            "INSERT INTO usage_cache_metadata VALUES (?, ?)",
            {
                "schema_version": str(USAGE_CACHE_SCHEMA_VERSION),
                "coverage_days": str(coverage_days),
                "timezone": timezone_name,
            }.items(),
        )
    return coverage_days


def _read_rollout_state(
    connection: duckdb.DuckDBPyConnection, thread_id: str
) -> _RolloutState | None:
    """读取单个 Thread 的解析位点。"""
    row = connection.execute(
        """
        SELECT path, device, inode, size, mtime_ns, parsed_bytes,
               last_input, last_cached_input, last_cache_write_input,
               last_output, last_reasoning_output, last_total, last_model,
               last_service_tier
        FROM rollout_files
        WHERE thread_id = ?
        """,
        [thread_id],
    ).fetchone()
    if row is None:
        return None
    last_total = None if row[6] is None else tuple(int(value) for value in row[6:12])
    return _RolloutState(
        path=str(row[0]),
        device=int(row[1]),
        inode=int(row[2]),
        size=int(row[3]),
        mtime_ns=int(row[4]),
        parsed_bytes=int(row[5]),
        last_total=last_total,
        last_model=str(row[12]) if row[12] is not None else None,
        last_service_tier=_normalize_service_tier(str(row[13])),
    )


def _write_rollout_state(
    connection: duckdb.DuckDBPyConnection,
    thread_id: str,
    path: Path,
    stat: os.stat_result,
    parsed_bytes: int,
    last_total: tuple[int, int, int, int, int, int] | None,
    last_model: str | None,
    last_service_tier: str,
) -> None:
    """持久化单个 Thread 的解析位点。"""
    values: tuple[int | None, ...] = last_total or (None,) * 6
    connection.execute(
        """
        INSERT INTO rollout_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (thread_id) DO UPDATE SET
            path = excluded.path,
            device = excluded.device,
            inode = excluded.inode,
            size = excluded.size,
            mtime_ns = excluded.mtime_ns,
            parsed_bytes = excluded.parsed_bytes,
            last_input = excluded.last_input,
            last_cached_input = excluded.last_cached_input,
            last_cache_write_input = excluded.last_cache_write_input,
            last_output = excluded.last_output,
            last_reasoning_output = excluded.last_reasoning_output,
            last_total = excluded.last_total,
            last_model = excluded.last_model,
            last_service_tier = excluded.last_service_tier
        """,
        [
            thread_id,
            str(path),
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            parsed_bytes,
            *values,
            last_model,
            _normalize_service_tier(last_service_tier),
        ],
    )


def _parse_rollout_usage(
    path: Path,
    *,
    thread_id: str,
    start_offset: int,
    previous_total: tuple[int, int, int, int, int, int] | None,
    current_model: str | None,
    current_service_tier: str,
    first_day: date,
    timezone: Any,
    event_sink: Callable[[list[_UsageEvent]], None] | None = None,
) -> tuple[
    list[_UsageEvent],
    int,
    tuple[int, int, int, int, int, int] | None,
    str | None,
    str,
]:
    """从指定字节位点解析 TokenCount 增量。"""
    events: list[_UsageEvent] = []
    parsed_bytes = start_offset
    with path.open("rb") as file:
        file.seek(start_offset)
        while True:
            line_start = file.tell()
            line = file.readline()
            if not line:
                break
            if not line.endswith(b"\n"):
                parsed_bytes = line_start
                break
            parsed_bytes = file.tell()
            if b"thread_settings_applied" in line:
                settings_model, settings_tier = _parse_thread_settings(line)
                current_model = settings_model or current_model
                current_service_tier = settings_tier or current_service_tier
            if b"turn_context" in line:
                current_model = _parse_turn_context_model(line) or current_model
            if b"token_count" not in line:
                continue
            event, previous_total = _parse_usage_event(
                line,
                thread_id=thread_id,
                line_start=line_start,
                previous_total=previous_total,
                model=current_model,
                service_tier=current_service_tier,
                first_day=first_day,
                timezone=timezone,
            )
            if event is not None:
                events.append(event)
                if event_sink is not None and len(events) >= USAGE_EVENT_BATCH_SIZE:
                    event_sink(events)
                    events = []
    if event_sink is not None and events:
        event_sink(events)
        events = []
    return (
        events,
        parsed_bytes,
        previous_total,
        current_model,
        _normalize_service_tier(current_service_tier),
    )


def _parse_turn_context_model(line: bytes) -> str | None:
    """从 turn_context 记录提取模型名。"""
    try:
        item = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(item, dict) or item.get("type") != "turn_context":
        return None
    payload = item.get("payload")
    model = payload.get("model") if isinstance(payload, dict) else None
    return _normalize_model(model) if isinstance(model, str) else None


def _parse_thread_settings(line: bytes) -> tuple[str | None, str | None]:
    """从 thread_settings_applied 记录提取模型和 service tier。"""
    try:
        item = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    payload = item.get("payload") if isinstance(item, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "thread_settings_applied"
    ):
        return None, None
    settings = payload.get("thread_settings")
    if not isinstance(settings, dict):
        return None, None
    model = settings.get("model")
    service_tier = settings.get("service_tier")
    return (
        _normalize_model(model) if isinstance(model, str) else None,
        _normalize_service_tier(service_tier)
        if isinstance(service_tier, str)
        else None,
    )


def _parse_usage_event(
    line: bytes,
    *,
    thread_id: str,
    line_start: int,
    previous_total: tuple[int, int, int, int, int, int] | None,
    model: str | None,
    service_tier: str,
    first_day: date,
    timezone: Any,
) -> tuple[
    _UsageEvent | None,
    tuple[int, int, int, int, int, int] | None,
]:
    """解析单条 TokenCount，并推进累计快照。"""
    try:
        item = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, previous_total
    payload = item.get("payload") if isinstance(item, dict) else None
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None, previous_total
    info = payload.get("info")
    if not isinstance(info, dict):
        return None, previous_total
    current = _usage_tuple(info.get("total_token_usage"))
    if current is None:
        return None, previous_total
    last = _usage_tuple(info.get("last_token_usage"))
    contribution = _usage_contribution(current, previous_total, last)
    timestamp = _parse_event_timestamp(item.get("timestamp"), timezone)
    if timestamp is None or timestamp.date() < first_day or contribution[-1] <= 0:
        return None, current
    ordinal = item.get("ordinal")
    event_key = (
        f"ordinal:{ordinal}"
        if isinstance(ordinal, int) and not isinstance(ordinal, bool)
        else f"offset:{line_start}"
    )
    normalized_model = _normalize_model(model)
    return (
        _UsageEvent(
            thread_id=thread_id,
            event_key=event_key,
            day=timestamp.date(),
            model=normalized_model,
            service_tier=_normalize_service_tier(service_tier),
            usage=contribution,
        ),
        current,
    )


def _parse_rollout_usage_tail(
    path: Path,
    *,
    thread_id: str,
    first_day: date,
    timezone: Any,
    event_sink: Callable[[list[_UsageEvent]], None] | None = None,
) -> tuple[
    list[_UsageEvent],
    int,
    tuple[int, int, int, int, int, int] | None,
    str | None,
    str,
]:
    """从文件尾部反向定位时间窗口，只解析窗口内的 TokenCount。"""
    scan_start = 0
    initial_model = None
    initial_service_tier = "standard"
    with path.open("rb") as file:
        if os.fstat(file.fileno()).st_size == 0:
            return [], 0, None, None, "standard"
        with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
            final_newline = data.rfind(b"\n")
            parsed_bytes = final_newline + 1
            position = parsed_bytes
            crossed_boundary = False
            while position > 0:
                line_end = position - 1
                previous_newline = data.rfind(b"\n", 0, line_end)
                line_start = previous_newline + 1
                prefix = bytes(data[line_start : min(line_end, line_start + 1024)])
                match = TIMESTAMP_PATTERN.search(prefix)
                if match is not None:
                    timestamp = _parse_event_timestamp(
                        match.group(1).decode("ascii", errors="ignore"), timezone
                    )
                    if timestamp is not None and timestamp.date() < first_day:
                        if not crossed_boundary:
                            scan_start = line_end + 1
                        crossed_boundary = True
                if crossed_boundary:
                    if b"turn_context" in prefix and initial_model is None:
                        initial_model = _parse_turn_context_model(
                            bytes(data[line_start:line_end])
                        )
                    if b"thread_settings_applied" in prefix:
                        settings_model, settings_tier = _parse_thread_settings(
                            bytes(data[line_start:line_end])
                        )
                        initial_model = initial_model or settings_model
                        initial_service_tier = settings_tier or initial_service_tier
                        break
                position = line_start
    return _parse_rollout_usage(
        path,
        thread_id=thread_id,
        start_offset=scan_start,
        previous_total=None,
        current_model=initial_model,
        current_service_tier=initial_service_tier,
        first_day=first_day,
        timezone=timezone,
        event_sink=event_sink,
    )


def _rollout_starts_within(path: Path, first_day: date) -> bool:
    """判断 rollout 文件名记录的起始日期是否已位于索引窗口内。"""
    match = ROLLOUT_DATE_PATTERN.search(path.name)
    if match is None:
        return False
    try:
        return date.fromisoformat(match.group(1)) >= first_day
    except ValueError:
        return False


def _upsert_usage_events(
    connection: duckdb.DuckDBPyConnection,
    events: list[_UsageEvent],
) -> None:
    """按事件批量写入 Token 增量，保留逐请求定价所需维度。"""
    if not events:
        return
    connection.executemany(
        """
        INSERT INTO token_usage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (thread_id, event_key) DO NOTHING
        """,
        [
            (
                event.thread_id,
                event.event_key,
                event.day,
                event.model,
                event.service_tier,
                *event.usage,
            )
            for event in events
        ],
    )


def _commit_usage_events(
    connection: duckdb.DuckDBPyConnection, events: list[_UsageEvent]
) -> None:
    """提交固定大小的事件批次，限制 DuckDB 事务内存。"""
    connection.execute("BEGIN TRANSACTION")
    try:
        _upsert_usage_events(connection, events)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _reset_rollout_scan(
    connection: duckdb.DuckDBPyConnection,
    *,
    thread_id: str,
    path: Path,
    stat: os.stat_result,
) -> None:
    """清空旧事件并留下未完成标记，使中断后的全量扫描可重试。"""
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            "DELETE FROM token_usage_events WHERE thread_id = ?", [thread_id]
        )
        _write_rollout_state(
            connection,
            thread_id,
            path,
            stat,
            0,
            None,
            None,
            "standard",
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _delete_rollout_state(
    connection: duckdb.DuckDBPyConnection, thread_id: str
) -> None:
    """原子删除单个已消失 rollout 的事件与解析状态。"""
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            "DELETE FROM token_usage_events WHERE thread_id = ?", [thread_id]
        )
        connection.execute("DELETE FROM rollout_files WHERE thread_id = ?", [thread_id])
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _index_rollout_job(
    connection: duckdb.DuckDBPyConnection,
    job: _RolloutScanJob,
    *,
    first_day: date,
    timezone: Any,
) -> None:
    """使用线程本地连接增量或全量索引一个 rollout。"""
    local_connection = connection.cursor()
    try:
        if job.can_append:
            if job.state is None:
                raise RuntimeError("增量扫描缺少 rollout 状态")
            start_offset = job.state.parsed_bytes
            previous_total = job.state.last_total
            current_model = job.state.last_model
            current_service_tier = job.state.last_service_tier
        else:
            _reset_rollout_scan(
                local_connection,
                thread_id=job.thread_id,
                path=job.path,
                stat=job.stat,
            )
            start_offset = 0
            previous_total = None
            current_model = None
            current_service_tier = "standard"

        event_sink = lambda batch: _commit_usage_events(local_connection, batch)
        try:
            if job.can_append or _rollout_starts_within(job.path, first_day):
                (
                    _events,
                    parsed_bytes,
                    last_total,
                    last_model,
                    last_service_tier,
                ) = _parse_rollout_usage(
                    job.path,
                    thread_id=job.thread_id,
                    start_offset=start_offset,
                    previous_total=previous_total,
                    current_model=current_model,
                    current_service_tier=current_service_tier,
                    first_day=first_day,
                    timezone=timezone,
                    event_sink=event_sink,
                )
            else:
                (
                    _events,
                    parsed_bytes,
                    last_total,
                    last_model,
                    last_service_tier,
                ) = _parse_rollout_usage_tail(
                    job.path,
                    thread_id=job.thread_id,
                    first_day=first_day,
                    timezone=timezone,
                    event_sink=event_sink,
                )
        except FileNotFoundError:
            return
        current_stat = job.path.stat()
        _write_rollout_state(
            local_connection,
            job.thread_id,
            job.path,
            current_stat,
            parsed_bytes,
            last_total,
            last_model,
            last_service_tier,
        )
    finally:
        local_connection.close()


def _rollout_paths(codex_home: Path) -> list[Path]:
    """同时发现活跃与已归档 rollout。"""
    roots = (codex_home / "sessions", codex_home / "archived_sessions")
    return sorted(
        path
        for root in roots
        if root.is_dir()
        for path in root.rglob("*.jsonl")
        if path.is_file()
    )


def collect_usage_history(
    codex_home: Path,
    cache_path: Path,
    *,
    now: datetime,
    days: int = DEFAULT_HISTORY_DAYS,
    pricing_catalog: PricingCatalog | None = None,
) -> UsageHistory:
    """增量索引本地 Thread，并返回按天 Token 用量。"""
    if days < 1:
        raise ValueError("days 必须大于等于 1")
    local_now = now.astimezone()
    timezone = local_now.tzinfo or UTC
    display_first_day = local_now.date() - timedelta(days=days - 1)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = duckdb.connect(str(cache_path))
        connection.execute("SET force_compression = 'zstd'")
        connection.execute("SET preserve_insertion_order = false")
    except duckdb.Error as error:
        if "connection" in locals():
            connection.close()
        raise UsageError(f"无法打开本地用量索引：{error}") from error
    paths = _rollout_paths(codex_home)
    cache_hits = 0
    full_scans = 0
    incremental_scans = 0
    discovered: set[str] = set()
    scan_jobs: list[_RolloutScanJob] = []
    try:
        coverage_days = _ensure_usage_cache(
            connection, days=days, timezone_name=str(timezone)
        )
        index_first_day = local_now.date() - timedelta(days=coverage_days - 1)
        first_timestamp = datetime.combine(
            index_first_day, datetime.min.time(), timezone
        ).timestamp()
        for path in paths:
            match = THREAD_ID_PATTERN.search(path.name)
            if match is None:
                continue
            thread_id = match.group(1).lower()
            discovered.add(thread_id)
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            state = _read_rollout_state(connection, thread_id)
            same_file = state is not None and (
                state.device == stat.st_dev and state.inode == stat.st_ino
            )
            unchanged = (
                same_file
                and state is not None
                and (
                    state.size == stat.st_size
                    and state.mtime_ns == stat.st_mtime_ns
                    and state.parsed_bytes == stat.st_size
                )
            )
            if unchanged:
                cache_hits += 1
                if state.path != str(path):
                    _write_rollout_state(
                        connection,
                        thread_id,
                        path,
                        stat,
                        state.parsed_bytes,
                        state.last_total,
                        state.last_model,
                        state.last_service_tier,
                    )
                continue

            if state is None and stat.st_mtime < first_timestamp:
                cache_hits += 1
                _write_rollout_state(
                    connection,
                    thread_id,
                    path,
                    stat,
                    stat.st_size,
                    None,
                    None,
                    "standard",
                )
                continue

            can_append = (
                same_file
                and state is not None
                and stat.st_size > state.parsed_bytes
                and stat.st_size >= state.size
                and state.parsed_bytes <= state.size
                and (state.parsed_bytes > 0 or state.size == 0)
            )
            if can_append:
                incremental_scans += 1
            else:
                full_scans += 1
            scan_jobs.append(
                _RolloutScanJob(
                    path=path,
                    thread_id=thread_id,
                    stat=stat,
                    state=state,
                    can_append=can_append,
                )
            )

        if scan_jobs:
            worker_count = min(
                USAGE_SCAN_WORKERS,
                os.cpu_count() or 1,
                len(scan_jobs),
            )
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(
                        _index_rollout_job,
                        connection,
                        job,
                        first_day=index_first_day,
                        timezone=timezone,
                    )
                    for job in scan_jobs
                ]
                for future in futures:
                    future.result()

        for (thread_id,) in connection.execute(
            "SELECT thread_id FROM rollout_files"
        ).fetchall():
            if thread_id not in discovered:
                _delete_rollout_state(connection, thread_id)
        connection.execute(
            "DELETE FROM token_usage_events WHERE usage_date < ?", [index_first_day]
        )

        rows = connection.execute(
            """
            SELECT usage_date,
                   model,
                   service_tier,
                   input_tokens,
                   cached_input_tokens,
                   cache_write_input_tokens,
                   output_tokens,
                   reasoning_output_tokens,
                   total_tokens
            FROM token_usage_events
            WHERE usage_date BETWEEN ? AND ?
            ORDER BY usage_date, model, event_key
            """,
            [display_first_day, local_now.date()],
        ).fetchall()
    except Exception as error:
        try:
            connection.execute("ROLLBACK")
        except duckdb.Error:
            pass
        raise UsageError(f"无法更新本地用量索引：{error}") from error
    finally:
        connection.close()

    resolved_pricing = pricing_catalog or PricingCatalog(
        dict(MODEL_PRICING),
        PricingMetadata(
            "built_in",
            datetime.fromisoformat(PRICING_UPDATED_AT).replace(tzinfo=UTC),
            False,
        ),
    )
    totals_by_model: dict[tuple[date, str], list[int]] = {}
    tier_tokens_by_model: dict[tuple[date, str], list[int]] = {}
    costs_by_model: dict[tuple[date, str], float | None] = {}
    for row in rows:
        key = (row[0], str(row[1]))
        usage = [int(value) for value in row[3:9]]
        totals = totals_by_model.setdefault(key, [0] * 6)
        for index, value in enumerate(usage):
            totals[index] += value
        tier_tokens = tier_tokens_by_model.setdefault(key, [0, 0])
        tier_index = 0 if _normalize_service_tier(str(row[2])) == "fast" else 1
        tier_tokens[tier_index] += usage[-1]
        cost = estimate_api_cost(
            str(row[1]),
            input_tokens=usage[0],
            cached_input_tokens=usage[1],
            cache_write_input_tokens=usage[2],
            output_tokens=usage[3],
            service_tier=str(row[2]),
            prices=resolved_pricing.prices,
        )
        previous_cost = costs_by_model.get(key, 0.0)
        costs_by_model[key] = (
            None if cost is None or previous_cost is None else previous_cost + cost
        )

    models_by_day: dict[date, list[ModelTokenUsage]] = {}
    for (usage_day, model), usage in sorted(totals_by_model.items()):
        fast_tokens, non_fast_tokens = tier_tokens_by_model[(usage_day, model)]
        models_by_day.setdefault(usage_day, []).append(
            ModelTokenUsage(
                model=model,
                input_tokens=usage[0],
                cached_input_tokens=usage[1],
                cache_write_input_tokens=usage[2],
                output_tokens=usage[3],
                reasoning_output_tokens=usage[4],
                total_tokens=usage[5],
                estimated_cost_usd=costs_by_model[(usage_day, model)],
                fast_tokens=fast_tokens,
                non_fast_tokens=non_fast_tokens,
            )
        )
    usage_by_day = {}
    for usage_day, models in models_by_day.items():
        totals = tuple(
            sum(getattr(model, field) for model in models)
            for field in (
                "input_tokens",
                "cached_input_tokens",
                "cache_write_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
                "total_tokens",
            )
        )
        usage_by_day[usage_day] = DailyTokenUsage(
            usage_day, *totals, models=tuple(models)
        )
    empty = (0, 0, 0, 0, 0, 0)
    daily = tuple(
        usage_by_day.get(
            day,
            DailyTokenUsage(day, *empty),
        )
        for offset in range(days)
        for day in (display_first_day + timedelta(days=offset),)
    )
    return UsageHistory(
        days=daily,
        scan=ScanStats(
            total_files=len(discovered),
            cache_hits=cache_hits,
            full_scans=full_scans,
            incremental_scans=incremental_scans,
        ),
        pricing=resolved_pricing.metadata,
    )


def calculate_progress(window: UsageWindow, now: datetime) -> WindowProgress:
    """计算额度剩余、时间剩余及两者差值。"""
    quota_remaining = max(0.0, min(100.0, 100.0 - window.used_percent))
    if window.duration_minutes is None or window.resets_at is None:
        return WindowProgress(quota_remaining, None, None, None)

    remaining_seconds = max(0.0, window.resets_at - now.timestamp())
    duration_seconds = window.duration_minutes * 60
    time_remaining = max(0.0, min(100.0, remaining_seconds / duration_seconds * 100))
    pace_delta = quota_remaining - time_remaining
    return WindowProgress(
        quota_remaining_percent=quota_remaining,
        time_remaining_percent=time_remaining,
        pace_delta=pace_delta,
        remaining_seconds=remaining_seconds,
    )


def _window_label(minutes: int | None, index: int) -> str:
    """把窗口时长转换为紧凑中文名称。"""
    if minutes is None:
        return f"窗口 {index}"
    if minutes % (24 * 60) == 0:
        return f"{minutes // (24 * 60)} 天"
    if minutes % 60 == 0:
        return f"{minutes // 60} 小时"
    return f"{minutes} 分钟"


def _remaining_text(seconds: float | None) -> str:
    """格式化窗口剩余时间。"""
    if seconds is None:
        return "未知"
    total_minutes = max(0, round(seconds / 60))
    days, minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if (minutes and not days) or not parts:
        parts.append(f"{minutes}分钟")
    return "".join(parts)


def _catch_up_seconds(window: UsageWindow, progress: WindowProgress) -> float | None:
    """返回暂停使用后额度进度与时间持平所需秒数。"""
    if (
        window.duration_minutes is None
        or progress.pace_delta is None
        or progress.pace_delta >= 0
    ):
        return None
    return -progress.pace_delta / 100 * window.duration_minutes * 60


def _catch_up_text(window: UsageWindow, progress: WindowProgress) -> str | None:
    """格式化暂停使用后额度进度与时间持平的提示。"""
    catch_up_seconds = _catch_up_seconds(window, progress)
    if catch_up_seconds is None or catch_up_seconds <= 0:
        return None
    rounded_seconds = max(60, ceil(catch_up_seconds / 60) * 60)
    return f"休息约{_remaining_text(rounded_seconds)}后持平"


def _bar(percent: float, color: str) -> ProgressBar:
    """创建固定宽度的剩余量进度条。"""
    return ProgressBar(
        total=100,
        completed=percent,
        width=18,
        style="grey23",
        complete_style=color,
        finished_style=color,
    )


def _remaining_color(percent: float) -> str:
    """根据剩余比例选择进度条颜色。"""
    if percent <= 15:
        return "bright_red"
    if percent <= 40:
        return "yellow"
    return "green"


def _pace_tolerance(duration_minutes: int | None) -> float:
    """返回不同额度窗口的节奏容差百分点。"""
    if duration_minutes == 300:
        return 10.0
    if duration_minutes == 7 * 24 * 60:
        return 3.0
    return 0.5


def _pace_text(delta: float | None, duration_minutes: int | None) -> Text:
    """展示额度消耗相对时间流逝的快慢。"""
    if delta is None:
        return Text("无法比较", style="dim")
    if abs(delta) < 0.05:
        return Text("与时间同步", style="cyan")
    if abs(delta) < _pace_tolerance(duration_minutes):
        direction = "略慢" if delta > 0 else "略快"
        return Text(f"{direction} {delta:+.1f}pp", style="cyan")
    if delta > 0:
        return Text(f"偏慢 {delta:+.1f}pp", style="green")
    return Text(f"偏快 {delta:+.1f}pp", style="bright_red")


def _format_token_count(value: int) -> str:
    """把 Token 数量压缩成紧凑展示文本。"""
    for divisor, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= divisor:
            number = value / divisor
            precision = 0 if number >= 100 else 1
            return f"{number:.{precision}f}{suffix}"
    return str(value)


def _cache_hit_text(day: DailyTokenUsage) -> str:
    """格式化每日模型输入缓存命中率。"""
    percent = day.cache_hit_percent
    return "—" if percent is None else f"{percent:.1f}%"


def _format_cost(estimated_cost_usd: float, unpriced_tokens: int) -> str:
    """格式化 API 等价成本，并标记未完整估价的情况。"""
    if unpriced_tokens > 0:
        return f"≥${estimated_cost_usd:.2f}" if estimated_cost_usd > 0 else "—"
    return f"≈${estimated_cost_usd:.2f}"


def _render_usage_history(history: UsageHistory, *, verbose: bool) -> None:
    """用 Rich 展示按天 Token 用量与缓存命中率。"""
    table = Table(box=None, padding=(0, 1), show_header=True)
    table.add_column("日期", style="bold", no_wrap=True)
    table.add_column("Token", justify="right", no_wrap=True)
    table.add_column("缓存命中", justify="right", no_wrap=True)
    table.add_column("预估金额", justify="right", no_wrap=True)
    for day in history.days:
        table.add_row(
            day.day.strftime("%m-%d"),
            _format_token_count(day.total_tokens),
            _cache_hit_text(day),
            _format_cost(day.estimated_cost_usd, day.unpriced_tokens),
        )
    scan = history.scan
    subtitle_parts = []
    if history.unpriced_tokens:
        subtitle_parts.append(
            f"[yellow]未估价 {_format_token_count(history.unpriced_tokens)} Token[/]"
        )
    if verbose:
        subtitle_parts.append(
            f"[dim]索引命中 {scan.cache_hits}/{scan.total_files} · "
            f"全量 {scan.full_scans} · 增量 {scan.incremental_scans}[/]"
        )
        if history.pricing is not None:
            fetched_at = (
                history.pricing.fetched_at.astimezone().strftime("%m-%d %H:%M")
                if history.pricing.fetched_at is not None
                else "未知"
            )
            stale = " · 已过期" if history.pricing.stale else ""
            subtitle_parts.append(
                f"[dim]价格 {history.pricing.source} · {fetched_at}{stale}[/]"
            )
    console.print(
        Panel(
            table,
            title=(
                f"[bold]最近 {len(history.days)} 天 Token · "
                f"{_format_token_count(history.total_tokens)} · "
                f"API 等价 {_format_cost(history.estimated_cost_usd, history.unpriced_tokens)}[/]"
            ),
            subtitle=" · ".join(subtitle_parts) or None,
            border_style="blue",
            padding=(0, 1),
        )
    )


def render_usage(
    buckets: list[LimitBucket],
    now: datetime,
    *,
    history: UsageHistory | None = None,
    verbose: bool,
) -> None:
    """用 Rich 渲染订阅与额度进度。"""
    if history is not None:
        _render_usage_history(history, verbose=verbose)
    for bucket in _visible_buckets(buckets, verbose=verbose):
        table = Table(
            box=None,
            padding=(0, 1),
            show_header=False,
        )
        table.add_column(style="bold", no_wrap=True, width=7)
        table.add_column(no_wrap=True, width=4)
        table.add_column(width=18)
        table.add_column(justify="left", no_wrap=True, width=25)

        if not bucket.windows:
            row = ["—", "—", Text("服务端未提供窗口", style="dim"), "—"]
            table.add_row(*row)
        for index, window in enumerate(bucket.windows, start=1):
            progress = calculate_progress(window, now)
            label = _window_label(window.duration_minutes, index)
            quota_color = _remaining_color(progress.quota_remaining_percent)
            quota_summary = Text(f"{progress.quota_remaining_percent:.0f}% · ")
            quota_summary.append_text(
                _pace_text(progress.pace_delta, window.duration_minutes)
            )
            if catch_up_text := _catch_up_text(window, progress):
                quota_summary.append(f"\n{catch_up_text}", style="bright_red")
            quota_row: list[Any] = [
                label,
                "额度",
                _bar(progress.quota_remaining_percent, quota_color),
                quota_summary,
            ]
            table.add_row(*quota_row)
            reset_text: str | None = None
            if progress.time_remaining_percent is None:
                time_row: list[Any] = ["", "时间", Text("不可用", style="dim"), "未知"]
                table.add_row(*time_row)
            else:
                reset_text = (
                    datetime.fromtimestamp(window.resets_at or 0)
                    .astimezone()
                    .strftime("%Y-%m-%d %H:%M")
                )
                time_row = [
                    "",
                    "时间",
                    _bar(progress.time_remaining_percent, "blue"),
                    f"{progress.time_remaining_percent:.0f}% · {_remaining_text(progress.remaining_seconds)}",
                ]
                table.add_row(*time_row)
            if verbose:
                reset_detail = (
                    Text(f"重置 {reset_text}", style="dim") if reset_text else Text("")
                )
                table.add_row("", "详情", "", reset_detail)
        title = bucket.name or (
            "Codex（通用）" if bucket.limit_id == "codex" else bucket.limit_id
        )
        plan = bucket.plan_type.upper() if bucket.plan_type else "UNKNOWN"
        console.print(
            Panel(
                table,
                title=f"[bold]{title} · {plan}[/]",
                subtitle=f"[dim]{bucket.limit_id}[/]" if verbose else None,
                border_style="cyan" if bucket.limit_id == "codex" else "magenta",
                padding=(0, 1),
            )
        )


def _svg_text(value: object) -> str:
    """转义 SVG 动态文本。"""
    return escape(str(value), quote=True)


def _svg_pace(delta: float | None, duration_minutes: int | None) -> tuple[str, str]:
    """返回 SVG 使用的节奏文本与颜色。"""
    pace = _pace_text(delta, duration_minutes)
    if delta is None:
        return pace.plain, "#7f8aa3"
    if abs(delta) < 0.05:
        return pace.plain, "#8be9fd"
    if abs(delta) < _pace_tolerance(duration_minutes):
        return pace.plain, "#f1c75b" if delta < 0 else "#8be9fd"
    return pace.plain, "#50fa7b" if delta > 0 else "#ff5555"


def _svg_relation(delta: float | None, duration_minutes: int | None) -> tuple[str, str]:
    """返回直接描述额度与时间差距的文本和颜色。"""
    pace, color = _svg_pace(delta, duration_minutes)
    if delta is None:
        return "额度与时间无法比较", color
    if abs(delta) < 0.05:
        return "额度与时间同步", color
    relation = "多" if delta > 0 else "少"
    direction = pace.split(maxsplit=1)[0]
    return f"额度{relation} {abs(delta):.1f}pp · {direction}", color


def _svg_comparison_rail(
    progress: WindowProgress,
    *,
    x: float,
    y: float,
    width: float,
) -> str:
    """用同尺度双色双轨比较额度和时间。"""
    quota_percent = max(0.0, min(100.0, progress.quota_remaining_percent))
    quota_x = x + width * quota_percent / 100
    quota_y = y - 17
    time_y = y + 17
    parts = [
        f'<line data-role="quota-track" x1="{x}" y1="{quota_y}" x2="{x + width}" y2="{quota_y}" stroke="#283149" stroke-width="9" stroke-linecap="round"/>',
        f'<line data-role="time-track" x1="{x}" y1="{time_y}" x2="{x + width}" y2="{time_y}" stroke="#283149" stroke-width="9" stroke-linecap="round"/>',
    ]
    if progress.time_remaining_percent is not None:
        time_percent = max(0.0, min(100.0, progress.time_remaining_percent))
        time_x = x + width * time_percent / 100
        parts.extend(
            [
                f'<line x1="{x}" y1="{time_y}" x2="{time_x}" y2="{time_y}" stroke="#8f9fe8" stroke-width="9" stroke-linecap="round"/>',
                f'<line x1="{time_x}" y1="{time_y - 10}" x2="{time_x}" y2="{time_y + 10}" stroke="#aebaff" stroke-width="4" stroke-linecap="round"/>',
                f'<text x="{x - 14}" y="{time_y + 5}" text-anchor="end" fill="#aebaff" font-size="13" font-weight="650">时间剩余</text>',
                f'<text x="{x + width + 14}" y="{time_y + 5}" fill="#aebaff" font-size="14" font-weight="700">{time_percent:.0f}%</text>',
            ]
        )
    else:
        parts.append(
            f'<text x="{x - 14}" y="{time_y + 5}" text-anchor="end" class="muted" font-size="13">时间剩余</text>\n  <text x="{x + width + 14}" y="{time_y + 5}" class="muted" font-size="14">未知</text>'
        )
    parts.extend(
        [
            f'<line x1="{x}" y1="{quota_y}" x2="{quota_x}" y2="{quota_y}" stroke="#50fa7b" stroke-width="9" stroke-linecap="round"/>',
            f'<line x1="{quota_x}" y1="{quota_y - 10}" x2="{quota_x}" y2="{quota_y + 10}" stroke="#50fa7b" stroke-width="4" stroke-linecap="round"/>',
            f'<text x="{x - 14}" y="{quota_y + 5}" text-anchor="end" fill="#50fa7b" font-size="13" font-weight="650">额度剩余</text>',
            f'<text x="{x + width + 14}" y="{quota_y + 5}" fill="#50fa7b" font-size="14" font-weight="700">{quota_percent:.0f}%</text>',
        ]
    )
    return "\n  ".join(parts)


def _dashboard_summary(buckets: list[LimitBucket], now: datetime) -> tuple[str, str]:
    """归纳整个看板最需要关注的用量状态。"""
    deltas = [
        (progress.pace_delta, window.duration_minutes)
        for bucket in buckets
        for window in bucket.windows
        if (progress := calculate_progress(window, now)).pace_delta is not None
    ]
    if any(
        delta <= -_pace_tolerance(duration)
        for delta, duration in deltas
        if delta is not None
    ):
        return "消耗偏快，留意额度", "#ff5555"
    if any(delta < -0.05 for delta, _ in deltas if delta is not None):
        return "消耗略快，暂时无需干预", "#f1c75b"
    if any(delta > 0.05 for delta, _ in deltas if delta is not None):
        return "额度充足，节奏安全", "#50fa7b"
    if deltas:
        return "额度与时间基本同步", "#8be9fd"
    return "等待完整窗口数据", "#7f8aa3"


def _svg_usage_history(
    history: UsageHistory,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    verbose: bool,
) -> str:
    """生成不受极值影响的等高每日 Token 信息卡。"""
    days = history.days
    max_tokens = max((day.total_tokens for day in days), default=0)
    card_gap = 10.0
    grid_columns = min(10, max(1, len(days)))
    content_x = x + 18
    content_y = y + 58
    content_width = width - 36
    card_width = (content_width - card_gap * max(0, grid_columns - 1)) / grid_columns
    card_height = 140.0
    parts = [
        f'<g data-role="daily-usage" data-grid-columns="{grid_columns}" filter="url(#shadow)"><rect x="{x}" y="{y}" width="{width}" height="{height}" rx="24" fill="#151b2d" stroke="#283149"/></g>',
        f'<text x="{x + 26}" y="{y + 40}" fill="#f8f8f2" font-size="22" font-weight="700">最近 {len(days)} 天 Token · {_svg_text(_format_token_count(history.total_tokens))} · API 等价 {_svg_text(_format_cost(history.estimated_cost_usd, history.unpriced_tokens))}</text>',
    ]
    if verbose:
        scan = history.scan
        parts.append(
            f'<text x="{x + width - 26}" y="{y + 38}" text-anchor="end" class="muted" font-size="13">索引命中 {scan.cache_hits}/{scan.total_files} · 全量 {scan.full_scans} · 增量 {scan.incremental_scans}</text>'
        )
    for index, day in enumerate(days):
        row_index, column_index = divmod(index, grid_columns)
        card_x = content_x + column_index * (card_width + card_gap)
        card_y = content_y + row_index * (card_height + card_gap)
        center_x = card_x + card_width / 2
        intensity_width = (
            0.0
            if max_tokens <= 0 or day.total_tokens <= 0
            else max(12.0, (card_width - 28) * day.total_tokens / max_tokens)
        )
        cache_text = _cache_hit_text(day)
        parts.extend(
            [
                f'<g data-role="day-card"><rect x="{card_x}" y="{card_y}" width="{card_width}" height="{card_height}" rx="14" fill="#101626" stroke="#202941"/></g>',
                f'<text x="{center_x}" y="{card_y + 27}" text-anchor="middle" class="muted" font-size="13">{day.day.strftime("%m-%d")}</text>',
                f'<text x="{center_x}" y="{card_y + 63}" text-anchor="middle" fill="#f8f8f2" font-size="24" font-weight="750">{_svg_text(_format_token_count(day.total_tokens))}</text>',
                f'<text x="{center_x}" y="{card_y + 91}" text-anchor="middle" fill="#bd93f9" font-size="13" font-weight="650">缓存 {_svg_text(cache_text)}</text>',
                f'<text x="{center_x}" y="{card_y + 116}" text-anchor="middle" fill="#50fa7b" font-size="14" font-weight="700">{_svg_text(_format_cost(day.estimated_cost_usd, day.unpriced_tokens))}</text>',
            ]
        )
        if intensity_width > 0:
            parts.append(
                f'<rect x="{card_x + 14}" y="{card_y + card_height - 10}" width="{intensity_width}" height="4" rx="2" fill="#8be9fd" fill-opacity="0.86"/>'
            )
    return "\n  ".join(parts)


def _usage_history_height(day_count: int) -> int:
    """根据日期数量返回自适应网格高度。"""
    columns = min(10, max(1, day_count))
    rows = ceil(max(1, day_count) / columns)
    return 76 + rows * 140 + max(0, rows - 1) * 10


def _render_compact_usage_svg(
    buckets: list[LimitBucket], now: datetime, history: UsageHistory
) -> str:
    """渲染以每日用量为主、额度摘要为辅的默认看板。"""
    margin = 48
    header_height = 86
    card_gap = 20
    history_height = _usage_history_height(len(history.days))
    quota_heights = [70 + 56 * max(1, len(bucket.windows)) for bucket in buckets]
    height = (
        header_height
        + history_height
        + card_gap
        + sum(quota_heights)
        + card_gap * max(0, len(quota_heights) - 1)
        + margin
    )
    summary, summary_color = _dashboard_summary(buckets, now)
    parts = [
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{height}" viewBox="0 0 {SVG_WIDTH} {height}">
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0b1020"/>
      <stop offset="1" stop-color="#121a30"/>
    </linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">
      <feDropShadow dx="0" dy="8" stdDeviation="12" flood-color="#050814" flood-opacity="0.36"/>
    </filter>
  </defs>
  <rect width="{SVG_WIDTH}" height="{height}" rx="30" fill="url(#background)"/>
  <style>
    text {{ font-family: "SF Pro Display", "PingFang SC", "Noto Sans CJK SC", sans-serif; }}
    .muted {{ fill: #7f8aa3; }}
  </style>
  <text x="{margin}" y="55" fill="#f8f8f2" font-size="32" font-weight="750">ChatGPT Usage</text>
  <rect x="{SVG_WIDTH - margin - 300}" y="22" width="300" height="40" rx="20" fill="{summary_color}" fill-opacity="0.13"/>
  <circle cx="{SVG_WIDTH - margin - 276}" cy="42" r="6" fill="{summary_color}"/>
  <text x="{SVG_WIDTH - margin - 258}" y="48" fill="{summary_color}" font-size="16" font-weight="700">{_svg_text(summary)}</text>'''
    ]
    parts.append(
        _svg_usage_history(
            history,
            x=margin,
            y=header_height,
            width=SVG_WIDTH - margin * 2,
            height=history_height,
            verbose=False,
        )
    )

    y = float(header_height + history_height + card_gap)
    for bucket, quota_height in zip(buckets, quota_heights, strict=True):
        accent = "#8be9fd" if bucket.limit_id == "codex" else "#bd93f9"
        title = bucket.name or (
            "Codex（通用）" if bucket.limit_id == "codex" else bucket.limit_id
        )
        plan = bucket.plan_type.upper() if bucket.plan_type else "UNKNOWN"
        parts.append(
            f'''<g data-role="quota-summary" filter="url(#shadow)"><rect x="{margin}" y="{y}" width="{SVG_WIDTH - margin * 2}" height="{quota_height}" rx="22" fill="#151b2d" stroke="#283149"/></g>
  <circle cx="{margin + 28}" cy="{y + 30}" r="6" fill="{accent}"/>
  <text x="{margin + 46}" y="{y + 37}" fill="#f8f8f2" font-size="20" font-weight="700">{_svg_text(title)}</text>
  <text x="{SVG_WIDTH - margin - 24}" y="{y + 36}" text-anchor="end" fill="{accent}" font-size="13" font-weight="700">{_svg_text(plan)}</text>'''
        )
        windows = bucket.windows or (None,)
        for index, window in enumerate(windows, start=1):
            row_y = y + 66 + (index - 1) * 56
            if window is None:
                parts.append(
                    f'<text x="{margin + 26}" y="{row_y + 18}" class="muted" font-size="15">服务端未提供窗口</text>'
                )
                continue
            progress = calculate_progress(window, now)
            label = _window_label(window.duration_minutes, index)
            relation, pace_color = _svg_relation(
                progress.pace_delta, window.duration_minutes
            )
            relation = _catch_up_text(window, progress) or relation
            track_x = margin + 190
            track_width = 650
            quota_x = track_x + track_width * progress.quota_remaining_percent / 100
            parts.extend(
                [
                    f'<text x="{margin + 26}" y="{row_y + 19}" fill="#f8f8f2" font-size="15" font-weight="700">{_svg_text(label)}</text>',
                    f'<text x="{margin + 92}" y="{row_y + 19}" fill="#50fa7b" font-size="18" font-weight="750">{progress.quota_remaining_percent:.0f}%</text>',
                    f'<line data-role="quota-progress" x1="{track_x}" y1="{row_y + 13}" x2="{track_x + track_width}" y2="{row_y + 13}" stroke="#283149" stroke-width="8" stroke-linecap="round"/>',
                    f'<line x1="{track_x}" y1="{row_y + 13}" x2="{quota_x}" y2="{row_y + 13}" stroke="#50fa7b" stroke-width="8" stroke-linecap="round"/>',
                ]
            )
            if progress.time_remaining_percent is not None:
                time_x = track_x + track_width * progress.time_remaining_percent / 100
                parts.append(
                    f'<line x1="{time_x}" y1="{row_y + 3}" x2="{time_x}" y2="{row_y + 23}" stroke="#aebaff" stroke-width="3" stroke-linecap="round"/>'
                )
            parts.extend(
                [
                    f'<text x="{track_x + track_width + 24}" y="{row_y + 19}" class="muted" font-size="13">{_svg_text(_remaining_text(progress.remaining_seconds))}后重置</text>',
                    f'<rect x="{SVG_WIDTH - margin - 214}" y="{row_y - 4}" width="190" height="34" rx="17" fill="{pace_color}" fill-opacity="0.13"/>',
                    f'<text x="{SVG_WIDTH - margin - 119}" y="{row_y + 18}" text-anchor="middle" fill="{pace_color}" font-size="13" font-weight="700">{_svg_text(relation)}</text>',
                ]
            )
        y += quota_height + card_gap
    parts.append("</svg>\n")
    return "\n".join(parts)


def render_usage_svg(
    buckets: list[LimitBucket],
    now: datetime,
    *,
    history: UsageHistory | None = None,
    verbose: bool,
) -> str:
    """把额度看板渲染为共享刻度对比 SVG。"""
    buckets = _visible_buckets(buckets, verbose=verbose)
    if history is not None and not verbose:
        return _render_compact_usage_svg(buckets, now, history)
    margin = 48
    card_gap = 24
    panel_gap = 18
    panel_height = 154
    header_height = 110
    bucket_header_height = 70
    max_window_columns = 3
    bucket_rows: list[list[LimitBucket]] = []
    current_row: list[LimitBucket] = []
    occupied_columns = 0
    for bucket in buckets:
        span = min(max_window_columns, max(1, len(bucket.windows)))
        if current_row and occupied_columns + span > max_window_columns:
            bucket_rows.append(current_row)
            current_row = []
            occupied_columns = 0
        current_row.append(bucket)
        occupied_columns += span
    if current_row:
        bucket_rows.append(current_row)

    row_heights = []
    for row in bucket_rows:
        window_rows = max(
            ceil(max(1, len(bucket.windows)) / max_window_columns) for bucket in row
        )
        row_heights.append(
            bucket_header_height
            + window_rows * panel_height
            + (window_rows - 1) * panel_gap
            + 18
        )
    bucket_content_height = (
        header_height + sum(row_heights) + card_gap * max(0, len(bucket_rows) - 1)
    )
    history_height = (
        _usage_history_height(len(history.days)) if history is not None else 0
    )
    height = (
        bucket_content_height
        + (card_gap + history_height if history is not None else 0)
        + margin
    )
    summary, summary_color = _dashboard_summary(buckets, now)
    parts = [
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{height}" viewBox="0 0 {SVG_WIDTH} {height}">
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0b1020"/>
      <stop offset="1" stop-color="#121a30"/>
    </linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">
      <feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="#050814" flood-opacity="0.42"/>
    </filter>
  </defs>
  <rect width="{SVG_WIDTH}" height="{height}" rx="30" fill="url(#background)"/>
  <style>
    text {{ font-family: "SF Pro Display", "PingFang SC", "Noto Sans CJK SC", sans-serif; }}
    .muted {{ fill: #7f8aa3; }}
  </style>
  <text x="{margin}" y="64" fill="#f8f8f2" font-size="38" font-weight="750">ChatGPT Usage</text>
  <rect x="{SVG_WIDTH - margin - 354}" y="30" width="354" height="48" rx="24" fill="{summary_color}" fill-opacity="0.13"/>
  <circle cx="{SVG_WIDTH - margin - 326}" cy="54" r="7" fill="{summary_color}"/>
  <text x="{SVG_WIDTH - margin - 306}" y="61" fill="{summary_color}" font-size="19" font-weight="700">{_svg_text(summary)}</text>'''
    ]

    bucket_layouts: list[tuple[LimitBucket, float, float, float, float]] = []
    y = float(header_height)
    for row, row_height in zip(bucket_rows, row_heights, strict=True):
        spans = [min(max_window_columns, max(1, len(bucket.windows))) for bucket in row]
        available_width = SVG_WIDTH - margin * 2 - card_gap * (len(row) - 1)
        total_span = sum(spans)
        bucket_x = float(margin)
        for bucket, span in zip(row, spans, strict=True):
            bucket_width = available_width * span / total_span
            bucket_layouts.append((bucket, bucket_x, y, bucket_width, row_height))
            bucket_x += bucket_width + card_gap
        y += row_height + card_gap

    for bucket, bucket_x, y, bucket_width, bucket_height in bucket_layouts:
        accent = "#8be9fd" if bucket.limit_id == "codex" else "#bd93f9"
        title = bucket.name or (
            "Codex（通用）" if bucket.limit_id == "codex" else bucket.limit_id
        )
        plan = bucket.plan_type.upper() if bucket.plan_type else "UNKNOWN"
        parts.append(
            f'''
  <g filter="url(#shadow)">
    <rect x="{bucket_x}" y="{y}" width="{bucket_width}" height="{bucket_height}" rx="24" fill="#151b2d" stroke="#283149"/>
    <rect x="{bucket_x}" y="{y}" width="6" height="{bucket_height}" rx="3" fill="{accent}"/>
  </g>
  <circle cx="{bucket_x + 34}" cy="{y + 34}" r="7" fill="{accent}"/>
  <text x="{bucket_x + 54}" y="{y + 42}" fill="#f8f8f2" font-size="24" font-weight="700">{_svg_text(title)}</text>
  <rect x="{bucket_x + bucket_width - 104}" y="{y + 18}" width="76" height="30" rx="15" fill="{accent}" fill-opacity="0.14"/>
  <text x="{bucket_x + bucket_width - 66}" y="{y + 39}" text-anchor="middle" fill="{accent}" font-size="14" font-weight="700">{_svg_text(plan)}</text>'''
        )
        if verbose:
            parts.append(
                f'  <text x="{bucket_x + 54}" y="{y + 60}" class="muted" font-size="13">{_svg_text(bucket.limit_id)}</text>'
            )

        windows = bucket.windows or (None,)
        column_count = min(max_window_columns, len(windows))
        panel_width = (
            bucket_width - 40 - panel_gap * (column_count - 1)
        ) / column_count
        for index, window in enumerate(windows, start=1):
            row_index, column_index = divmod(index - 1, column_count)
            panel_x = bucket_x + 20 + column_index * (panel_width + panel_gap)
            panel_y = y + bucket_header_height + row_index * (panel_height + panel_gap)
            parts.append(
                f'  <rect x="{panel_x}" y="{panel_y}" width="{panel_width}" height="{panel_height}" rx="18" fill="#101626"/>'
            )
            if window is None:
                parts.append(
                    f'  <text x="{panel_x + 28}" y="{panel_y + 60}" class="muted" font-size="17">服务端未提供窗口</text>'
                )
                continue

            progress = calculate_progress(window, now)
            label = _window_label(window.duration_minutes, index)
            relation_text, pace_color = _svg_relation(
                progress.pace_delta, window.duration_minutes
            )
            relation_text = _catch_up_text(window, progress) or relation_text
            rail_x = panel_x + 112
            rail_width = panel_width - 176
            badge_width = min(220, panel_width * 0.55)
            badge_x = panel_x + panel_width - badge_width - 18
            parts.append(
                f'''
  <text x="{panel_x + 22}" y="{panel_y + 29}" fill="#f8f8f2" font-size="18" font-weight="700">{_svg_text(label)}</text>
  <rect x="{badge_x}" y="{panel_y + 12}" width="{badge_width}" height="32" rx="16" fill="{pace_color}" fill-opacity="0.13"/>
  <text x="{badge_x + badge_width / 2}" y="{panel_y + 34}" text-anchor="middle" fill="{pace_color}" font-size="14" font-weight="700">{_svg_text(relation_text)}</text>
  {_svg_comparison_rail(progress, x=rail_x, y=panel_y + 83, width=rail_width)}
  <text x="{panel_x + 22}" y="{panel_y + 140}" class="muted" font-size="12">距离重置 {_svg_text(_remaining_text(progress.remaining_seconds))}</text>'''
            )
            if verbose and window.resets_at is not None:
                reset_text = (
                    datetime.fromtimestamp(window.resets_at)
                    .astimezone()
                    .strftime("%Y-%m-%d %H:%M")
                )
                parts.append(
                    f'  <text x="{panel_x + panel_width - 22}" y="{panel_y + 140}" text-anchor="end" class="muted" font-size="11">重置于 {_svg_text(reset_text)}</text>'
                )

    if history is not None:
        parts.append(
            _svg_usage_history(
                history,
                x=margin,
                y=bucket_content_height + card_gap,
                width=SVG_WIDTH - margin * 2,
                height=history_height,
                verbose=verbose,
            )
        )
    parts.append("</svg>\n")
    return "\n".join(parts)


def svg_to_png(svg: str) -> bytes:
    """使用进程内 resvg 把 SVG 栅格化为高分屏 PNG。"""
    try:
        png = svg_to_bytes(svg_string=svg, zoom=IMAGE_SCALE)
    except Exception as error:
        raise UsageError(f"SVG 渲染失败：{error}") from error
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise UsageError("resvg 没有返回有效的 PNG")
    return png


def render_usage_image(
    buckets: list[LimitBucket],
    now: datetime,
    *,
    history: UsageHistory | None = None,
    columns: int | None,
    verbose: bool,
) -> None:
    """生成 SVG、栅格化，并通过 Kitty 协议展示。"""
    svg = render_usage_svg(buckets, now, history=history, verbose=verbose)
    png = svg_to_png(svg)
    render_png(png, cols=columns)


def image_environment_hint(environment: dict[str, str] | None = None) -> bool:
    """根据终端标识保守识别 Kitty 图片能力。"""
    values = os.environ if environment is None else environment
    term = values.get("TERM", "").lower()
    term_program = values.get("TERM_PROGRAM", "").lower()
    return bool(
        values.get("KITTY_WINDOW_ID")
        or values.get("GHOSTTY_RESOURCES_DIR")
        or "kitty" in term
        or "ghostty" in term
        or term_program in {"ghostty", "wezterm"}
    )


def supports_image_output(stream: Any = None) -> bool:
    """保守判断当前输出是否适合 Kitty 图片协议。"""
    target = stream or sys.stdout
    try:
        return bool(target.isatty() and image_environment_hint())
    except (AttributeError, OSError, RuntimeError):
        return False


def default_image_columns() -> int:
    """使用接近完整宽度，并避开终端行尾自动换行。"""
    terminal_columns = shutil.get_terminal_size(fallback=(120, 40)).columns
    requested_columns = ceil(terminal_columns * DEFAULT_IMAGE_WIDTH_RATIO)
    return min(requested_columns, max(1, terminal_columns - 1))


def _json_report(
    buckets: list[LimitBucket],
    now: datetime,
    history: UsageHistory | None = None,
) -> dict[str, Any]:
    """构造稳定的机器可读结果。"""
    rows: list[dict[str, Any]] = []
    for bucket in buckets:
        bucket_data = asdict(bucket)
        bucket_data["windows"] = []
        for index, window in enumerate(bucket.windows, start=1):
            window_data = asdict(window)
            window_data["label"] = _window_label(window.duration_minutes, index)
            window_data["progress"] = asdict(calculate_progress(window, now))
            bucket_data["windows"].append(window_data)
        rows.append(bucket_data)
    local_usage = None
    if history is not None:
        pricing = history.pricing
        local_usage = {
            "days": [
                {
                    **asdict(day),
                    "day": day.day.isoformat(),
                    "estimated_cost_usd": day.estimated_cost_usd,
                    "unpriced_tokens": day.unpriced_tokens,
                }
                for day in history.days
            ],
            "total_tokens": history.total_tokens,
            "estimated_cost_usd": history.estimated_cost_usd,
            "unpriced_tokens": history.unpriced_tokens,
            "pricing_basis": "current_standard_api_equivalent",
            "pricing": {
                "source": pricing.source if pricing is not None else "unknown",
                "fetched_at": (
                    pricing.fetched_at.isoformat()
                    if pricing is not None and pricing.fetched_at is not None
                    else None
                ),
                "stale": pricing.stale if pricing is not None else True,
                "fallback": "built_in",
                "error": pricing.error if pricing is not None else None,
            },
            "scan": asdict(history.scan),
        }
    return {
        "fetched_at": now.isoformat(),
        "buckets": rows,
        "local_usage": local_usage,
    }


@app.command()
def main(
    codex_bin: Annotated[
        Path | None,
        typer.Option("--codex-bin", help="Codex CLI 路径；默认从 PATH 查找。"),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option("--timeout", min=1, help="等待 Codex app-server 的秒数。"),
    ] = 30,
    codex_home: Annotated[
        Path | None,
        typer.Option(
            "--codex-home",
            help="Codex 本地数据目录；默认使用 CODEX_HOME 或 ~/.codex。",
        ),
    ] = None,
    usage_cache: Annotated[
        Path | None,
        typer.Option(
            "--usage-cache",
            help="本地用量 DuckDB 索引路径。",
        ),
    ] = None,
    history_days: Annotated[
        int,
        typer.Option(
            "--history-days",
            min=1,
            max=365,
            help="本地 Token 用量展示天数；扩大范围时会补建一次索引。",
        ),
    ] = DEFAULT_HISTORY_DAYS,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="输出机器可读 JSON。"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="显示额度 ID 与精确重置时间。"),
    ] = False,
    image_output: Annotated[
        bool | None,
        typer.Option(
            "--image/--text",
            help="强制使用图片或 Rich 文本；默认自动探测。",
        ),
    ] = None,
    image_width: Annotated[
        int | None,
        typer.Option(
            "--image-width",
            min=24,
            max=240,
            help="图片占用的终端列数；默认使用可用终端宽度。",
        ),
    ] = None,
    save_svg: Annotated[
        Path | None,
        typer.Option("--save-svg", help="同时把 SVG 看板保存到指定路径。"),
    ] = None,
) -> None:
    """显示 Codex 额度、时间进度与最近本地 Token 用量。"""
    if json_output and image_output is True:
        raise typer.BadParameter("--json 与 --image 不能同时使用")
    resolved = codex_bin or (Path(found) if (found := shutil.which("codex")) else None)
    if resolved is None:
        error_console.print("[bold red]错误：[/]PATH 中找不到 Codex CLI")
        raise typer.Exit(1)

    try:
        result = fetch_rate_limits(resolved, timeout)
        buckets = parse_rate_limits(result)
    except UsageError as error:
        error_console.print(f"[bold red]错误：[/]{error}")
        error_console.print("请先确认 Codex CLI 已使用 ChatGPT 账号登录。", style="dim")
        raise typer.Exit(1) from error

    now = datetime.now(UTC)
    history = None
    resolved_usage_cache = (usage_cache or default_usage_cache_path()).expanduser()
    pricing_cache = resolved_usage_cache.with_name(
        f"models-dev-v{PRICING_CACHE_VERSION}.json"
    )
    pricing_catalog = load_pricing_catalog(
        pricing_cache,
        now=now,
        timeout=min(PRICING_FETCH_TIMEOUT, timeout),
    )
    try:
        history = collect_usage_history(
            (codex_home or default_codex_home()).expanduser(),
            resolved_usage_cache,
            now=datetime.now().astimezone(),
            days=history_days,
            pricing_catalog=pricing_catalog,
        )
    except (OSError, RuntimeError, ValueError, UsageError) as error:
        error_console.print(f"[yellow]本地 Token 统计不可用：[/]{error}")
    use_image = image_output if image_output is not None else supports_image_output()
    if save_svg is not None:
        try:
            save_svg.write_text(
                render_usage_svg(buckets, now, history=history, verbose=verbose),
                encoding="utf-8",
            )
        except OSError as error:
            error_console.print(f"[bold red]错误：[/]无法保存 SVG：{error}")
            raise typer.Exit(1) from error
    if json_output:
        print(
            json.dumps(
                _json_report(buckets, now, history), ensure_ascii=False, indent=2
            )
        )
    elif use_image:
        try:
            columns = (
                image_width if image_width is not None else default_image_columns()
            )
            render_usage_image(
                buckets,
                now,
                history=history,
                columns=columns,
                verbose=verbose,
            )
        except (UsageError, OSError, RuntimeError, ValueError) as error:
            if image_output is True:
                error_console.print(f"[bold red]错误：[/]无法展示图片：{error}")
                raise typer.Exit(1) from error
            error_console.print(f"[yellow]图片模式不可用，已回退到文本：[/]{error}")
            render_usage(buckets, now, history=history, verbose=verbose)
    else:
        render_usage(buckets, now, history=history, verbose=verbose)


if __name__ == "__main__":
    app()
