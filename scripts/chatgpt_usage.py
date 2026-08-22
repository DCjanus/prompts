#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "rich>=15.0.0",
#     "typer>=0.27.1",
# ]
# ///

"""通过本机 Codex 登录态展示 ChatGPT 订阅的 Codex 额度。"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, TextIO

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

APP_NAME = "chatgpt-usage"
APP_VERSION = "0.1.0"
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
) -> None:
    """显示当前 ChatGPT 登录态对应的 Codex 额度与时间进度。"""
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
    if json_output:
        print(json.dumps(_json_report(buckets, now), ensure_ascii=False, indent=2))
    else:
        render_usage(buckets, now, verbose=verbose)


if __name__ == "__main__":
    app()
