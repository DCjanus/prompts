#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx2>=2.7.0",
#     "pydantic>=2.13.4",
#     "rich>=15.0.0",
#     "tomli-w>=1.2.0",
#     "typer>=0.27.0",
# ]
# ///
"""Controlled Jira Server/Data Center command-line client."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.pretty import Pretty
from rich.table import Table

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from jira_api_client import JiraApiClient, JiraApiError, JiraConfig  # noqa: E402
from jira_config import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    DEFAULT_SMC_CONFIG_PATH,
    JiraCliSettings,
    import_smc_settings,
    load_settings,
    masked_settings,
    save_settings,
)

app = typer.Typer(help="Manage Jira Server/Data Center through REST API v2.")
config_app = typer.Typer(help="Manage jira-cli TOML configuration.")
user_app = typer.Typer(help="Inspect Jira users.")
project_app = typer.Typer(help="Inspect projects, versions, and components.")
metadata_app = typer.Typer(help="Inspect fields and issue creation metadata.")
issue_app = typer.Typer(help="Read and update Jira issues.")
epic_app = typer.Typer(help="Create epics and manage epic membership.")
comment_app = typer.Typer(help="Manage issue comments.")
attachment_app = typer.Typer(help="Manage issue attachments.")
link_app = typer.Typer(help="Manage links between Jira issues.")
remote_link_app = typer.Typer(help="Manage external links on issues.")
watcher_app = typer.Typer(help="Manage issue watchers.")
vote_app = typer.Typer(help="Manage the current user's issue vote.")
worklog_app = typer.Typer(help="Manage issue worklogs.")
board_app = typer.Typer(help="Inspect Jira Software boards.")
sprint_app = typer.Typer(help="Inspect Jira Software sprints.")
api_app = typer.Typer(help="Access unwrapped read-only REST endpoints.")
for name, group in {
    "config": config_app,
    "user": user_app,
    "project": project_app,
    "metadata": metadata_app,
    "issue": issue_app,
    "epic": epic_app,
    "comment": comment_app,
    "attachment": attachment_app,
    "link": link_app,
    "remote-link": remote_link_app,
    "watcher": watcher_app,
    "vote": vote_app,
    "worklog": worklog_app,
    "board": board_app,
    "sprint": sprint_app,
    "api": api_app,
}.items():
    app.add_typer(group, name=name)

console = Console()
err_console = Console(stderr=True)
_json_errors = False


@dataclass
class State:
    persisted_settings: JiraCliSettings
    settings: JiraCliSettings
    config_path: Path
    json_output: bool
    _client: JiraApiClient | None = None

    def client(self) -> JiraApiClient:
        if self._client is None:
            if not self.settings.token:
                raise typer.BadParameter(
                    "Jira token is required. Run 'config import-smc', configure "
                    f"{self.config_path}, or set JIRA_API_TOKEN."
                )
            self._client = JiraApiClient(
                JiraConfig(
                    server=self.settings.server,
                    token=self.settings.token,
                    username=self.settings.username,
                    auth_type=self.settings.auth_type,
                    timeout_seconds=self.settings.timeout_seconds,
                    verify_ssl=not self.settings.dangerously_disable_tls_verification,
                    dangerously_allow_http=self.settings.dangerously_allow_http,
                )
            )
        return self._client


def _env_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise typer.BadParameter(f"{name} must be true or false")


def _first(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _safe_error_message(exc: ValueError | ValidationError) -> str:
    if isinstance(exc, ValidationError):
        messages = []
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            prefix = f"{location}: " if location else ""
            messages.append(prefix + error["msg"])
        return "; ".join(messages)
    return str(exc)


@app.callback()
def configure(
    ctx: typer.Context,
    server: Annotated[
        str | None, typer.Option(help="Temporary Jira server override.")
    ] = None,
    username: Annotated[
        str | None, typer.Option(help="Temporary Basic Auth username override.")
    ] = None,
    auth_type: Annotated[
        str | None, typer.Option(help="Temporary auto, bearer, or basic override.")
    ] = None,
    timeout: Annotated[
        float | None, typer.Option(help="Temporary HTTP timeout override.")
    ] = None,
    config: Annotated[
        Path, typer.Option(help="TOML config path.")
    ] = DEFAULT_CONFIG_PATH,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON.")
    ] = False,
    dangerously_disable_tls_verification: Annotated[
        bool,
        typer.Option(
            "--dangerously-disable-tls-verification",
            help="Temporarily disable TLS verification. This is unsafe.",
        ),
    ] = False,
    dangerously_allow_http: Annotated[
        bool,
        typer.Option(
            "--dangerously-allow-http",
            help="Allow an HTTP Jira server. Credentials will be sent in cleartext.",
        ),
    ] = False,
) -> None:
    """Load persistent settings, then apply environment and CLI overrides."""
    global _json_errors
    _json_errors = json_output
    config_path = config.expanduser()
    try:
        persisted_settings = load_settings(config_path)
        updates = {
            "server": _first(server, os.getenv("JIRA_SERVER")),
            "token": os.getenv("JIRA_API_TOKEN"),
            "username": _first(username, os.getenv("JIRA_USERNAME")),
            "auth_type": _first(auth_type, os.getenv("JIRA_AUTH_TYPE")),
            "timeout_seconds": _first(timeout, os.getenv("JIRA_TIMEOUT")),
            "dangerously_allow_http": _env_bool("JIRA_DANGEROUSLY_ALLOW_HTTP"),
            "dangerously_disable_tls_verification": _env_bool(
                "JIRA_DANGEROUSLY_DISABLE_TLS_VERIFICATION"
            ),
        }
        if dangerously_disable_tls_verification:
            updates["dangerously_disable_tls_verification"] = True
        if dangerously_allow_http:
            updates["dangerously_allow_http"] = True
        settings = persisted_settings.model_copy(
            update={key: value for key, value in updates.items() if value is not None}
        )
        settings = JiraCliSettings.model_validate(settings.model_dump())
    except (ValueError, ValidationError) as exc:
        raise typer.BadParameter(_safe_error_message(exc)) from exc
    ctx.obj = State(persisted_settings, settings, config_path, json_output)


def _state(ctx: typer.Context) -> State:
    return ctx.ensure_object(State)


def _print_json(value: Any, *, error: bool = False) -> None:
    target = err_console if error else console
    target.file.write(
        json.dumps(value, ensure_ascii=False, default=str, indent=2) + "\n"
    )
    target.file.flush()


def _print_result(ctx: typer.Context, value: Any) -> None:
    if _state(ctx).json_output:
        _print_json(value)
    else:
        console.print(Pretty(value, expand_all=True))


def _body(body: str | None, body_file: Path | None, name: str = "body") -> str:
    if (body is None) == (body_file is None):
        raise typer.BadParameter(f"Provide exactly one of --{name} or --{name}-file")
    if body_file is not None:
        try:
            return body_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise typer.BadParameter(f"Cannot read {body_file}: {exc}") from exc
    return body or ""


def _optional_body(body: str | None, body_file: Path | None, name: str) -> str | None:
    if body is None and body_file is None:
        return None
    return _body(body, body_file, name)


def _parse_pairs(values: list[str] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values or []:
        key, separator, raw = value.partition("=")
        if not separator or not key:
            raise typer.BadParameter(f"Expected KEY=VALUE, got {value!r}")
        try:
            result[key] = json.loads(raw)
        except json.JSONDecodeError:
            result[key] = raw
    return result


def _require_project(state: State, project: str | None) -> str:
    value = project or state.settings.default_project
    if not value:
        raise typer.BadParameter(
            "Project is required; pass --project or configure default_project"
        )
    return value


def _issue_fields(
    *,
    project: str,
    issue_type: str,
    summary: str,
    description: str | None,
    parent: str | None,
    assignee: str | None,
    reporter: str | None,
    priority: str | None,
    labels: list[str] | None,
    components: list[str] | None,
    fix_versions: list[str] | None,
    custom_fields: list[str] | None,
) -> dict[str, Any]:
    parsed_custom_fields = _parse_pairs(custom_fields)
    reserved_fields = {
        "project",
        "issuetype",
        "summary",
        "description",
        "parent",
        "assignee",
        "reporter",
        "priority",
        "labels",
        "components",
        "fixVersions",
    }
    conflicts = sorted(parsed_custom_fields.keys() & reserved_fields)
    if conflicts:
        raise typer.BadParameter(
            "--field conflicts with explicit options: " + ", ".join(conflicts)
        )
    fields: dict[str, Any] = {
        "project": {"key": project},
        "issuetype": {"name": issue_type},
        "summary": summary,
        **parsed_custom_fields,
    }
    if description is not None:
        fields["description"] = description
    if parent:
        fields["parent"] = {"key": parent}
    if assignee:
        fields["assignee"] = {"name": assignee}
    if reporter:
        fields["reporter"] = {"name": reporter}
    if priority:
        fields["priority"] = {"name": priority}
    if labels:
        fields["labels"] = labels
    if components:
        fields["components"] = [{"name": value} for value in components]
    if fix_versions:
        fields["fixVersions"] = [{"name": value} for value in fix_versions]
    return fields


def _clone_fields(
    source_fields: dict[str, Any],
    *,
    project: str,
    summary: str | None,
    parent: str | None = None,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "project": {"key": project},
        "issuetype": {"name": (source_fields.get("issuetype") or {}).get("name")},
        "summary": summary or f"Clone of {source_fields.get('summary', 'issue')}",
    }
    source_project = (source_fields.get("project") or {}).get("key")
    cross_project = bool(source_project and source_project != project)
    for name in ("description", "labels", "components", "fixVersions", "priority"):
        if cross_project and name in {"components", "fixVersions"}:
            continue
        value = source_fields.get(name)
        if value not in (None, [], {}) and (
            allowed_fields is None or name in allowed_fields
        ):
            fields[name] = value
    source_parent = (source_fields.get("parent") or {}).get("key")
    if source_parent:
        selected_parent = (
            parent or source_parent if project == source_project else parent
        )
        if not selected_parent:
            raise typer.BadParameter(
                "Cloning a sub-task across projects requires --parent"
            )
        fields["parent"] = {"key": selected_parent}
    return fields


def _clone_target_project(
    source_fields: dict[str, Any], explicit_project: str | None
) -> str:
    if explicit_project:
        return explicit_project
    source_project = (source_fields.get("project") or {}).get("key")
    if not source_project:
        raise typer.BadParameter("Source issue does not include a project key")
    return source_project


def _create_field_ids(metadata: dict[str, Any]) -> set[str]:
    return {
        field_id
        for project in metadata.get("projects", [])
        for issue_type in project.get("issuetypes", [])
        for field_id in issue_type.get("fields", {})
    }


@config_app.command("path")
def config_path(ctx: typer.Context) -> None:
    """Show the active TOML config path."""
    _print_result(ctx, {"path": str(_state(ctx).config_path)})


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Show effective settings with the token masked."""
    _print_result(ctx, masked_settings(_state(ctx).settings))


