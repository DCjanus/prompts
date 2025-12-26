#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "rich>=14.2.0",
#     "typer>=0.21.0",
# ]
# ///
"""获取 GitHub PR 评审与评论信息的脚本。"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Tuple
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(add_completion=False, help="获取 GitHub PR 的 reviews、comments、review threads。")
CONSOLE = Console()


def parse_pr_url(pr_url: str) -> Tuple[str, str, int]:
    """解析 GitHub PR URL 并返回 owner/repo/number。"""
    parsed = urlparse(pr_url)
    if parsed.netloc != "github.com":
        raise typer.BadParameter("仅支持 github.com 域名的 PR 链接。")

    match = re.match(r"^/([^/]+)/([^/]+)/pull/(\\d+)", parsed.path)
    if not match:
        raise typer.BadParameter("PR 链接格式应为 https://github.com/<owner>/<repo>/pull/<number>。")

    owner, repo, number = match.group(1), match.group(2), int(match.group(3))
    return owner, repo, number


def build_query() -> str:
    """构造 GraphQL 查询字符串。"""
    return """
query($owner:String!, $repo:String!, $number:Int!) {{
  repository(owner:$owner, name:$repo) {{
    pullRequest(number:$number) {{
      title
      url
      body
      reviewDecision
      reviews(first:20) {{
        nodes {{ author {{ login }} state body submittedAt }}
      }}
      comments(first:20) {{
        nodes {{ author {{ login }} body createdAt }}
      }}
      reviewThreads(first:20) {{
        nodes {{
          isResolved
          comments(first:20) {{
            nodes {{ author {{ login }} body path line createdAt }}
          }}
        }}
      }}
    }}
  }}
}}
""".strip()


def run_query(
    query: str,
    owner: str,
    repo: str,
    number: int,
) -> str:
    """调用 gh api graphql 并返回原始 JSON。"""
    command = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={query}",
        "-f",
        f"owner={owner}",
        "-f",
        f"repo={repo}",
        "-F",
        f"number={number}",
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        CONSOLE.print(Panel.fit("[red]未找到 gh 命令，请先安装 GitHub CLI。[/red]"))
        raise typer.Exit(code=1) from exc

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "gh api graphql 执行失败。"
        CONSOLE.print(Panel.fit(f"[red]{message}[/red]", title="请求失败"))
        raise typer.Exit(code=result.returncode)

    return result.stdout


@app.command()
def fetch(
    pr_url: str = typer.Argument(
        ...,
        help="PR 链接，例如 https://github.com/OWNER/REPO/pull/123。",
    ),
) -> None:
    """拉取 PR 的 reviews、comments 与 review threads。"""
    owner_value, repo_value, number_value = parse_pr_url(pr_url)
    query = build_query()
    output = run_query(
        query,
        owner_value,
        repo_value,
        number_value,
    )
    sys.stdout.write(output)


if __name__ == "__main__":
    app()
