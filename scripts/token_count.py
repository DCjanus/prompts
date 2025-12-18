#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pydantic>=2.12.5",
#     "rich>=14.2.0",
#     "tiktoken>=0.12.0",
#     "typer>=0.20.0",
# ]
# ///

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator
from rich.console import Console
import tiktoken
import typer

console = Console()
# 关闭 Typer 自动补全以保持命令行精简
app = typer.Typer(add_completion=False, no_args_is_help=False)


class InputSpec(BaseModel):
    file_path: Path | None = Field(default=None, description="输入文件路径")

    @field_validator("file_path")
    @classmethod
    def ensure_file_exists(cls, value: Path | None) -> Path | None:
        if value is None:
            return value
        if not value.exists():
            raise ValueError(f"文件不存在: {value}")
        if not value.is_file():
            raise ValueError(f"目标不是文件: {value}")
        return value


def count_tokens(text: str) -> int:
    """使用默认 cl100k_base 编码统计 token 数。"""
    encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


@app.command(help="统计输入文本的 token 数（tiktoken/cl100k_base）。")
def main(
    file: Path | None = typer.Argument(None, help="输入文件路径，省略则读取 stdin"),
) -> None:
    try:
        spec = InputSpec(file_path=file)
    except ValidationError as exc:
        console.print("[red]参数校验失败[/red]")
        for err in exc.errors():
            console.print(f"• {err['msg']}")
        raise typer.Exit(code=1)

    try:
        text = spec.file_path.read_text(encoding="utf-8") if spec.file_path else sys.stdin.read()
    except OSError as exc:  # noqa: PERF203 - keep clarity
        console.print(f"[red]读取输入失败：{exc}[/red]")
        raise typer.Exit(code=1)

    tokens = count_tokens(text)
    console.print(f"[bold cyan]{tokens}[/bold cyan]")


if __name__ == "__main__":
    app()
