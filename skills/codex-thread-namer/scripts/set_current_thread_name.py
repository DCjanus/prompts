#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

"""Set the current Codex thread name through codex app-server."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import json
import os
from queue import Empty, Queue
import subprocess
import sys
import threading
from time import monotonic
from typing import Any


APP_SERVER_TIMEOUT_ERROR = "等待 codex app-server 响应超时。"
STDOUT_EOF = object()


class ThreadNameError(RuntimeError):
    """User-facing error for this script."""


@dataclass(frozen=True)
class JsonRpcResponse:
    id: int | str | None
    result: Any | None = None
    error: dict[str, Any] | None = None


class CodexAppServerClient:
    """Tiny JSON-RPC client for `codex app-server --listen stdio://`."""

    def __init__(self, request_timeout: float = 30.0) -> None:
        self.request_timeout = request_timeout
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._stdout_queue: Queue[str | object] = Queue()
        self._stderr_lines: deque[str] = deque(maxlen=200)
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def __enter__(self) -> CodexAppServerClient:
        try:
            self._process = subprocess.Popen(
                ["codex", "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise ThreadNameError(
                "未找到 `codex` 命令，无法启动 `codex app-server`。请确认 Codex CLI 已安装且在 PATH 中。"
            ) from exc
        except OSError as exc:
            reason = exc.strerror or str(exc)
            raise ThreadNameError(f"无法启动 `codex app-server`：{reason}") from exc

        self._stdout_thread = threading.Thread(
            target=self._drain_stdout,
            name="codex-thread-namer-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name="codex-thread-namer-stderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

        try:
            self.initialize()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._process is None:
            return

        process = self._process
        try:
            if process.stdin:
                process.stdin.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        finally:
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
            self._process = None

    def _drain_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self._stdout_queue.put(line)
        self._stdout_queue.put(STDOUT_EOF)

    def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr_lines.append(line.rstrip("\n"))

    def _stderr_tail(self) -> str:
        return "\n".join(self._stderr_lines)

    def _ensure_running(self) -> subprocess.Popen[str]:
        if self._process is None:
            raise ThreadNameError("codex app-server 尚未启动。")
        return self._process

    def _send_json(self, payload: dict[str, Any]) -> None:
        process = self._ensure_running()
        if process.stdin is None:
            raise ThreadNameError("codex app-server stdin 不可用。")
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except OSError as exc:
            message = "向 codex app-server 发送请求失败。"
            if detail := self._stderr_tail():
                message += f"\nstderr:\n{detail}"
            raise ThreadNameError(message) from exc

    def _read_response(self, deadline: float) -> JsonRpcResponse:
        process = self._ensure_running()
        timeout = deadline - monotonic()
        if timeout <= 0:
            raise ThreadNameError(APP_SERVER_TIMEOUT_ERROR)

        try:
            line = self._stdout_queue.get(timeout=timeout)
        except Empty as exc:
            raise ThreadNameError(APP_SERVER_TIMEOUT_ERROR) from exc

        if line is STDOUT_EOF:
            line = ""
        if not isinstance(line, str):
            raise ThreadNameError("codex app-server stdout 返回了未知消息。")

        if not line:
            return_code = process.poll()
            message = "codex app-server 已提前退出。"
            if return_code is not None:
                message += f" exit_code={return_code}"
            if detail := self._stderr_tail():
                message += f"\nstderr:\n{detail}"
            raise ThreadNameError(message)

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            message = f"codex app-server 返回了非法 JSON：{line.strip()}"
            if detail := self._stderr_tail():
                message += f"\nstderr:\n{detail}"
            raise ThreadNameError(message) from exc

        if not isinstance(payload, dict):
            raise ThreadNameError("codex app-server 返回结构不合法：顶层必须是对象。")

        if "method" in payload:
            return JsonRpcResponse(id=None, result=None, error=None)
        return JsonRpcResponse(
            id=payload.get("id"),
            result=payload.get("result"),
            error=payload.get("error"),
        )

    def request(self, method: str, params: dict[str, Any] | None) -> Any:
        request_id = self._next_id
        self._next_id += 1
        deadline = monotonic() + self.request_timeout

        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._send_json(payload)

        while True:
            response = self._read_response(deadline)
            if response.id != request_id:
                continue
            if response.error is not None:
                message = self._format_rpc_error(response.error)
                if detail := self._stderr_tail():
                    message += f"\nstderr:\n{detail}"
                raise ThreadNameError(message)
            return response.result

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        self._send_json(payload)

    def initialize(self) -> None:
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex-thread-namer",
                    "title": "Codex Thread Namer",
                    "version": "0.1.0",
                },
                "capabilities": {
                    "experimentalApi": False,
                },
            },
        )
        self.notify("initialized")

    @staticmethod
    def _format_rpc_error(error: dict[str, Any]) -> str:
        code = error.get("code", "unknown")
        message = error.get("message", "unknown error")
        formatted = f"codex app-server 请求失败：{code}: {message}"
        if "data" in error and error["data"] is not None:
            formatted += "\n" + json.dumps(error["data"], ensure_ascii=False, indent=2)
        return formatted

    def set_thread_name(self, thread_id: str, name: str) -> None:
        self.request("thread/name/set", {"threadId": thread_id, "name": name})


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set the current Codex thread name through codex app-server.",
    )
    parser.add_argument("name", help="完整 thread 名称，格式建议为 `Project: 标题`。")
    return parser.parse_args(argv)


def current_thread_id() -> str:
    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if not thread_id:
        raise ThreadNameError(
            "当前环境没有 CODEX_THREAD_ID，无法判断要设置哪个 Codex 会话。"
        )
    return thread_id


def normalized_name(raw_name: str) -> str:
    name = raw_name.strip()
    if not name:
        raise ThreadNameError("thread 名称不能为空。")
    return name


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        thread_id = current_thread_id()
        name = normalized_name(args.name)
        with CodexAppServerClient() as client:
            client.set_thread_name(thread_id, name)
    except ThreadNameError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print(f"已设置当前 Codex 会话名称：{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
