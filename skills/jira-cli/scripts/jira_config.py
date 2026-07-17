"""TOML configuration management for jira-cli."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import tomli_w
from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_CONFIG_PATH = Path("~/.config/jira-cli/config.toml").expanduser()
DEFAULT_SMC_CONFIG_PATH = Path("~/.agents/jira_config.json").expanduser()


class JiraCliSettings(BaseModel):
    """Persistent jira-cli settings."""

    server: str = "https://jira.shopee.io"
    token: str | None = None
    username: str | None = None
    auth_type: str = "auto"
    timeout_seconds: float = Field(default=30.0, gt=0)
    verify_ssl: bool = True
    dangerously_allow_http: bool = False
    default_project: str | None = None
    default_board: str | None = None
    epic_name_field: str | None = None
    epic_link_field: str | None = None
    timezone: str | None = None

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"auto", "bearer", "basic"}:
            raise ValueError("auth_type must be auto, bearer, or basic")
        return normalized

    @model_validator(mode="after")
    def validate_server_transport(self) -> JiraCliSettings:
        scheme = urlsplit(self.server).scheme.lower()
        if scheme not in {"http", "https"}:
            raise ValueError("server must use http or https")
        if scheme == "http" and not self.dangerously_allow_http:
            raise ValueError(
                "HTTP requires dangerously_allow_http=true because credentials "
                "would be sent without transport encryption"
            )
        return self


def load_settings(path: Path = DEFAULT_CONFIG_PATH) -> JiraCliSettings:
    if not path.exists():
        return JiraCliSettings()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Cannot read config {path}: {exc}") from exc
    return JiraCliSettings.model_validate(data)


def save_settings(
    settings: JiraCliSettings,
    path: Path = DEFAULT_CONFIG_PATH,
    *,
    overwrite: bool = False,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Config already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = settings.model_dump(exclude_none=True)
    encoded = tomli_w.dumps(payload)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_handle:
            file_handle.write(encoded)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def import_smc_settings(path: Path = DEFAULT_SMC_CONFIG_PATH) -> JiraCliSettings:
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read smc jira config {path}: {exc}") from exc

    project = raw.get("project") if isinstance(raw.get("project"), dict) else {}
    epic = raw.get("epic") if isinstance(raw.get("epic"), dict) else {}
    return JiraCliSettings(
        server=raw.get("server") or "https://jira.shopee.io",
        token=raw.get("api_token"),
        username=raw.get("login"),
        auth_type=raw.get("auth_type") or "auto",
        verify_ssl=not bool(raw.get("insecure", False)),
        default_project=project.get("key"),
        default_board=str(raw["board"]) if raw.get("board") else None,
        epic_name_field=epic.get("name"),
        epic_link_field=epic.get("link"),
        timezone=raw.get("timezone"),
    )


def masked_settings(settings: JiraCliSettings) -> dict[str, Any]:
    result = settings.model_dump(exclude_none=True)
    token = result.get("token")
    if token:
        result["token"] = (
            f"{token[:4]}...{token[-4:]}" if len(token) > 10 else "********"
        )
    return result
