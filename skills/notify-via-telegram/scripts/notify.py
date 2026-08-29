#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx2>=2.12.0",
#     "pydantic>=2.13.5",
#     "rich>=15.0.0",
#     "tomli-w>=1.2.0",
#     "typer>=0.27.2",
# ]
# ///

from __future__ import annotations

import json
import os
import sys
import tempfile
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

import httpx2
import tomli_w
import tomllib
import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from rich.console import Console
from rich.table import Table

CONFIG_ENV = "NOTIFY_VIA_TELEGRAM_CONFIG"
DEFAULT_TIMEOUT_SECONDS = 10.0
TELEGRAM_API_BASE = "https://api.telegram.org"

app = typer.Typer(no_args_is_help=True, add_completion=False)
config_app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="管理本地配置。"
)
app.add_typer(config_app, name="config")
console = Console()
error_console = Console(stderr=True)


class ConfigKey(str, Enum):
    """CLI 可管理的配置项。"""

    bot_token = "bot-token"
    chat_id = "chat-id"


class NotificationStatus(str, Enum):
    """长任务通知的结果状态。"""

    success = "success"
    failed = "failed"
    action_required = "action-required"


class TelegramConfig(BaseModel):
    """本地 Telegram 配置。"""

    model_config = ConfigDict(extra="forbid")

    bot_token: str | None = None
    chat_id: str | None = None


class AppState(BaseModel):
    """CLI 全局状态。"""

    config_path: Path
    json_output: bool


class Notification(BaseModel):
    """结构化长任务通知。"""

    status: NotificationStatus
    title: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=600)
    verification: str | None = Field(default=None, min_length=1, max_length=200)
    action: str | None = Field(default=None, min_length=1, max_length=200)
    context: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator(
        "title", "summary", "verification", "action", "context", mode="before"
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        """移除字段首尾空白，保持通知紧凑。"""

        return value.strip() if isinstance(value, str) else value


STATUS_PRESENTATION = {
    NotificationStatus.success: ("✅", "已完成"),
    NotificationStatus.failed: ("❌", "未完成"),
    NotificationStatus.action_required: ("⚠️", "等待处理"),
}


def notification_from_options(
    *,
    status: NotificationStatus,
    title: str,
    summary: str,
    verification: str | None,
    action: str | None,
    context: str | None,
) -> Notification:
    """校验 CLI 提供的结构化通知字段。"""

    try:
        return Notification(
            status=status,
            title=title,
            summary=summary,
            verification=verification,
            action=action,
            context=context,
        )
    except ValidationError as exc:
        details = ", ".join(
            f"{error['loc'][-1]}: {error['msg']}"
            for error in exc.errors(include_input=False)
        )
        abort(f"通知内容无效：{details}")


def render_notification_blocks(notification: Notification) -> list[dict[str, Any]]:
    """生成 Telegram Rich Message 的显式内容块。"""

    icon, status_label = STATUS_PRESENTATION[notification.status]
    blocks: list[dict[str, Any]] = [
        {
            "type": "heading",
            "text": notification.title,
            "size": 4,
        },
        {
            "type": "blockquote",
            "blocks": [{"type": "paragraph", "text": notification.summary}],
        },
    ]

    if notification.action:
        blocks.append(
            {
                "type": "paragraph",
                "text": [
                    {"type": "marked", "text": "需要你处理"},
                    f"：{notification.action}",
                ],
            }
        )

    footer: list[Any] = [f"{icon} {status_label}"]
    if notification.verification:
        footer.extend([" · ", notification.verification])
    if notification.context:
        footer.extend([" · ", notification.context])
    blocks.append({"type": "footer", "text": footer})
    return blocks


def render_notification_plain(notification: Notification) -> str:
    """渲染终端预览使用的纯文本通知。"""

    icon, status_label = STATUS_PRESENTATION[notification.status]
    lines = [
        notification.title,
        "",
        f"> {notification.summary}",
    ]
    if notification.action:
        lines.extend(["", f"需要你处理：{notification.action}"])

    footer = [f"{icon} {status_label}"]
    if notification.verification:
        footer.append(notification.verification)
    if notification.context:
        footer.append(notification.context)
    lines.extend(["", " · ".join(footer)])
    return "\n".join(lines)


def default_config_path() -> Path:
    """返回默认配置文件路径。"""

    overridden = os.environ.get(CONFIG_ENV)
    if overridden:
        return Path(overridden).expanduser()

    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "notify-via-telegram" / "config.toml"


def state_from_context(ctx: typer.Context) -> AppState:
    """从 Typer 上下文读取全局状态。"""

    if not isinstance(ctx.obj, AppState):
        raise TypeError("CLI state is not initialized")
    return ctx.obj


def emit(state: AppState, payload: dict[str, Any], message: str) -> None:
    """按调用方需要输出 JSON 或人类可读文本。"""

    if state.json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False))
    else:
        console.print(message)


