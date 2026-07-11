#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pydantic>=2.13.4",
#     "rich>=15.0.0",
#     "typer>=0.26.8",
#     "websockets>=16.1",
# ]
# ///

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

MIN_PORT_OFFSET = 1024
TOKEN_CHARS = "0123456789abcdefghijklmnopqrstuvwxyz"
BASE32_CHARS = "0123456789abcdefghijklmnopqrstuv"
DEFAULT_SOCKET_NAME = "codex-tampermonkey.sock"

app = typer.Typer(
    no_args_is_help=True,
    help="通过 Tampermonkey Editors 管理本机 Tampermonkey userscript。",
)
console = Console(stderr=True)
stdout = Console()


class ScriptMeta(BaseModel):
    """Tampermonkey 脚本列表项。"""

    namespace: str = ""
    name: str = ""
    path: str = ""
    requires: list[str] = []
    storage: str | None = None


def default_socket_path() -> Path:
    """返回 XDG 规范下的默认 Unix Domain Socket 路径。"""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / DEFAULT_SOCKET_NAME

    cache_home = os.environ.get("XDG_CACHE_HOME")
    cache_dir = Path(cache_home) if cache_home else Path.home() / ".cache"
    return cache_dir / "codex" / DEFAULT_SOCKET_NAME


def encode_base32(value: int) -> str:
    """按 JS Number.toString(32) 的字符表编码端口。"""
    if value < 0:
        raise ValueError("port must be greater than MIN_PORT_OFFSET")
    if value == 0:
        return "0"

    digits: list[str] = []
    while value:
        value, remainder = divmod(value, 32)
        digits.append(BASE32_CHARS[remainder])
    return "".join(reversed(digits))


def as_json(data: Any) -> str:
    """稳定输出 JSON。"""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


