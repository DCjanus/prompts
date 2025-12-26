#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx>=0.28.1",
#     "pydantic>=2.12.5",
#     "rich>=14.2.0",
#     "typer>=0.20.1",
# ]
# ///

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import typer
from pydantic import AnyHttpUrl, BaseModel, Field, ValidationError
from rich.console import Console
from rich.table import Table

APP_NAME = "ticktick-cli"
DEFAULT_BASE_URL = "https://api.dida365.com/api/v2"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"
SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ticktick_api_client import TicktickApiClient, TicktickApiError  # noqa: E402

app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
api_app = typer.Typer(no_args_is_help=True)
console = Console()


class ClientConfig(BaseModel):
    base_url: AnyHttpUrl = Field(default=DEFAULT_BASE_URL)
    token: str | None = Field(default=None)
    timeout_seconds: float = Field(default=30.0, gt=0)


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def load_config() -> ClientConfig:
    if not CONFIG_PATH.exists():
        return ClientConfig()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return ClientConfig.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ApiError(f"Invalid config at {CONFIG_PATH}: {exc}") from exc


def save_config(config: ClientConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def parse_key_value(items: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ApiError(f"Invalid key=value pair: {item}")
        key, value = item.split("=", 1)
        params[key] = value
    return params


def render_response(response: httpx.Response) -> None:
    console.print(f"[bold]Status:[/bold] {response.status_code}")
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            console.print(response.text)
            return
        console.print_json(data=payload)
        return
    console.print(response.text)


@app.callback()
def main() -> None:
    pass


@config_app.command("path")
def config_path() -> None:
    console.print(str(CONFIG_PATH))


@config_app.command("show")
def config_show() -> None:
    config = load_config()
    table = Table(title="ticktick-cli config")
    table.add_column("field")
    table.add_column("value")
    table.add_row("base_url", str(config.base_url))
    table.add_row("token", "set" if config.token else "missing")
    table.add_row("timeout_seconds", str(config.timeout_seconds))
    console.print(table)


@config_app.command("set")
def config_set(
    base_url: str | None = typer.Option(None, "--base-url"),
    token: str | None = typer.Option(None, "--token"),
    timeout_seconds: float | None = typer.Option(None, "--timeout"),
) -> None:
    config = load_config()
    payload = config.model_dump()
    if base_url is not None:
        payload["base_url"] = base_url
    if token is not None:
        payload["token"] = token
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
    updated = ClientConfig.model_validate(payload)
    save_config(updated)
    console.print("Config updated.")


@api_app.command("request")
def api_request(
    method: str = typer.Argument(...),
    path: str = typer.Argument(...),
    params: list[str] = typer.Option(None, "--param"),
    raw_json: str | None = typer.Option(None, "--json"),
) -> None:
    config = load_config()
    if not config.token:
        raise ApiError("Missing token. Run `config set --token <token>` first.")
    client = TicktickApiClient(
        token=config.token,
        base_url=str(config.base_url),
        timeout_seconds=config.timeout_seconds,
    )
    query = parse_key_value(params or [])
    payload: dict[str, Any] | list[Any] | None = None
    if raw_json:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ApiError(f"Invalid JSON payload: {exc}") from exc
    response = client._request(method, path, params=query, payload=payload)
    if response.status_code >= 400:
        render_response(response)
        raise ApiError("Request failed", response.status_code)
    render_response(response)


app.add_typer(config_app, name="config")
app.add_typer(api_app, name="api")


def run() -> None:
    try:
        app()
    except (ApiError, TicktickApiError) as exc:
        if exc.status_code:
            console.print(f"[red]Error:[/red] {exc} (status {exc.status_code})")
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    run()