@config_app.command("import-smc")
def config_import_smc(
    ctx: typer.Context,
    source: Annotated[
        Path, typer.Option(help="smc jira JSON config path.")
    ] = DEFAULT_SMC_CONFIG_PATH,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite existing TOML config.")
    ] = False,
    dangerously_disable_tls_verification: Annotated[
        bool,
        typer.Option(
            "--dangerously-disable-tls-verification",
            help="Preserve insecure=true from SMC config. This is unsafe.",
        ),
    ] = False,
) -> None:
    """Import the existing smc jira JSON configuration into TOML."""
    state = _state(ctx)
    try:
        imported = import_smc_settings(
            source.expanduser(),
            dangerously_disable_tls_verification=dangerously_disable_tls_verification,
        )
        save_settings(imported, state.config_path, overwrite=force)
    except (ValueError, FileExistsError, ValidationError) as exc:
        raise typer.BadParameter(_safe_error_message(exc)) from exc
    _print_result(
        ctx,
        {
            "path": str(state.config_path),
            "mode": "0600",
            "settings": masked_settings(imported),
        },
    )


@config_app.command("set")
def config_set(
    ctx: typer.Context,
    server: Annotated[str | None, typer.Option()] = None,
    prompt_token: Annotated[
        bool,
        typer.Option(
            "--prompt-token",
            help="Read and confirm the Jira token through a hidden prompt.",
        ),
    ] = False,
    username: Annotated[str | None, typer.Option()] = None,
    auth_type: Annotated[str | None, typer.Option()] = None,
    timeout_seconds: Annotated[float | None, typer.Option(min=0.1)] = None,
    verify_ssl: Annotated[
        bool, typer.Option("--verify-ssl", help="Enable TLS verification.")
    ] = False,
    dangerously_disable_tls_verification: Annotated[
        bool,
        typer.Option(
            "--dangerously-disable-tls-verification",
            help="Persistently disable TLS verification. This is unsafe.",
        ),
    ] = False,
    dangerously_allow_http: Annotated[
        bool,
        typer.Option(
            "--dangerously-allow-http",
            help="Persistently allow HTTP. Credentials will be sent in cleartext.",
        ),
    ] = False,
    require_https: Annotated[
        bool,
        typer.Option(
            "--require-https",
            help="Remove a persisted HTTP opt-in and require HTTPS.",
        ),
    ] = False,
    default_project: Annotated[str | None, typer.Option()] = None,
    default_board: Annotated[str | None, typer.Option()] = None,
    epic_name_field: Annotated[str | None, typer.Option()] = None,
    epic_link_field: Annotated[str | None, typer.Option()] = None,
    timezone: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Persist selected settings to the TOML config."""
    state = _state(ctx)
    if verify_ssl and dangerously_disable_tls_verification:
        raise typer.BadParameter(
            "Choose either --verify-ssl or --dangerously-disable-tls-verification"
        )
    if require_https and dangerously_allow_http:
        raise typer.BadParameter(
            "Choose either --require-https or --dangerously-allow-http"
        )
    if prompt_token and state.json_output:
        raise typer.BadParameter("--prompt-token cannot be used with --json")
    disable_tls_verification_update = (
        False if verify_ssl else True if dangerously_disable_tls_verification else None
    )
    allow_http_update = (
        False if require_https else True if dangerously_allow_http else None
    )
    token = (
        typer.prompt("Jira token", hide_input=True, confirmation_prompt=True)
        if prompt_token
        else None
    )
    server_update = server
    if (
        require_https
        and server_update is None
        and state.persisted_settings.server.lower().startswith("http://")
    ):
        server_update = "https://" + state.persisted_settings.server.split("://", 1)[1]
    updates = {
        "server": server_update,
        "token": token,
        "username": username,
        "auth_type": auth_type,
        "timeout_seconds": timeout_seconds,
        "dangerously_disable_tls_verification": disable_tls_verification_update,
        "dangerously_allow_http": allow_http_update,
        "default_project": default_project,
        "default_board": default_board,
        "epic_name_field": epic_name_field,
        "epic_link_field": epic_link_field,
        "timezone": timezone,
    }
    selected = {key: value for key, value in updates.items() if value is not None}
    if not selected:
        raise typer.BadParameter("No settings were provided")
    try:
        settings = JiraCliSettings.model_validate(
            state.persisted_settings.model_copy(update=selected).model_dump()
        )
        save_settings(settings, state.config_path, overwrite=True)
    except (ValueError, ValidationError) as exc:
        raise typer.BadParameter(_safe_error_message(exc)) from exc
    _print_result(ctx, masked_settings(settings))


@app.command("server-info")
def server_info(ctx: typer.Context) -> None:
    """Show Jira server version and deployment information."""
    _print_result(ctx, _state(ctx).client().server_info())


@user_app.command("me")
def user_me(ctx: typer.Context) -> None:
    """Show the authenticated Jira user."""
    _print_result(ctx, _state(ctx).client().myself())


@user_app.command("search")
def user_search(
    ctx: typer.Context,
    query: str,
    max_results: Annotated[int, typer.Option(min=1, max=1000)] = 50,
) -> None:
    """Search users using Jira's user picker."""
    _print_result(
        ctx, _state(ctx).client().search_users(query, max_results=max_results)
    )


@project_app.command("list")
def project_list(ctx: typer.Context) -> None:
    """List visible Jira projects."""
    _print_result(ctx, _state(ctx).client().list_projects())


@project_app.command("get")
def project_get(ctx: typer.Context, project_key: str) -> None:
    """Get one Jira project."""
    _print_result(ctx, _state(ctx).client().get_project(project_key))


@project_app.command("versions")
def project_versions(ctx: typer.Context, project_key: str | None = None) -> None:
    """List project releases/versions."""
    state = _state(ctx)
    _print_result(
        ctx, state.client().list_versions(_require_project(state, project_key))
    )


@project_app.command("components")
def project_components(ctx: typer.Context, project_key: str | None = None) -> None:
    """List project components."""
    state = _state(ctx)
    _print_result(
        ctx, state.client().list_components(_require_project(state, project_key))
    )


@metadata_app.command("fields")
def metadata_fields(ctx: typer.Context) -> None:
    """List Jira fields, including custom field IDs."""
    _print_result(ctx, _state(ctx).client().list_fields())


@metadata_app.command("issue-types")
def metadata_issue_types(ctx: typer.Context) -> None:
    """List Jira issue types."""
    _print_result(ctx, _state(ctx).client().list_issue_types())


@metadata_app.command("create")
def metadata_create(
    ctx: typer.Context,
    project: Annotated[list[str] | None, typer.Option("--project")] = None,
    issue_type: Annotated[list[str] | None, typer.Option("--type")] = None,
) -> None:
    """Show fields accepted when creating issues."""
    _print_result(
        ctx,
        _state(ctx)
        .client()
        .create_meta(project_keys=project, issue_type_names=issue_type),
    )


@issue_app.command("get")
def issue_get(
    ctx: typer.Context,
    issue_key: str,
    field: Annotated[list[str] | None, typer.Option("--field")] = None,
    expand: Annotated[list[str] | None, typer.Option("--expand")] = None,
) -> None:
    """Get one issue."""
    _print_result(
        ctx, _state(ctx).client().get_issue(issue_key, fields=field, expand=expand)
    )


@issue_app.command("list")
def issue_list(
    ctx: typer.Context,
    jql: Annotated[str, typer.Option(help="JQL query.")],
    start_at: Annotated[int, typer.Option(min=0)] = 0,
    max_results: Annotated[int, typer.Option(min=1, max=1000)] = 50,
    field: Annotated[list[str] | None, typer.Option("--field")] = None,
    expand: Annotated[list[str] | None, typer.Option("--expand")] = None,
) -> None:
    """Search issues using JQL."""
    state = _state(ctx)
    result = state.client().search_issues(
        jql,
        start_at=start_at,
        max_results=max_results,
        fields=field,
        expand=expand,
    )
    if state.json_output:
        _print_json(result)
        return
    table = Table("Key", "Summary", "Status", "Assignee")
    for issue in result.get("issues", []):
        fields = issue.get("fields", {})
        table.add_row(
            str(issue.get("key", "")),
            str(fields.get("summary", "")),
            str((fields.get("status") or {}).get("name", "")),
            str((fields.get("assignee") or {}).get("displayName", "")),
        )
    console.print(table)
    console.print(
        f"Showing {len(result.get('issues', []))} of {result.get('total', 0)}"
    )


@issue_app.command("create")
def issue_create(
    ctx: typer.Context,
    issue_type: Annotated[str, typer.Option("--type")],
    summary: Annotated[str, typer.Option()],
    project: Annotated[str | None, typer.Option()] = None,
    description: Annotated[str | None, typer.Option()] = None,
    description_file: Annotated[Path | None, typer.Option()] = None,
    parent: Annotated[str | None, typer.Option()] = None,
    assignee: Annotated[str | None, typer.Option()] = None,
    reporter: Annotated[str | None, typer.Option()] = None,
    priority: Annotated[str | None, typer.Option()] = None,
    label: Annotated[list[str] | None, typer.Option("--label")] = None,
    component: Annotated[list[str] | None, typer.Option("--component")] = None,
    fix_version: Annotated[list[str] | None, typer.Option("--fix-version")] = None,
    field: Annotated[
        list[str] | None,
        typer.Option("--field", help="Additional field as KEY=JSON_OR_TEXT."),
    ] = None,
) -> None:
    """Create an issue or sub-task."""
    state = _state(ctx)
    fields = _issue_fields(
        project=_require_project(state, project),
        issue_type=issue_type,
        summary=summary,
        description=_optional_body(description, description_file, "description"),
        parent=parent,
        assignee=assignee,
        reporter=reporter,
        priority=priority,
        labels=label,
        components=component,
        fix_versions=fix_version,
        custom_fields=field,
    )
    _print_result(ctx, state.client().create_issue(fields))


@issue_app.command("edit")
def issue_edit(
    ctx: typer.Context,
    issue_key: str,
    summary: Annotated[str | None, typer.Option()] = None,
    description: Annotated[str | None, typer.Option()] = None,
    description_file: Annotated[Path | None, typer.Option()] = None,
    assignee: Annotated[str | None, typer.Option()] = None,
    reporter: Annotated[str | None, typer.Option()] = None,
    priority: Annotated[str | None, typer.Option()] = None,
    label: Annotated[list[str] | None, typer.Option("--label")] = None,
    component: Annotated[list[str] | None, typer.Option("--component")] = None,
    fix_version: Annotated[list[str] | None, typer.Option("--fix-version")] = None,
    field: Annotated[list[str] | None, typer.Option("--field")] = None,
) -> None:
    """Edit selected issue fields."""
    fields = _parse_pairs(field)
    if summary is not None:
        fields["summary"] = summary
    body = _optional_body(description, description_file, "description")
    if body is not None:
        fields["description"] = body
    if assignee is not None:
        fields["assignee"] = {"name": assignee}
    if reporter is not None:
        fields["reporter"] = {"name": reporter}
    if priority is not None:
        fields["priority"] = {"name": priority}
    if label is not None:
        fields["labels"] = label
    if component is not None:
        fields["components"] = [{"name": value} for value in component]
    if fix_version is not None:
        fields["fixVersions"] = [{"name": value} for value in fix_version]
    if not fields:
        raise typer.BadParameter("No changes were provided")
    client = _state(ctx).client()
    client.get_issue(issue_key, fields=["summary"])
    client.edit_issue(issue_key, fields)
    _print_result(ctx, {"key": issue_key, "updated_fields": sorted(fields)})


@issue_app.command("assign")
def issue_assign(ctx: typer.Context, issue_key: str, username: str) -> None:
    """Assign an issue to a Jira username."""
    client = _state(ctx).client()
    client.get_issue(issue_key, fields=["assignee"])
    client.edit_issue(issue_key, {"assignee": {"name": username}})
    _print_result(ctx, {"key": issue_key, "assignee": username})


@issue_app.command("clone")
def issue_clone(
    ctx: typer.Context,
    issue_key: str,
    summary: Annotated[str | None, typer.Option()] = None,
    project: Annotated[str | None, typer.Option()] = None,
    parent: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Clone common fields into a new issue."""
    state = _state(ctx)
    source = state.client().get_issue(issue_key)
    source_fields = source.get("fields", {})
    project_key = _clone_target_project(source_fields, project)
    issue_type_name = (source_fields.get("issuetype") or {}).get("name")
    metadata = state.client().create_meta(
        project_keys=[project_key], issue_type_names=[issue_type_name]
    )
    fields = _clone_fields(
        source_fields,
        project=project_key,
        summary=summary,
        parent=parent,
        allowed_fields=_create_field_ids(metadata),
    )
    _print_result(ctx, state.client().create_issue(fields))


@issue_app.command("delete")
def issue_delete(
    ctx: typer.Context,
    issue_key: str,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    delete_subtasks: Annotated[bool, typer.Option("--delete-subtasks")] = False,
) -> None:
    """Permanently delete one issue with explicit confirmation."""
    if not yes:
        raise typer.BadParameter("Pass --yes to confirm permanent deletion")
    client = _state(ctx).client()
    issue = client.get_issue(issue_key, fields=["summary", "subtasks"])
    subtasks = issue.get("fields", {}).get("subtasks") or []
    if subtasks and not delete_subtasks:
        raise typer.BadParameter(
            "Issue has subtasks; delete them first or pass --delete-subtasks"
        )
    client.delete_issue(issue_key, delete_subtasks=delete_subtasks)
    _print_result(ctx, {"deleted_issue": issue_key})


@issue_app.command("transitions")
def issue_transitions(ctx: typer.Context, issue_key: str) -> None:
    """List valid transitions for an issue."""
    _print_result(ctx, _state(ctx).client().list_transitions(issue_key))


@issue_app.command("move")
def issue_move(
    ctx: typer.Context,
    issue_key: str,
    transition: str,
    field: Annotated[list[str] | None, typer.Option("--field")] = None,
) -> None:
    """Move an issue by exact transition name or ID."""
    selected = (
        _state(ctx)
        .client()
        .transition_issue(issue_key, transition, fields=_parse_pairs(field))
    )
    _print_result(ctx, {"key": issue_key, "transition": selected})


@epic_app.command("create")
def epic_create(
    ctx: typer.Context,
    summary: Annotated[str, typer.Option()],
    epic_name: Annotated[str, typer.Option()],
    project: Annotated[str | None, typer.Option()] = None,
    description: Annotated[str | None, typer.Option()] = None,
    description_file: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Create an Epic using configured custom field IDs."""
    state = _state(ctx)
    field = state.settings.epic_name_field
    if not field:
        raise typer.BadParameter("Configure epic_name_field before creating epics")
    fields = _issue_fields(
        project=_require_project(state, project),
        issue_type="Epic",
        summary=summary,
        description=_optional_body(description, description_file, "description"),
        parent=None,
        assignee=None,
        reporter=None,
        priority=None,
        labels=None,
        components=None,
        fix_versions=None,
        custom_fields=[f"{field}={json.dumps(epic_name)}"],
    )
    _print_result(ctx, state.client().create_issue(fields))


@epic_app.command("list")
def epic_list(
    ctx: typer.Context,
    project: Annotated[str | None, typer.Option()] = None,
    max_results: Annotated[int, typer.Option(min=1, max=1000)] = 50,
) -> None:
    """List epics in a project."""
    state = _state(ctx)
    key = _require_project(state, project)
    _print_result(
        ctx,
        state.client().search_issues(
            f'project = "{key}" AND issuetype = Epic ORDER BY updated DESC',
            max_results=max_results,
        ),
    )


def _update_epic_membership(
    client: JiraApiClient,
    issue_keys: list[str],
    field: str,
    value: str | None,
) -> list[str]:
    for key in issue_keys:
        client.get_issue(key, fields=[field])

    completed: list[str] = []
    for index, key in enumerate(issue_keys):
        try:
            client.edit_issue(key, {field: value})
        except JiraApiError as exc:
            raise JiraApiError(
                "Epic membership update partially failed",
                status_code=exc.status_code,
                payload={
                    "completed": completed,
                    "failed": key,
                    "remaining": issue_keys[index + 1 :],
                    "jira": exc.payload,
                },
            ) from None
        completed.append(key)
    return completed


@epic_app.command("add")
def epic_add(ctx: typer.Context, epic_key: str, issue_key: list[str]) -> None:
    """Assign one or more issues to an Epic."""
    state = _state(ctx)
    field = state.settings.epic_link_field
    if not field:
        raise typer.BadParameter("Configure epic_link_field before editing membership")
    client = state.client()
    client.get_issue(epic_key, fields=["issuetype"])
    added = _update_epic_membership(client, issue_key, field, epic_key)
    _print_result(ctx, {"epic": epic_key, "added": added})


@epic_app.command("remove")
def epic_remove(ctx: typer.Context, issue_key: list[str]) -> None:
    """Remove one or more issues from their Epic."""
    state = _state(ctx)
    field = state.settings.epic_link_field
    if not field:
        raise typer.BadParameter("Configure epic_link_field before editing membership")
    removed = _update_epic_membership(state.client(), issue_key, field, None)
    _print_result(ctx, {"removed": removed})


@comment_app.command("list")
def comment_list(
    ctx: typer.Context,
    issue_key: str,
    start_at: Annotated[int, typer.Option(min=0)] = 0,
    max_results: Annotated[int, typer.Option(min=1, max=1000)] = 100,
) -> None:
    """List comments on an issue."""
    _print_result(
        ctx,
        _state(ctx)
        .client()
        .list_comments(issue_key, start_at=start_at, max_results=max_results),
    )


@comment_app.command("add")
def comment_add(
    ctx: typer.Context,
    issue_key: str,
    body: Annotated[str | None, typer.Option(help="Raw Jira wiki markup.")] = None,
    body_file: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Add a comment without rewriting Jira wiki markup."""
    _print_result(
        ctx, _state(ctx).client().add_comment(issue_key, _body(body, body_file))
    )


@comment_app.command("edit")
def comment_edit(
    ctx: typer.Context,
    issue_key: str,
    comment_id: str,
    body: Annotated[str | None, typer.Option(help="Raw Jira wiki markup.")] = None,
    body_file: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Edit a comment without rewriting Jira wiki markup."""
    _print_result(
        ctx,
        _state(ctx)
        .client()
        .edit_comment(issue_key, comment_id, _body(body, body_file)),
    )


@comment_app.command("delete")
def comment_delete(
    ctx: typer.Context,
    issue_key: str,
    comment_id: str,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Permanently delete a comment."""
    if not yes:
        raise typer.BadParameter("Pass --yes to confirm permanent deletion")
    client = _state(ctx).client()
    client.list_comments(issue_key)
    client.delete_comment(issue_key, comment_id)
    _print_result(ctx, {"issue_key": issue_key, "deleted_comment": comment_id})


@attachment_app.command("list")
def attachment_list(ctx: typer.Context, issue_key: str) -> None:
    """List issue attachments."""
    _print_result(ctx, _state(ctx).client().list_attachments(issue_key))


@attachment_app.command("add")
def attachment_add(ctx: typer.Context, issue_key: str, file: Path) -> None:
    """Upload one attachment."""
    if not file.is_file():
        raise typer.BadParameter(f"File does not exist: {file}")
    _print_result(ctx, _state(ctx).client().add_attachment(issue_key, file))


@attachment_app.command("delete")
def attachment_delete(
    ctx: typer.Context,
    attachment_id: str,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Permanently delete an attachment by ID."""
    if not yes:
        raise typer.BadParameter("Pass --yes to confirm permanent deletion")
    _state(ctx).client().delete_attachment(attachment_id)
    _print_result(ctx, {"deleted_attachment": attachment_id})


@link_app.command("types")
def link_types(ctx: typer.Context) -> None:
    """List available issue link types."""
    _print_result(ctx, _state(ctx).client().list_link_types())


@link_app.command("get")
def link_get(ctx: typer.Context, link_id: str) -> None:
    """Get one issue link."""
    _print_result(ctx, _state(ctx).client().get_issue_link(link_id))


@link_app.command("add")
def link_add(
    ctx: typer.Context,
    inward_issue: str,
    outward_issue: str,
    link_type: Annotated[str, typer.Option("--type")],
    comment: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Create a directional link between two issues."""
    client = _state(ctx).client()
    client.get_issue(inward_issue, fields=["summary"])
    client.get_issue(outward_issue, fields=["summary"])
    client.create_issue_link(inward_issue, outward_issue, link_type, comment=comment)
    _print_result(
        ctx,
        {
            "inward_issue": inward_issue,
            "outward_issue": outward_issue,
            "type": link_type,
        },
    )


@link_app.command("delete")
def link_delete(
    ctx: typer.Context,
    link_id: str,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Permanently delete an issue link by ID."""
    if not yes:
        raise typer.BadParameter("Pass --yes to confirm permanent deletion")
    client = _state(ctx).client()
    client.get_issue_link(link_id)
    client.delete_issue_link(link_id)
    _print_result(ctx, {"deleted_link": link_id})


@remote_link_app.command("list")
def remote_link_list(ctx: typer.Context, issue_key: str) -> None:
    """List external links on an issue."""
    _print_result(ctx, _state(ctx).client().list_remote_links(issue_key))


@remote_link_app.command("add")
def remote_link_add(
    ctx: typer.Context,
    issue_key: str,
    url: Annotated[str, typer.Option()],
    title: Annotated[str, typer.Option()],
    summary: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Add an external link to an issue."""
    _print_result(
        ctx,
        _state(ctx)
        .client()
        .add_remote_link(
            issue_key,
            url=url,
            title=title,
            summary=summary,
        ),
    )


@remote_link_app.command("upsert")
def remote_link_upsert(
    ctx: typer.Context,
    issue_key: str,
    url: Annotated[str, typer.Option()],
    title: Annotated[str, typer.Option()],
    global_id: Annotated[str, typer.Option()],
    summary: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Create or update an external link identified by globalId."""
    _print_result(
        ctx,
        _state(ctx)
        .client()
        .upsert_remote_link(
            issue_key,
            url=url,
            title=title,
            global_id=global_id,
            summary=summary,
        ),
    )


@remote_link_app.command("delete")
def remote_link_delete(
    ctx: typer.Context,
    issue_key: str,
    link_id: str,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Permanently delete an external link."""
    if not yes:
        raise typer.BadParameter("Pass --yes to confirm permanent deletion")
    _state(ctx).client().delete_remote_link(issue_key, link_id)
    _print_result(ctx, {"issue_key": issue_key, "deleted_remote_link": link_id})


@watcher_app.command("list")
def watcher_list(ctx: typer.Context, issue_key: str) -> None:
    """List issue watchers."""
    _print_result(ctx, _state(ctx).client().get_watchers(issue_key))


@watcher_app.command("add")
def watcher_add(ctx: typer.Context, issue_key: str, username: str) -> None:
    """Add a watcher by Jira username."""
    _state(ctx).client().add_watcher(issue_key, username)
    _print_result(ctx, {"issue_key": issue_key, "added_watcher": username})


@watcher_app.command("remove")
def watcher_remove(ctx: typer.Context, issue_key: str, username: str) -> None:
    """Remove a watcher by Jira username."""
    _state(ctx).client().remove_watcher(issue_key, username)
    _print_result(ctx, {"issue_key": issue_key, "removed_watcher": username})


@vote_app.command("get")
def vote_get(ctx: typer.Context, issue_key: str) -> None:
    """Show issue vote information."""
    _print_result(ctx, _state(ctx).client().get_votes(issue_key))


@vote_app.command("add")
def vote_add(ctx: typer.Context, issue_key: str) -> None:
    """Add the current user's vote."""
    _state(ctx).client().add_vote(issue_key)
    _print_result(ctx, {"issue_key": issue_key, "voted": True})


@vote_app.command("remove")
def vote_remove(ctx: typer.Context, issue_key: str) -> None:
    """Remove the current user's vote."""
    _state(ctx).client().remove_vote(issue_key)
    _print_result(ctx, {"issue_key": issue_key, "voted": False})


@worklog_app.command("list")
def worklog_list(ctx: typer.Context, issue_key: str) -> None:
    """List issue worklogs."""
    _print_result(ctx, _state(ctx).client().list_worklogs(issue_key))


@worklog_app.command("add")
def worklog_add(
    ctx: typer.Context,
    issue_key: str,
    time_spent: Annotated[str, typer.Option(help="Jira duration, such as 30m.")],
    comment: Annotated[str | None, typer.Option()] = None,
    started: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Add a worklog."""
    _print_result(
        ctx,
        _state(ctx)
        .client()
        .add_worklog(
            issue_key, time_spent=time_spent, comment=comment, started=started
        ),
    )


@worklog_app.command("edit")
def worklog_edit(
    ctx: typer.Context,
    issue_key: str,
    worklog_id: str,
    time_spent: Annotated[str, typer.Option()],
    comment: Annotated[str | None, typer.Option()] = None,
    started: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Edit a worklog."""
    _print_result(
        ctx,
        _state(ctx)
        .client()
        .edit_worklog(
            issue_key,
            worklog_id,
            time_spent=time_spent,
            comment=comment,
            started=started,
        ),
    )


@worklog_app.command("delete")
def worklog_delete(
    ctx: typer.Context,
    issue_key: str,
    worklog_id: str,
    yes: Annotated[bool, typer.Option("--yes")] = False,
) -> None:
    """Permanently delete a worklog."""
    if not yes:
        raise typer.BadParameter("Pass --yes to confirm permanent deletion")
    _state(ctx).client().delete_worklog(issue_key, worklog_id)
    _print_result(ctx, {"issue_key": issue_key, "deleted_worklog": worklog_id})


@board_app.command("list")
def board_list(
    ctx: typer.Context,
    project: Annotated[str | None, typer.Option()] = None,
    start_at: Annotated[int, typer.Option(min=0)] = 0,
    max_results: Annotated[int, typer.Option(min=1, max=1000)] = 50,
) -> None:
    """List Jira Software boards."""
    _print_result(
        ctx,
        _state(ctx)
        .client()
        .list_boards(project_key=project, start_at=start_at, max_results=max_results),
    )


@sprint_app.command("list")
def sprint_list(
    ctx: typer.Context,
    board_id: str | None = None,
    state: Annotated[
        str | None, typer.Option(help="future, active, or closed.")
    ] = None,
    start_at: Annotated[int, typer.Option(min=0)] = 0,
    max_results: Annotated[int, typer.Option(min=1, max=1000)] = 50,
) -> None:
    """List sprints without mutating board state."""
    app_state = _state(ctx)
    resolved_board = board_id or app_state.settings.default_board
    if not resolved_board:
        raise typer.BadParameter("Board ID is required")
    _print_result(
        ctx,
        app_state.client().list_sprints(
            resolved_board,
            state=state,
            start_at=start_at,
            max_results=max_results,
        ),
    )


@api_app.command("get")
def api_get(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Relative path starting with rest/.")],
    param: Annotated[list[str] | None, typer.Option("--param")] = None,
) -> None:
    """Call an unwrapped read-only Jira REST endpoint."""
    pairs = _parse_pairs(param)
    _print_result(
        ctx,
        _state(ctx)
        .client()
        .raw_get(path, {key: str(value) for key, value in pairs.items()}),
    )


def main() -> None:
    global _json_errors
    _json_errors = "--json" in sys.argv[1:]
    try:
        app(standalone_mode=False)
    except JiraApiError as exc:
        payload = {
            "error": str(exc),
            "status_code": exc.status_code,
            "jira": exc.payload,
        }
        if _json_errors:
            _print_json(payload, error=True)
        else:
            err_console.print(f"[bold red]Jira API error:[/] {exc}")
            if exc.payload is not None:
                err_console.print(Pretty(exc.payload, expand_all=True))
        raise SystemExit(1) from None
    except ValueError as exc:
        if _json_errors:
            _print_json({"error": str(exc)}, error=True)
        else:
            err_console.print(f"[bold red]Error:[/] {exc}")
        raise SystemExit(2) from None
    except OSError as exc:
        if _json_errors:
            _print_json({"error": str(exc)}, error=True)
        else:
            err_console.print(f"[bold red]I/O error:[/] {exc}")
        raise SystemExit(2) from None
    except typer.Abort:
        if _json_errors:
            _print_json({"error": "Aborted"}, error=True)
        else:
            err_console.print("[bold red]Aborted[/]")
        raise SystemExit(1) from None
    except typer.core._click.ClickException as exc:
        if _json_errors:
            _print_json({"error": exc.format_message()}, error=True)
        else:
            exc.show()
        raise SystemExit(exc.exit_code) from None


if __name__ == "__main__":
    main()