class TampermonkeyBridge:
    """Tampermonkey Editors WebSocket 桥接。"""

    def __init__(self, host: str = "localhost", timeout: float = 30.0) -> None:
        self.host = host
        self.timeout = timeout
        self.auth = random.choice(TOKEN_CHARS)
        self.auth_echo = random.choice(TOKEN_CHARS)
        self.port = 0
        self.code = ""
        self.server: Server | None = None
        self.connection: ServerConnection | None = None
        self.connected = asyncio.Event()
        self.pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.next_message_id = 1
        self.ping_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> TampermonkeyBridge:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def start(self) -> None:
        """启动本地 WebSocket server 并生成 Tampermonkey Editors 连接码。"""
        self.server = await serve(self.handle_connection, self.host, 0)
        socket = self.server.sockets[0]
        self.port = int(socket.getsockname()[1])
        self.code = (
            f"{encode_base32(self.port - MIN_PORT_OFFSET)}{self.auth}{self.auth_echo}"
        )

    async def close(self) -> None:
        """关闭连接和 WebSocket server。"""
        if self.ping_task:
            self.ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.ping_task

        if self.connection:
            await self.connection.close()
            self.connection = None

        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def handle_connection(self, websocket: ServerConnection) -> None:
        """处理 Tampermonkey Editors 发起的连接。"""
        try:
            auth_data = self.parse_message(await websocket.recv())
            if auth_data.get("method") != "auth" or auth_data.get("token") != self.auth:
                await websocket.close(3003, "Auth failed")
                return

            await websocket.send(
                json.dumps({"method": "auth", "token": self.auth_echo})
            )
            ok_data = self.parse_message(await websocket.recv())
            if ok_data.get("method") != "authOK":
                await websocket.close(3003, "Missing authOK")
                return

            if self.connection and self.connection is not websocket:
                await self.connection.close(4009, "Connection superseded")

            self.connection = websocket
            self.connected.set()
            self.ping_task = asyncio.create_task(self.ping_loop())

            async for raw_message in websocket:
                data = self.parse_message(raw_message)
                if data.get("method") == "pong":
                    continue

                message_id = str(data.get("id") or data.get("messageId") or "")
                response = data.get("response")
                future = self.pending.pop(message_id, None)
                if future and not future.done():
                    future.set_result(response if isinstance(response, dict) else data)
        except ConnectionClosed:
            pass
        except Exception as exc:
            console.print(f"[red]连接处理失败：{exc}[/red]")
        finally:
            if self.connection is websocket:
                self.connection = None
                self.connected.clear()

    async def ping_loop(self) -> None:
        """定期 ping，保持扩展连接。"""
        while self.connection:
            await asyncio.sleep(15)
            if self.connection:
                await self.connection.send(json.dumps({"method": "ping"}))

    def parse_message(self, raw_message: str | bytes) -> dict[str, Any]:
        """解析 WebSocket JSON 消息。"""
        text = raw_message.decode() if isinstance(raw_message, bytes) else raw_message
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("message must be a JSON object")
        return parsed

    async def command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 Tampermonkey command 并等待响应。"""
        if not self.connection:
            raise RuntimeError("Tampermonkey Editors is not connected")

        message_id = str(self.next_message_id)
        self.next_message_id += 1
        payload = {**payload, "messageId": message_id}

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending[message_id] = future

        await self.connection.send(json.dumps(payload, ensure_ascii=False))
        return await asyncio.wait_for(future, timeout=self.timeout)


class SocketServer:
    """给本地 CLI 子命令调用的 Unix Domain Socket 控制面。"""

    def __init__(self, bridge: TampermonkeyBridge, socket_path: Path) -> None:
        self.bridge = bridge
        self.socket_path = socket_path
        self.server: asyncio.Server | None = None
        self.stop_event = asyncio.Event()

    async def start(self) -> None:
        """启动 UDS 控制服务。"""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.server = await asyncio.start_unix_server(
            self.handle_client, path=self.socket_path
        )
        self.socket_path.chmod(0o600)

    async def close(self) -> None:
        """关闭 UDS 控制服务。"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        with contextlib.suppress(FileNotFoundError):
            self.socket_path.unlink()

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """处理一个 JSON line 请求。"""
        try:
            line = await reader.readline()
            request_data = json.loads(line.decode() or "{}")
            if not isinstance(request_data, dict):
                raise ValueError("request must be a JSON object")
            response = await self.route(request_data)
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}

        writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def route(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """路由本地控制请求。"""
        action = request_data.get("action")
        if action == "status":
            return {
                "ok": True,
                "connected": self.bridge.connected.is_set(),
                "connectionCode": self.bridge.code,
                "socketPath": str(self.socket_path),
                "webSocketPort": self.bridge.port,
            }

        if action == "shutdown":
            self.stop_event.set()
            return {"ok": True}

        if action == "command":
            if not self.bridge.connection:
                return {
                    "ok": False,
                    "error": "Tampermonkey Editors is not connected. Start serve and enter its connection code first.",
                }
            payload = request_data.get("payload")
            if not isinstance(payload, dict):
                return {"ok": False, "error": "payload must be a JSON object"}
            return {"ok": True, "response": await self.bridge.command(payload)}

        return {"ok": False, "error": f"unknown action: {action}"}


async def socket_request(
    socket_path: Path,
    request_data: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    """向 serve 进程发送一个 JSON line 请求。"""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(path=socket_path),
            timeout=timeout,
        )
    except (FileNotFoundError, ConnectionRefusedError, TimeoutError) as exc:
        raise RuntimeError(
            f"无法连接 Tampermonkey serve socket：{socket_path}"
        ) from exc

    writer.write((json.dumps(request_data, ensure_ascii=False) + "\n").encode())
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    writer.close()
    await writer.wait_closed()
    response = json.loads(line.decode() or "{}")
    if not isinstance(response, dict):
        raise RuntimeError("serve returned a non-object response")
    return response


def call_socket(
    socket_path: Path,
    request_data: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    """同步调用 UDS 控制面。"""
    return asyncio.run(socket_request(socket_path, request_data, timeout=timeout))


def command_via_socket(
    payload: dict[str, Any],
    *,
    socket_path: Path,
    timeout: float,
) -> dict[str, Any]:
    """通过 serve 执行 Tampermonkey command。"""
    response = call_socket(
        socket_path,
        {"action": "command", "payload": payload},
        timeout=timeout,
    )
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error") or response))
    command_response = response.get("response")
    if not isinstance(command_response, dict):
        raise RuntimeError("serve returned an invalid command response")
    return command_response


def print_connection_help(code: str, socket_path: Path) -> None:
    """输出连接码和 socket 提示。"""
    console.print(
        f"[bold]Tampermonkey Editors connection code:[/bold] [cyan]{code}[/cyan]"
    )
    console.print(f"Socket: {socket_path}")
    console.print(
        "打开 Tampermonkey Editors 扩展，输入上面的 code；后续命令会复用这个 serve 连接。"
    )


async def run_serve(
    *,
    ws_host: str,
    socket_path: Path,
    timeout: float,
) -> None:
    """启动常驻桥接和 UDS 控制服务。"""
    async with TampermonkeyBridge(host=ws_host, timeout=timeout) as bridge:
        control = SocketServer(bridge, socket_path)
        await control.start()
        try:
            print_connection_help(bridge.code, socket_path)
            console.print("保持该进程运行；按 Ctrl-C 退出。")
            await control.stop_event.wait()
        finally:
            await control.close()


def build_filter(
    pattern: str | None,
    include_pattern: list[str] | None,
) -> dict[str, Any] | None:
    """构造 list 命令的过滤条件。"""
    filter_data: dict[str, Any] = {}
    if pattern:
        filter_data["content"] = {"pattern": pattern}
    if include_pattern:
        filter_data["location"] = {"includePattern": include_pattern}
    return filter_data or None


def print_response(response: dict[str, Any], json_output: bool) -> None:
    """输出通用响应。"""
    if json_output:
        stdout.print(as_json(response))
        return

    error = response.get("error")
    if error:
        console.print(f"[red]{as_json(error)}[/red]")
        raise typer.Exit(1)

    stdout.print(as_json(response))


def socket_option_help() -> str:
    """返回 socket 参数说明。"""
    return "serve 的 Unix Domain Socket 路径；默认使用 XDG runtime/cache 路径。"


@app.command("serve")
def serve_command(
    ws_host: Annotated[
        str, typer.Option(help="Tampermonkey Editors WebSocket 监听 host。")
    ] = "localhost",
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", help=socket_option_help()),
    ] = None,
    timeout: Annotated[
        float, typer.Option(help="Tampermonkey 命令响应超时秒数。")
    ] = 60.0,
) -> None:
    """启动常驻桥接进程，只需要输入一次 connection code。"""
    try:
        asyncio.run(
            run_serve(
                ws_host=ws_host,
                socket_path=socket_path or default_socket_path(),
                timeout=timeout,
            ),
        )
    except KeyboardInterrupt:
        console.print("已退出 Tampermonkey serve。")


@app.command("status")
def status_command(
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", help=socket_option_help()),
    ] = None,
    timeout: Annotated[float, typer.Option(help="UDS 请求超时秒数。")] = 5.0,
    json_output: Annotated[
        bool, typer.Option("--json", help="输出原始 JSON。")
    ] = False,
) -> None:
    """查看 serve 连接状态。"""
    try:
        response = call_socket(
            socket_path or default_socket_path(), {"action": "status"}, timeout=timeout
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if json_output:
        stdout.print(as_json(response))
    else:
        stdout.print(as_json(response))


@app.command("shutdown")
def shutdown_command(
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", help=socket_option_help()),
    ] = None,
    timeout: Annotated[float, typer.Option(help="UDS 请求超时秒数。")] = 5.0,
    json_output: Annotated[
        bool, typer.Option("--json", help="输出原始 JSON。")
    ] = False,
) -> None:
    """让 serve 进程退出。"""
    try:
        response = call_socket(
            socket_path or default_socket_path(),
            {"action": "shutdown"},
            timeout=timeout,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if json_output:
        stdout.print(as_json(response))
    else:
        stdout.print("serve 已请求退出。")


@app.command("list")
def list_scripts(
    pattern: Annotated[
        str | None, typer.Option(help="按脚本内容或名称 pattern 过滤。")
    ] = None,
    include_pattern: Annotated[
        list[str] | None,
        typer.Option(
            "--include-pattern", help="按 include/match URL pattern 过滤，可重复。"
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="输出原始 JSON。")
    ] = False,
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", help=socket_option_help()),
    ] = None,
    timeout: Annotated[float, typer.Option(help="UDS 请求超时秒数。")] = 30.0,
) -> None:
    """列出 Tampermonkey userscript。"""
    try:
        response = command_via_socket(
            {"action": "list", "filter": build_filter(pattern, include_pattern)},
            socket_path=socket_path or default_socket_path(),
            timeout=timeout,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if json_output:
        stdout.print(as_json(response))
        return

    scripts = [ScriptMeta.model_validate(item) for item in response.get("list", [])]
    table = Table("Name", "Namespace", "Path", "Requires", "Storage")
    for script in scripts:
        table.add_row(
            script.name,
            script.namespace,
            script.path,
            "\n".join(script.requires),
            script.storage or "",
        )
    stdout.print(table)


@app.command("get")
def get_script(
    path: Annotated[str, typer.Argument(help="脚本 path，来自 list 输出。")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="把脚本内容写入文件；必须指定。"),
    ],
    if_not_modified_since: Annotated[
        float | None,
        typer.Option(help="只在脚本晚于该 Unix 时间戳修改时返回。"),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="输出原始 JSON。")
    ] = False,
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", help=socket_option_help()),
    ] = None,
    timeout: Annotated[float, typer.Option(help="UDS 请求超时秒数。")] = 30.0,
) -> None:
    """读取指定 userscript 并写入本地文件。"""
    payload: dict[str, Any] = {"action": "get", "path": path}
    if if_not_modified_since is not None:
        payload["ifNotModifiedSince"] = if_not_modified_since
    try:
        response = command_via_socket(
            payload, socket_path=socket_path or default_socket_path(), timeout=timeout
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if response.get("error"):
        print_response(response, json_output=False)
        return

    value = str(response.get("value") or "")
    output.write_text(value)
    if json_output:
        metadata = {key: val for key, val in response.items() if key != "value"}
        metadata["output"] = str(output)
        stdout.print(as_json(metadata))
    else:
        console.print(f"已写入 {output}")


@app.command("patch")
def patch_script(
    path: Annotated[str, typer.Argument(help="脚本 path，来自 list 输出。")],
    file: Annotated[Path, typer.Argument(help="新的 userscript 文件。")],
    last_modified: Annotated[
        float | None,
        typer.Option(help="乐观锁 Unix 时间戳，来自 get 输出。"),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="输出原始 JSON。")
    ] = False,
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", help=socket_option_help()),
    ] = None,
    timeout: Annotated[float, typer.Option(help="UDS 请求超时秒数。")] = 30.0,
) -> None:
    """用本地文件覆盖指定 userscript。"""
    payload: dict[str, Any] = {
        "action": "patch",
        "path": path,
        "value": file.read_text(),
    }
    if last_modified is not None:
        payload["lastModified"] = last_modified
    try:
        response = command_via_socket(
            payload, socket_path=socket_path or default_socket_path(), timeout=timeout
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    print_response(response, json_output)


@app.command("put")
def put_script(
    file: Annotated[Path, typer.Argument(help="要创建的 userscript 文件。")],
    last_modified: Annotated[
        float | None, typer.Option(help="乐观锁 Unix 时间戳。")
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="输出原始 JSON。")
    ] = False,
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", help=socket_option_help()),
    ] = None,
    timeout: Annotated[float, typer.Option(help="UDS 请求超时秒数。")] = 30.0,
) -> None:
    """创建新的 userscript。"""
    payload: dict[str, Any] = {"action": "put", "value": file.read_text()}
    if last_modified is not None:
        payload["lastModified"] = last_modified
    try:
        response = command_via_socket(
            payload, socket_path=socket_path or default_socket_path(), timeout=timeout
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    print_response(response, json_output)


@app.command("delete")
def delete_script(
    path: Annotated[str, typer.Argument(help="脚本 path，来自 list 输出。")],
    json_output: Annotated[
        bool, typer.Option("--json", help="输出原始 JSON。")
    ] = False,
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", help=socket_option_help()),
    ] = None,
    timeout: Annotated[float, typer.Option(help="UDS 请求超时秒数。")] = 30.0,
) -> None:
    """删除指定 userscript。"""
    try:
        response = command_via_socket(
            {"action": "delete", "path": path},
            socket_path=socket_path or default_socket_path(),
            timeout=timeout,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    print_response(response, json_output)


if __name__ == "__main__":
    app()
