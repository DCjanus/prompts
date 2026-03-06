#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pydantic>=2.12.5",
#     "rich>=14.3.3",
#     "typer>=0.24.1",
# ]
# ///

"""读取 Codex session/thread 的只读 CLI。"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import json
import re
import select
import subprocess
import sys
import threading
from time import monotonic
from typing import Annotated, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from rich.console import Console
import typer


def to_camel(value: str) -> str:
    """将 snake_case 字段名转换为 camelCase。"""

    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class AppModel(BaseModel):
    """协议模型基类。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )


class ClientInfo(AppModel):
    """初始化时声明的客户端信息。"""

    name: str
    title: str | None = None
    version: str


class InitializeCapabilities(AppModel):
    """初始化能力声明。"""

    experimental_api: bool = False
    opt_out_notification_methods: list[str] | None = None


class InitializeParams(AppModel):
    """initialize 请求参数。"""

    client_info: ClientInfo
    capabilities: InitializeCapabilities | None = None


class InitializeResponse(AppModel):
    """initialize 响应。"""

    user_agent: str


class JsonRpcErrorPayload(AppModel):
    """JSON-RPC 错误体。"""

    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(AppModel):
    """JSON-RPC 响应。"""

    id: int | str | None = None
    result: Any | None = None
    error: JsonRpcErrorPayload | None = None


class JsonRpcNotification(AppModel):
    """JSON-RPC 通知。"""

    method: str
    params: Any | None = None


class ThreadReadParams(AppModel):
    """thread/read 请求参数。"""

    thread_id: str
    include_turns: bool


class ThreadStatus(AppModel):
    """线程运行状态。"""

    type: str
    active_flags: list[Any] | None = None


class UserInput(AppModel):
    """用户输入片段。"""

    type: str
    text: str | None = None
    url: str | None = None
    path: str | None = None
    name: str | None = None
    text_elements: list[Any] | None = None


class ThreadItem(AppModel):
    """线程 item。"""

    type: str
    id: str | None = None
    content: list[UserInput] | None = None
    text: str | None = None
    phase: str | None = None
    summary: list[str] | None = None
    command: str | None = None
    cwd: str | None = None
    process_id: str | None = None
    status: str | None = None
    aggregated_output: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    changes: list[dict[str, Any]] | None = None
    tool: str | None = None
    prompt: str | None = None
    sender_thread_id: str | None = None
    receiver_thread_ids: list[str] | None = None
    agents_states: dict[str, Any] | None = None
    query: str | None = None
    result: Any | None = None
    revised_prompt: str | None = None
    review: str | None = None


class Turn(AppModel):
    """线程 turn。"""

    id: str
    items: list[ThreadItem] = Field(default_factory=list)
    status: str
    error: Any | None = None


class Thread(AppModel):
    """线程摘要与详情。"""

    id: str
    preview: str
    ephemeral: bool
    model_provider: str
    created_at: int
    updated_at: int
    status: ThreadStatus
    path: str | None = None
    cwd: str
    cli_version: str
    source: str | dict[str, Any]
    agent_nickname: str | None = None
    agent_role: str | None = None
    git_info: dict[str, Any] | None = None
    name: str | None = None
    turns: list[Turn] = Field(default_factory=list)


class ThreadReadResponse(AppModel):
    """thread/read 响应。"""

    thread: Thread


class CodexSessionReaderError(RuntimeError):
    """skill 运行失败时的统一异常。"""


APP_SERVER_SEND_ERROR = "向 app-server 发送请求失败。"
APP_SERVER_INVALID_JSON_ERROR = "app-server 返回了非法 JSON。"
APP_SERVER_TIMEOUT_ERROR = "等待 app-server 响应超时。"


THREAD_ID_PATTERN = re.compile(
    r"^(?:urn:uuid:)?[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$"
)

AppModelType = TypeVar("AppModelType", bound=BaseModel)


def validate_model_or_raise(
    model_type: type[AppModelType], payload: Any, label: str
) -> AppModelType:
    """将 schema 校验失败统一转换为 CLI 友好的错误。"""

    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        raise CodexSessionReaderError(f"{label} 结构不合法。") from exc