def abort(message: str) -> None:
    """输出安全错误并以非零状态退出。"""

    error_console.print(f"[red]错误：[/red]{message}")
    raise typer.Exit(1)


def load_config(path: Path, *, allow_missing: bool = False) -> TelegramConfig:
    """读取并校验本地配置。"""

    if not path.exists():
        if allow_missing:
            return TelegramConfig()
        abort(f"配置文件不存在：{path}；请先运行 config set。")

    try:
        with path.open("rb") as config_file:
            raw_config = tomllib.load(config_file)
        return TelegramConfig.model_validate(raw_config)
    except (OSError, tomllib.TOMLDecodeError):
        abort(f"无法读取配置文件：{path}")
    except ValidationError:
        abort("配置内容无效；请检查是否只包含 bot_token 和 chat_id。")


def write_config(path: Path, config: TelegramConfig) -> None:
    """以仅当前用户可读写的权限原子更新配置。"""

    temp_path: Path | None = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        content = tomli_w.dumps(config.model_dump(exclude_none=True)).encode()
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            os.chmod(temp_path, 0o600)
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    except OSError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        abort(f"无法写入配置文件：{path}")


def complete_config(path: Path) -> TelegramConfig:
    """读取可用于 Telegram API 的完整配置。"""

    config = load_config(path)
    missing = [
        name
        for name, value in (
            ("bot-token", config.bot_token),
            ("chat-id", config.chat_id),
        )
        if not value
    ]
    if missing:
        abort(f"缺少配置项：{', '.join(missing)}")
    return config


def telegram_call(
    config: TelegramConfig, method: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """执行一次 Telegram Bot API 请求且不泄露 Token。"""

    url = f"{TELEGRAM_API_BASE}/bot{config.bot_token}/{method}"
    try:
        with httpx2.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            response = client.post(url, json=payload or {})
    except httpx2.RequestError as exc:
        abort(f"Telegram 请求失败（{type(exc).__name__}）。")

    try:
        response_data = response.json()
    except ValueError:
        abort(f"Telegram 返回了无法解析的响应（HTTP {response.status_code}）。")

    if not isinstance(response_data, dict):
        abort(f"Telegram 返回了结构异常的响应（HTTP {response.status_code}）。")

    if response.status_code >= 400 or not response_data.get("ok"):
        description = response_data.get("description")
        detail = description if isinstance(description, str) else "未知 API 错误"
        abort(f"Telegram API 拒绝请求（HTTP {response.status_code}）：{detail}")

    result = response_data.get("result")
    if not isinstance(result, dict):
        abort("Telegram 返回的数据缺少 result 对象。")
    return result


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", help=f"配置文件路径；也可使用 {CONFIG_ENV}。"),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="输出适合 Agent 解析的 JSON。")
    ] = False,
) -> None:
    """通过本地安全配置发送 Telegram 通知。"""

    ctx.obj = AppState(
        config_path=(config.expanduser() if config else default_config_path()),
        json_output=json_output,
    )


@app.command("send")
def send_message(
    ctx: typer.Context,
    status: Annotated[
        NotificationStatus, typer.Option("--status", help="长任务的最终状态。")
    ],
    title: Annotated[str, typer.Option("--title", help="用于识别任务的简短标题。")],
    summary: Annotated[str, typer.Option("--summary", help="任务结果的一句话摘要。")],
    verification: Annotated[
        str | None, typer.Option("--verification", help="可选的验证结果。")
    ] = None,
    action: Annotated[
        str | None, typer.Option("--action", help="可选的下一步或所需操作。")
    ] = None,
    context: Annotated[
        str | None, typer.Option("--context", help="可选的仓库或任务上下文。")
    ] = None,
) -> None:
    """发送一条结构化长任务结果通知。"""

    state = state_from_context(ctx)
    notification = notification_from_options(
        status=status,
        title=title,
        summary=summary,
        verification=verification,
        action=action,
        context=context,
    )
    config = complete_config(state.config_path)
    result = telegram_call(
        config,
        "sendRichMessage",
        {
            "chat_id": config.chat_id,
            "rich_message": {
                "blocks": render_notification_blocks(notification),
            },
        },
    )
    emit(
        state,
        {
            "ok": True,
            "status": notification.status.value,
            "message_id": result.get("message_id"),
        },
        f"[green]通知已发送[/green]（message_id={result.get('message_id')}）。",
    )


