#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "kittytgp>=0.0.2",
#     "resvg-py>=0.4.0",
#     "rich>=15.0.0",
#     "typer>=0.27.1",
# ]
# ///

"""通过本机 Codex 登录态展示 ChatGPT 订阅的 Codex 额度。"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html import escape
from math import ceil
from pathlib import Path
from typing import Annotated, Any, TextIO

import typer
from kittytgp import render_png
from resvg_py import svg_to_bytes
from rich.console import Console
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

APP_NAME = "chatgpt-usage"
APP_VERSION = "0.1.0"
SVG_WIDTH = 1440
IMAGE_SCALE = 2
DEFAULT_IMAGE_WIDTH_RATIO = 1.0
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


def calculate_progress(window: UsageWindow, now: datetime) -> WindowProgress:
    """计算额度剩余、时间剩余及两者差值。"""
    quota_remaining = max(0.0, min(100.0, 100.0 - window.used_percent))
    if window.duration_minutes is None or window.resets_at is None:
        return WindowProgress(quota_remaining, None, None, None)

    remaining_seconds = max(0.0, window.resets_at - now.timestamp())
    duration_seconds = window.duration_minutes * 60
    time_remaining = max(0.0, min(100.0, remaining_seconds / duration_seconds * 100))
    return WindowProgress(
        quota_remaining_percent=quota_remaining,
        time_remaining_percent=time_remaining,
        pace_delta=quota_remaining - time_remaining,
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


def render_usage(buckets: list[LimitBucket], now: datetime, *, verbose: bool) -> None:
    """用 Rich 渲染订阅与额度进度。"""
    for bucket in buckets:
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


def render_usage_svg(
    buckets: list[LimitBucket], now: datetime, *, verbose: bool
) -> str:
    """把额度看板渲染为共享刻度对比 SVG。"""
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
    height = (
        header_height
        + sum(row_heights)
        + card_gap * max(0, len(bucket_rows) - 1)
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
    columns: int | None,
    verbose: bool,
) -> None:
    """生成 SVG、栅格化，并通过 Kitty 协议展示。"""
    svg = render_usage_svg(buckets, now, verbose=verbose)
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


def _json_report(buckets: list[LimitBucket], now: datetime) -> dict[str, Any]:
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
    return {"fetched_at": now.isoformat(), "buckets": rows}


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
    """显示当前 ChatGPT 登录态对应的 Codex 额度与时间进度。"""
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
    use_image = image_output if image_output is not None else supports_image_output()
    if save_svg is not None:
        try:
            save_svg.write_text(
                render_usage_svg(buckets, now, verbose=verbose), encoding="utf-8"
            )
        except OSError as error:
            error_console.print(f"[bold red]错误：[/]无法保存 SVG：{error}")
            raise typer.Exit(1) from error
    if json_output:
        print(json.dumps(_json_report(buckets, now), ensure_ascii=False, indent=2))
    elif use_image:
        try:
            columns = (
                image_width if image_width is not None else default_image_columns()
            )
            render_usage_image(buckets, now, columns=columns, verbose=verbose)
        except (UsageError, OSError, RuntimeError, ValueError) as error:
            if image_output is True:
                error_console.print(f"[bold red]错误：[/]无法展示图片：{error}")
                raise typer.Exit(1) from error
            error_console.print(f"[yellow]图片模式不可用，已回退到文本：[/]{error}")
            render_usage(buckets, now, verbose=verbose)
    else:
        render_usage(buckets, now, verbose=verbose)


if __name__ == "__main__":
    app()