class CodexAppServerClient:
    """`codex app-server` 的极薄同步 JSON-RPC client。"""

    def __init__(self, codex_bin: str = "codex", request_timeout: float = 30.0) -> None:
        """初始化 client 配置。"""

        self.codex_bin = codex_bin
        self.request_timeout = request_timeout
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._stderr_lines: deque[str] = deque(maxlen=200)
        self._stderr_thread: threading.Thread | None = None

    def __enter__(self) -> "CodexAppServerClient":
        """启动 app-server 子进程并完成握手。"""

        try:
            process = subprocess.Popen(
                [self.codex_bin, "app-server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            if isinstance(exc, FileNotFoundError):
                message = f"未找到 `{self.codex_bin}`，无法启动 `codex app-server`。"
            else:
                reason = exc.strerror or str(exc)
                message = f"无法启动 `codex app-server` ({reason})。"
            raise CodexSessionReaderError(message) from exc

        self._process = process
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name="codex-session-reader-stderr",
            daemon=True,
        )
        self._stderr_thread.start()
        try:
            self.initialize()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """关闭 app-server 子进程。"""

        if self._process is None:
            return

        if self._process.stdin:
            self._process.stdin.close()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)

    def _drain_stderr(self) -> None:
        """持续读取 stderr，避免阻塞并保留最近日志。"""

        if self._process is None or self._process.stderr is None:
            return

        for line in self._process.stderr:
            self._stderr_lines.append(line.rstrip("\n"))

    def _stderr_tail(self) -> str:
        """返回最近的 stderr 摘要。"""

        if not self._stderr_lines:
            return ""
        return "\n".join(self._stderr_lines)

    def _ensure_running(self) -> subprocess.Popen[str]:
        """确保子进程可用。"""

        if self._process is None:
            raise CodexSessionReaderError("app-server 尚未启动。")
        return self._process

    def _send_json(self, payload: dict[str, Any]) -> None:
        """发送一条 JSON-RPC 消息。"""

        process = self._ensure_running()
        if process.stdin is None:
            raise CodexSessionReaderError("app-server stdin 不可用。")

        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except OSError as exc:
            message = APP_SERVER_SEND_ERROR
            if detail := self._stderr_tail():
                message += f"\nstderr:\n{detail}"
            raise CodexSessionReaderError(message) from exc

    def _read_message(
        self, deadline: float | None = None
    ) -> JsonRpcResponse | JsonRpcNotification:
        """读取一条来自 app-server 的 JSON-RPC 消息。"""

        process = self._ensure_running()
        if process.stdout is None:
            raise CodexSessionReaderError("app-server stdout 不可用。")

        if deadline is not None:
            timeout = deadline - monotonic()
            if timeout <= 0:
                raise CodexSessionReaderError(APP_SERVER_TIMEOUT_ERROR)
            ready, _, _ = select.select([process.stdout], [], [], timeout)
            if not ready:
                raise CodexSessionReaderError(APP_SERVER_TIMEOUT_ERROR)

        line = process.stdout.readline()
        if line:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                message = f"{APP_SERVER_INVALID_JSON_ERROR} {line.strip()}"
                if detail := self._stderr_tail():
                    message += f"\nstderr:\n{detail}"
                raise CodexSessionReaderError(message) from exc
            if "method" in payload:
                return validate_model_or_raise(
                    JsonRpcNotification, payload, "app-server 通知"
                )
            return validate_model_or_raise(JsonRpcResponse, payload, "app-server 响应")

        return_code = process.poll()
        stderr_tail = self._stderr_tail()
        message = "app-server 已提前退出。"
        if return_code is not None:
            message += f" exit_code={return_code}"
        if stderr_tail:
            message += f"\nstderr:\n{stderr_tail}"
        raise CodexSessionReaderError(message)

    def initialize(self) -> InitializeResponse:
        """执行 initialize / initialized 握手。"""

        response = self.request(
            "initialize",
            InitializeParams(
                client_info=ClientInfo(
                    name="codex-session-reader",
                    title="Codex Session Reader",
                    version="0.1.0",
                ),
                capabilities=InitializeCapabilities(experimental_api=False),
            ),
        )
        self.notify("initialized", None)
        return validate_model_or_raise(InitializeResponse, response, "initialize 响应")

    def notify(self, method: str, params: Any | None) -> None:
        """发送 JSON-RPC 通知。"""

        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        self._send_json(payload)

    def request(self, method: str, params: AppModel | dict[str, Any] | None) -> Any:
        """发送 JSON-RPC 请求并等待对应响应。"""

        request_id = self._next_id
        self._next_id += 1
        deadline = monotonic() + self.request_timeout

        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            if isinstance(params, AppModel):
                payload["params"] = params.model_dump(by_alias=True, exclude_none=True)
            else:
                payload["params"] = params
        self._send_json(payload)

        while True:
            message = self._read_message(deadline=deadline)
            if isinstance(message, JsonRpcNotification):
                continue
            if message.id != request_id:
                continue
            if message.error is not None:
                detail = f"{message.error.code}: {message.error.message}"
                if message.error.data is not None:
                    detail += f"\n{json.dumps(message.error.data, ensure_ascii=False, indent=2)}"
                raise CodexSessionReaderError(detail)
            return message.result

    def read_thread(self, params: ThreadReadParams) -> ThreadReadResponse:
        """调用 `thread/read`。"""

        result = self.request("thread/read", params)
        return validate_model_or_raise(ThreadReadResponse, result, "thread/read 响应")


