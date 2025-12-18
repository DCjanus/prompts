#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pydantic>=2.12.5",
#     "rich>=14.2.0",
#     "tiktoken>=0.12.0",
#     "typer>=0.20.0",
#     # 交互式 TUI 暂不启用，若需可添加 textual>=6.10.0
# ]
# ///

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List

from pydantic import BaseModel, Field, ValidationError, field_validator
from rich.console import Console
from rich.text import Text
import tiktoken
import typer

console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=False)


class InputSpec(BaseModel):
    repo_path: Path | None = Field(
        default=None, description="Git 仓库路径，默认自动探测为当前工作目录所属仓库根目录"
    )

    @field_validator("repo_path")
    @classmethod
    def ensure_git_repo(cls, value: Path | None) -> Path | None:
        if value is None:
            return value
        if not value.exists():
            raise ValueError(f"路径不存在: {value}")
        if not value.is_dir():
            raise ValueError(f"目标不是目录: {value}")
        if not (value / ".git").exists():
            raise ValueError(f"目录下未发现 .git: {value}")
        return value


def detect_repo_root(explicit_path: Path | None) -> Path:
    """优先使用用户指定路径，否则通过 git rev-parse 自动探测仓库根目录。"""
    if explicit_path:
        return explicit_path.resolve()
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
        return Path(output)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        console.print(f"[red]无法定位 Git 仓库根目录：{exc}[/red]")
        raise typer.Exit(code=1)


def list_tracked_files(repo_root: Path) -> List[Path]:
    """列出仓库中所有被跟踪的文件路径。"""
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=repo_root, text=True
        )
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]获取跟踪文件列表失败：{exc}[/red]")
        raise typer.Exit(code=1)
    return [repo_root / path for path in output.split("\x00") if path]


def is_text_file(path: Path, sample_size: int = 4096) -> bool:
    """简单二进制判定：包含 NUL 字节或无法 UTF-8 解码则视为二进制。"""
    try:
        sample = path.read_bytes()[:sample_size]
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def count_tokens(text: str, encoding) -> int:
    return len(encoding.encode(text))


@dataclass
class TokenNode:
    name: str
    is_dir: bool
    tokens: int = 0
    children: Dict[str, "TokenNode"] = field(default_factory=dict)

    def ensure_child(self, name: str, is_dir: bool) -> "TokenNode":
        if name not in self.children:
            self.children[name] = TokenNode(name=name, is_dir=is_dir)
        return self.children[name]

    def aggregate(self) -> int:
        if not self.is_dir:
            return self.tokens
        self.tokens = sum(child.aggregate() for child in self.children.values())
        return self.tokens


def build_token_tree(repo_root: Path, files: Iterable[Path], encoding) -> TokenNode:
    root_node = TokenNode(name=repo_root.name, is_dir=True)
    skipped: List[Path] = []
    for file_path in files:
        rel_parts = file_path.relative_to(repo_root).parts
        if not is_text_file(file_path):
            skipped.append(file_path)
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append(file_path)
            continue
        tokens = count_tokens(text, encoding)

        node = root_node
        for part in rel_parts[:-1]:
            node = node.ensure_child(part, is_dir=True)
        file_node = node.ensure_child(rel_parts[-1], is_dir=False)
        file_node.tokens = tokens

    root_node.aggregate()
    return root_node, len(skipped)


def max_token_text_len(node: TokenNode) -> int:
    """获取树中 token 数字字符串的最大长度，用于右对齐。"""
    lengths = [len(format_tokens(node.tokens))]
    for child in node.children.values():
        lengths.append(max_token_text_len(child))
    return max(lengths)


def format_tokens(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def render_tree_lines(
    node: TokenNode,
    max_tokens: int,
    bar_width: int,
    max_token_len: int,
):
    from rich.table import Table

    table = Table(
        show_header=False,
        show_edge=False,
        box=None,
        pad_edge=False,
        expand=False,
        collapse_padding=True,
    )
    table.add_column("tokens", justify="right", min_width=max_token_len, no_wrap=True)
    table.add_column("name", justify="left")
    table.add_column(
        "bar",
        justify="left",
        min_width=bar_width,
        max_width=bar_width,
        no_wrap=True,
    )
    table.add_column("%", justify="right", width=4, no_wrap=True)

    def walk(current: TokenNode, prefix: str, is_last: bool, depth: int) -> None:
        connector = "" if depth == 0 else ("└── " if is_last else "├── ")
        next_prefix = prefix + ("    " if is_last else "│   ")

        is_file = not current.is_dir
        tokens_style = "green" if is_file else "blue"
        name_style = None if is_file else "bold"
        token_text = format_tokens(current.tokens)

        name_text = Text(f"{prefix}{connector}")
        name_text.append(current.name, style=name_style)

        bar_text: Text | str = ""
        percent_text = ""
        if is_file:
            ratio = 0 if max_tokens == 0 else current.tokens / max_tokens
            filled = max(1 if current.tokens > 0 else 0, int(ratio * bar_width))
            empty = bar_width - filled
            bar = "█" * filled + "░" * empty
            bar_text = Text(bar, style="magenta")
            percent_text = f"{ratio * 100:>3.0f}%"

        table.add_row(
            Text(token_text, style=tokens_style),
            name_text,
            bar_text,
            percent_text,
        )

        children = list(current.children.values())
        dirs = sorted([c for c in children if c.is_dir], key=lambda n: n.name)
        files = sorted([c for c in children if not c.is_dir], key=lambda n: n.name)
        ordered = dirs + files
        for idx, child in enumerate(ordered):
            walk(child, next_prefix, idx == len(ordered) - 1, depth + 1)

    walk(node, prefix="", is_last=True, depth=0)
    return table


def summarize_tree(node: TokenNode) -> tuple[int, int, str]:
    """返回 (文件数, 最大 token 数, 最大文件名)。"""
    max_tokens = 0
    max_name = ""
    count = 0

    def walk(current: TokenNode, path_parts: list[str]) -> None:
        nonlocal max_tokens, max_name, count
        if not current.is_dir:
            count += 1
            if current.tokens > max_tokens:
                max_tokens = current.tokens
                max_name = "/".join(path_parts + [current.name])
            return
        for child in current.children.values():
            walk(child, path_parts + [current.name])

    walk(node, [])
    return count, max_tokens, max_name


@app.command(help="统计仓库内所有被 Git 追踪的文本文件的 token 数，并以树状图展示。")
def main(
    path: Path | None = typer.Option(
        None, "--path", "-p", help="Git 仓库路径，默认自动探测"
    ),
    bar_width: int = typer.Option(
        24, "--bar-width", "-w", help="进度条宽度（字符数），基于全局最大 token 数缩放"
    ),
) -> None:
    try:
        spec = InputSpec(repo_path=path)
    except ValidationError as exc:
        console.print("[red]参数校验失败[/red]")
        for err in exc.errors():
            console.print(f"• {err['msg']}")
        raise typer.Exit(code=1)

    repo_root = detect_repo_root(spec.repo_path)
    files = list_tracked_files(repo_root)
    encoding = tiktoken.get_encoding("cl100k_base")

    token_tree, skipped = build_token_tree(repo_root, files, encoding)
    tree = render_tree_lines(
        node=token_tree,
        max_tokens=token_tree.tokens,
        bar_width=bar_width,
        max_token_len=max_token_text_len(token_tree),
    )
    if skipped:
        console.print(f"[yellow]跳过 {skipped} 个疑似二进制或非 UTF-8 文件[/yellow]")
    console.print(tree)


if __name__ == "__main__":
    app()
