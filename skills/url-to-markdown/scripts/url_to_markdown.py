#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx>=0.28.1",
#     "rich>=14.2.0",
#     "typer>=0.20.1",
# ]
# ///

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import httpx
import typer
from rich.console import Console
from rich.panel import Panel

APP = typer.Typer(add_completion=False)
CONSOLE = Console()


@dataclass(frozen=True)
class CloudflareConfig:
    """Cloudflare 调用所需的认证配置模型。"""

    account_id: str
    api_token: str


def build_config() -> CloudflareConfig:
    """从环境变量构建 CloudflareConfig。"""

    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    missing: list[str] = []
    if not account_id:
        missing.append("CLOUDFLARE_ACCOUNT_ID")
    if not api_token:
        missing.append("CLOUDFLARE_API_TOKEN")
    if missing:
        raise typer.BadParameter(f"Missing environment variables: {', '.join(missing)}.")
    return CloudflareConfig(account_id=account_id, api_token=api_token)


def extract_markdown(data: Any) -> str:
    """从 Cloudflare API 响应中提取 Markdown 字符串。"""

    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("result"), str):
            return cast(str, data["result"])
        if isinstance(data.get("markdown"), str):
            return cast(str, data["markdown"])
    return str(data)


def extract_error(data: Any) -> str | None:
    """从 Cloudflare API 响应中提取错误信息。"""

    if not isinstance(data, dict):
        return None
    errors = data.get("errors")
    if isinstance(errors, list):
        messages = [item.get("message") for item in errors if isinstance(item, dict) and item.get("message")]
        if messages:
            return "; ".join(messages)
    if isinstance(data.get("error"), dict) and data["error"].get("message"):
        return str(data["error"]["message"])
    return None


@APP.command()
def fetch(
    url: str = typer.Argument(..., help="Target URL to render into markdown."),
    output: Path | None = typer.Option(None, help="Write markdown to file instead of stdout."),
    cache_ttl: int = typer.Option(60, help="Cache TTL seconds (0 to disable)."),
) -> None:
    """通过 Cloudflare Browser Rendering API 获取 Markdown。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise typer.BadParameter("Only http or https URLs are supported.")

    resolved_config = build_config()
    endpoint = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{resolved_config.account_id}/browser-rendering/markdown"
    )
    headers = {
        "Authorization": f"Bearer {resolved_config.api_token}",
        "Content-Type": "application/json",
    }
    params: dict[str, Any] = {"cacheTTL": cache_ttl} if cache_ttl is not None else {}
    payload = {"url": url}

    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(endpoint, headers=headers, params=params, json=payload)
    except httpx.HTTPError as exc:
        CONSOLE.print(
            Panel.fit(
                f"[red]Cloudflare API error[/red]\n{exc}",
                title="Request Failed",
            )
        )
        raise typer.Exit(code=1) from exc

    data: Any = None
    if response.headers.get("content-type", "").startswith("application/json"):
        try:
            data = response.json()
        except ValueError:
            data = None

    if response.status_code >= 400:
        message = extract_error(data) or response.text.strip()
        CONSOLE.print(
            Panel.fit(
                f"[red]Cloudflare API error[/red]\nStatus: {response.status_code}\n{message}",
                title="Request Failed",
            )
        )
        raise typer.Exit(code=1)

    if isinstance(data, dict):
        if data.get("success") is False or data.get("status") is False:
            message = extract_error(data) or "Unknown Cloudflare API error."
            CONSOLE.print(
                Panel.fit(
                    f"[red]Cloudflare API error[/red]\n{message}",
                    title="Request Failed",
                )
            )
            raise typer.Exit(code=1)

    markdown = extract_markdown(data if data is not None else response.text)
    if output:
        output.write_text(markdown, encoding="utf-8")
        CONSOLE.print(f"[green]Saved markdown to[/green] {output}")
    else:
        CONSOLE.print(markdown, markup=False)


if __name__ == "__main__":
    APP()