def unix_ts_to_text(value: int) -> str:
    """将 Unix 时间戳转成易读字符串。"""

    return datetime.fromtimestamp(value, tz=UTC).isoformat()


def format_source(source: str | dict[str, Any]) -> str:
    """格式化 session source 字段。"""

    if isinstance(source, str):
        return source
    return json.dumps(source, ensure_ascii=False, sort_keys=True)


def render_user_input(item: UserInput) -> str:
    """将单个用户输入片段转成文本。"""

    if item.type == "text":
        return item.text or ""
    if item.type in {"image", "localImage"}:
        target = item.url or item.path or ""
        return f"[{item.type}] {target}".strip()
    if item.type in {"skill", "mention"}:
        pieces = [f"[{item.type}]"]
        if item.name:
            pieces.append(item.name)
        if item.path:
            pieces.append(f"({item.path})")
        return " ".join(pieces)
    return json.dumps(
        item.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False
    )


def render_item_markdown(item: ThreadItem) -> list[str]:
    """将单个 thread item 渲染成 Markdown 片段。"""

    item_type = item.type
    if item_type == "userMessage":
        text = "\n".join(
            part
            for part in (render_user_input(entry) for entry in item.content or [])
            if part
        )
        return ["#### User", "", text or "_Empty user message._", ""]

    if item_type == "agentMessage":
        return ["#### Assistant", "", item.text or "_Empty assistant message._", ""]

    if item_type == "reasoning":
        lines = ["#### Reasoning", ""]
        if item.summary:
            lines.append("Summary:")
            for entry in item.summary:
                lines.append(f"- {entry}")
            lines.append("")
        if item.text:
            lines.append(item.text)
            lines.append("")
        return lines

    if item_type == "plan":
        return ["#### Plan", "", item.text or "_Empty plan._", ""]

    if item_type == "commandExecution":
        lines = [
            "#### Command Execution",
            "",
            f"- command: `{item.command or ''}`",
            f"- status: `{item.status or 'unknown'}`",
        ]
        if item.cwd:
            lines.append(f"- cwd: `{item.cwd}`")
        if item.exit_code is not None:
            lines.append(f"- exit_code: `{item.exit_code}`")
        if item.duration_ms is not None:
            lines.append(f"- duration_ms: `{item.duration_ms}`")
        lines.append("")
        if item.aggregated_output:
            lines.extend(["```text", item.aggregated_output.rstrip(), "```", ""])
        return lines

    if item_type == "fileChange":
        lines = ["#### File Change", ""]
        if item.changes:
            for change in item.changes:
                rendered = json.dumps(change, ensure_ascii=False, sort_keys=True)
                lines.append(f"- {rendered}")
        else:
            lines.append("_No changes payload._")
        lines.append("")
        return lines

    if item_type == "collabAgentToolCall":
        lines = [
            "#### Collaboration Tool Call",
            "",
            f"- tool: `{item.tool or ''}`",
            f"- status: `{item.status or 'unknown'}`",
        ]
        if item.sender_thread_id:
            lines.append(f"- sender_thread_id: `{item.sender_thread_id}`")
        if item.receiver_thread_ids:
            joined = ", ".join(
                f"`{thread_id}`" for thread_id in item.receiver_thread_ids
            )
            lines.append(f"- receiver_thread_ids: {joined}")
        if item.prompt:
            lines.extend(["", item.prompt, ""])
        else:
            lines.append("")
        return lines

    payload = item.model_dump(by_alias=True, exclude_none=True)
    return [
        f"#### {item_type}",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "```",
        "",
    ]