@app.command("preview")
def preview_message(
    ctx: typer.Context,
    status: Annotated[
        NotificationStatus, typer.Option("--status", help="长任务的最终状态。")
    ],
    title: Annotated[str, typer.Option("--title", help="用于识别任务的简短标题。")],
    summary: Annotated[str, typer.Option("--summary", help="任务结果的一句话摘要。")],
    verification: Annotated[
        str | None, typer.Option("--verification", help="可选的验证结果。")
    ] = None,
    action: Annotated[
        str | None, typer.Option("--action", help="可选的下一步或所需操作。")
    ] = None,
    context: Annotated[
        str | None, typer.Option("--context", help="可选的仓库或任务上下文。")
    ] = None,
) -> None:
    """在本地预览通知，不读取配置或访问 Telegram。"""

    state = state_from_context(ctx)
    notification = notification_from_options(
        status=status,
        title=title,
        summary=summary,
        verification=verification,
        action=action,
        context=context,
    )
    if state.json_output:
        emit(
            state,
            {
                "status": notification.status.value,
                "rich_message": {
                    "blocks": render_notification_blocks(notification),
                },
            },
            "",
        )
        return
    console.print(render_notification_plain(notification), markup=False)


@config_app.command("path")
def show_config_path(ctx: typer.Context) -> None:
    """显示当前配置文件路径。"""

    state = state_from_context(ctx)
    emit(
        state,
        {"config_path": str(state.config_path)},
        str(state.config_path),
    )


@config_app.command("show")
def show_config(ctx: typer.Context) -> None:
    """显示配置，Bot Token 始终脱敏。"""

    state = state_from_context(ctx)
    config = load_config(state.config_path, allow_missing=True)
    payload = {
        "config_path": str(state.config_path),
        "bot_token": "configured" if config.bot_token else None,
        "chat_id": config.chat_id,
    }
    if state.json_output:
        emit(state, payload, "")
        return

    table = Table(title="Telegram 通知配置")
    table.add_column("配置项")
    table.add_column("值")
    table.add_row("config_path", str(state.config_path))
    table.add_row("bot_token", "<已配置>" if config.bot_token else "<未配置>")
    table.add_row("chat_id", config.chat_id or "<未配置>")
    console.print(table)


@config_app.command("get")
def get_config(
    ctx: typer.Context,
    key: Annotated[ConfigKey, typer.Argument(help="要查看的配置项。")],
) -> None:
    """查看单个配置项，Bot Token 始终脱敏。"""

    state = state_from_context(ctx)
    config = load_config(state.config_path, allow_missing=True)
    if key is ConfigKey.bot_token:
        value = "configured" if config.bot_token else None
    else:
        value = config.chat_id
    emit(state, {"key": key.value, "value": value}, str(value or "<未配置>"))


@config_app.command("set", context_settings={"ignore_unknown_options": True})
def set_config(
    ctx: typer.Context,
    key: Annotated[ConfigKey, typer.Argument(help="要设置的配置项。")],
    value: Annotated[
        str | None,
        typer.Argument(help="配置值；设置 bot-token 时必须省略并交互输入。"),
    ] = None,
) -> None:
    """设置配置项；Bot Token 只接受隐藏的交互式输入。"""

    state = state_from_context(ctx)
    config = load_config(state.config_path, allow_missing=True)

    if key is ConfigKey.bot_token:
        if value is not None:
            abort("bot-token 不接受命令行参数；请省略值并通过隐藏提示输入。")
        if not sys.stdin.isatty():
            abort("设置 bot-token 需要交互式终端。")
        new_value = typer.prompt("Bot Token", hide_input=True).strip()
        if not new_value:
            abort("bot-token 不能为空。")
        config.bot_token = new_value
    else:
        new_value = value.strip() if value is not None else ""
        if not new_value:
            abort("chat-id 不能为空。")
        config.chat_id = new_value

    write_config(state.config_path, config)
    emit(
        state,
        {"ok": True, "key": key.value, "config_path": str(state.config_path)},
        f"[green]已更新[/green] {key.value}。",
    )


@config_app.command("unset")
def unset_config(
    ctx: typer.Context,
    key: Annotated[ConfigKey, typer.Argument(help="要删除的配置项。")],
) -> None:
    """删除一个配置项。"""

    state = state_from_context(ctx)
    config = load_config(state.config_path, allow_missing=True)
    if key is ConfigKey.bot_token:
        config.bot_token = None
    else:
        config.chat_id = None
    write_config(state.config_path, config)
    emit(
        state,
        {"ok": True, "key": key.value, "config_path": str(state.config_path)},
        f"[green]已删除[/green] {key.value}。",
    )


@config_app.command("check")
def check_config(ctx: typer.Context) -> None:
    """校验 Bot 与目标会话，但不发送消息。"""

    state = state_from_context(ctx)
    config = complete_config(state.config_path)
    bot = telegram_call(config, "getMe")
    chat = telegram_call(config, "getChat", {"chat_id": config.chat_id})
    payload = {
        "ok": True,
        "bot_username": bot.get("username"),
        "chat_id": str(chat.get("id")),
        "chat_type": chat.get("type"),
        "chat_title": chat.get("title") or chat.get("username"),
    }
    emit(
        state,
        payload,
        "[green]配置有效[/green]："
        f"@{bot.get('username')} -> {payload['chat_title'] or payload['chat_id']}",
    )


if __name__ == "__main__":
    app()