def parse_turn_slice_expr(expr: str) -> tuple[int | None, int | None]:
    """解析 0-based、接近 Python 的 turns 切片表达式。"""

    value = expr.strip()
    if not value:
        raise CodexSessionReaderError("`--turns` 不能为空。")
    if value.count(":") > 1:
        raise CodexSessionReaderError("`--turns` 暂不支持 step，只允许 `start:end`。")
    if ":" not in value:
        try:
            index = int(value)
        except ValueError as exc:
            raise CodexSessionReaderError(
                "`--turns` 只支持单个整数或 `start:end` 形式。"
            ) from exc
        return index, index + 1
    raw_start, raw_end = value.split(":", 1)
    try:
        start = int(raw_start) if raw_start else None
        end = int(raw_end) if raw_end else None
    except ValueError as exc:
        raise CodexSessionReaderError(
            "`--turns` 只支持单个整数或 `start:end` 形式。"
        ) from exc
    return start, end


def resolve_slice_index(index: int | None, total_turns: int, *, default: int) -> int:
    """将切片边界归一化为 Python 风格的绝对下标。"""

    if index is None:
        return default
    if index < 0:
        return max(total_turns + index, 0)
    return min(index, total_turns)


def select_turns_by_expr(
    turns: list[Turn],
    include_turns: bool,
    turns_expr: str | None,
) -> tuple[list[Turn], int, int]:
    """根据 `--turns` 表达式选择要输出的 turns。"""

    if not include_turns:
        return [], 0, 0

    total_turns = len(turns)
    if total_turns == 0:
        return [], 0, 0

    if turns_expr is None:
        return turns, 0, total_turns

    raw_start, raw_end = parse_turn_slice_expr(turns_expr)
    start_index = resolve_slice_index(raw_start, total_turns, default=0)
    end_index = resolve_slice_index(raw_end, total_turns, default=total_turns)
    if end_index < start_index:
        return [], start_index, end_index
    selected = turns[start_index:end_index]
    return selected, start_index, end_index


def render_thread_markdown(
    result: ThreadReadResponse,
    include_turns: bool,
    turns_expr: str | None,
) -> str:
    """将 thread/read 结果渲染成 Markdown。"""

    thread = result.thread
    lines = ["# Codex Thread", ""]
    title = thread.name or thread.preview or "(untitled)"
    lines.append(f"## {title}")
    lines.append("")
    lines.append(f"- id: `{thread.id}`")
    lines.append(f"- status: `{thread.status.type}`")
    lines.append(f"- provider: `{thread.model_provider}`")
    lines.append(f"- source: `{format_source(thread.source)}`")
    lines.append(f"- created_at: `{unix_ts_to_text(thread.created_at)}`")
    lines.append(f"- updated_at: `{unix_ts_to_text(thread.updated_at)}`")
    lines.append(f"- cwd: `{thread.cwd}`")
    lines.append(f"- ephemeral: `{thread.ephemeral}`")
    if thread.path:
        lines.append(f"- path: `{thread.path}`")
    if thread.agent_role:
        lines.append(f"- agent_role: `{thread.agent_role}`")
    if thread.agent_nickname:
        lines.append(f"- agent_nickname: `{thread.agent_nickname}`")
    lines.append("")
    if thread.preview:
        lines.extend(["## Preview", "", thread.preview, ""])

    selected_turns, selected_start, selected_end = select_turns_by_expr(
        thread.turns,
        include_turns=include_turns,
        turns_expr=turns_expr,
    )

    if not include_turns:
        return "\n".join(lines).rstrip() + "\n"

    lines.append("## Turns")
    lines.append("")
    if not selected_turns:
        lines.append("_No turns loaded._")
        return "\n".join(lines).rstrip() + "\n"
    if len(selected_turns) != len(thread.turns):
        lines.append(
            f"_Showing turns [{selected_start}:{selected_end}] of {len(thread.turns)}._"
        )
        lines.append("")

    for index, turn in enumerate(selected_turns, start=selected_start):
        lines.append(f"### Turn {index}")
        lines.append("")
        lines.append(f"- id: `{turn.id}`")
        lines.append(f"- status: `{turn.status}`")
        lines.append("")
        for item in turn.items:
            lines.extend(render_item_markdown(item))

    return "\n".join(lines).rstrip() + "\n"


def emit_output(payload: str) -> None:
    """统一输出结果。"""

    sys.stdout.write(payload)


def validate_thread_id(thread_id: str) -> str:
    """在本地做一层 thread id 格式校验。"""

    value = thread_id.strip()
    if not value:
        raise CodexSessionReaderError("thread id 不能为空。")
    if not THREAD_ID_PATTERN.fullmatch(value):
        raise CodexSessionReaderError(
            "thread id 格式不合法；只允许 UUID 或 `urn:uuid:` 前缀的 UUID。"
        )
    return value


app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main_callback() -> None:
    """读取 Codex session/thread 的 CLI。"""


@app.command("read")
def read_thread_command(
    thread_id: Annotated[str, typer.Argument(help="要读取的 thread id。")],
    include_turns: Annotated[
        bool,
        typer.Option(
            "--include-turns/--preview-only", help="是否展开 turns 与 items。"
        ),
    ] = True,
    format_name: Annotated[
        Literal["markdown", "json"],
        typer.Option("--format", help="输出格式。"),
    ] = "markdown",
    turns_expr: Annotated[
        str | None,
        typer.Option(
            "--turns",
            help="0-based turns 切片，如 `:5`、`-5:`、`10:-1`、`13:15`、`13`。",
        ),
    ] = None,
    codex_bin: Annotated[str, typer.Option(help="Codex 可执行文件路径。")] = "codex",
) -> None:
    """读取单个 Codex thread。"""

    normalized_thread_id = validate_thread_id(thread_id)

    with CodexAppServerClient(codex_bin=codex_bin) as client:
        result = client.read_thread(
            ThreadReadParams(
                thread_id=normalized_thread_id,
                include_turns=include_turns,
            )
        )

    selected_turns, selected_start, selected_end = select_turns_by_expr(
        result.thread.turns,
        include_turns=include_turns,
        turns_expr=turns_expr,
    )

    effective_result = result.model_copy(deep=True)
    if include_turns:
        effective_result.thread.turns = selected_turns
    else:
        effective_result.thread.turns = []

    if format_name == "json":
        is_truncated = include_turns and (
            selected_start != 0 or selected_end != len(result.thread.turns)
        )
        payload = (
            json.dumps(
                {
                    **effective_result.model_dump(by_alias=True),
                    "truncated": (
                        {
                            "totalTurnCount": len(result.thread.turns),
                            "includedTurnCount": len(selected_turns),
                            "startTurn": selected_start,
                            "endTurn": selected_end,
                            "turns": turns_expr,
                        }
                        if is_truncated
                        else None
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    else:
        payload = render_thread_markdown(
            result,
            include_turns=include_turns,
            turns_expr=turns_expr,
        )
    emit_output(payload)


def main() -> None:
    """CLI 主入口。"""

    console = Console(stderr=True)
    try:
        app()
    except CodexSessionReaderError as exc:
        console.print(f"[red]error:[/red] {exc}", highlight=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
