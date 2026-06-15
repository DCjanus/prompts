#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "rich>=15.0.0",
#     "typer>=0.26.7",
# ]
# ///

"""配置 GitLab project 的 squash merge policy。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import quote

import typer
from rich.console import Console
from rich.table import Table

console = Console()
error_console = Console(stderr=True)

SQUASH_COMMIT_TEMPLATE = "%{title}\n\n%{description}\n\n%{co_authored_by}"

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="配置 GitLab project 的 semi-linear + always squash merge policy。",
)


def encode_project(project: str) -> str:
    """把项目路径编码成 GitLab API 可接受的形式。"""

    project = project.strip()
    if not project:
        raise RuntimeError("project must not be empty")
    if project.isdigit():
        return project
    return quote(project, safe="")


def policy_payload() -> dict[str, object]:
    """生成长期维护分支使用的 MR squash / merge 策略配置。"""

    return {
        "merge_method": "rebase_merge",
        "squash_option": "always",
        "squash_commit_template": SQUASH_COMMIT_TEMPLATE,
        "remove_source_branch_after_merge": True,
    }


def expected_settings() -> dict[str, object]:
    """生成回读校验需要满足的配置。"""

    return {
        **policy_payload(),
        "merge_commit_template": None,
    }


def run_glab_api(
    *,
    project: str,
    method: str,
    payload: dict[str, object] | None,
    cwd: Path,
    hostname: str | None,
) -> dict[str, object]:
    """通过 `glab api` 调用 GitLab project API。"""

    args = [
        "glab",
        "api",
        f"projects/{encode_project(project)}",
        "--method",
        method,
    ]
    stdin_text: str | None = None
    if payload is not None:
        args.extend(["--input", "-"])
        args.extend(["--header", "Content-Type: application/json"])
        stdin_text = json.dumps(payload, ensure_ascii=True)
    if hostname:
        args.extend(["--hostname", hostname])

    result = subprocess.run(
        args,
        cwd=str(cwd),
        input=stdin_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "glab api failed"
        raise RuntimeError(message)

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("glab api did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("unexpected API response shape")
    return parsed


def apply_policy(*, project: str, cwd: Path, hostname: str | None) -> dict[str, object]:
    """写入配置后回读确认。"""

    run_glab_api(
        project=project,
        method="PUT",
        payload=policy_payload(),
        cwd=cwd,
        hostname=hostname,
    )
    response = run_glab_api(
        project=project,
        method="GET",
        payload=None,
        cwd=cwd,
        hostname=hostname,
    )
    validate_settings(response)
    return response


def validate_settings(payload: dict[str, object]) -> None:
    """确认 GitLab project 配置符合预期。"""

    mismatches: list[str] = []
    for key, expected in expected_settings().items():
        actual = payload.get(key)
        if actual != expected:
            mismatches.append(f"- {key}: expected {expected!r}, got {actual!r}")

    if mismatches:
        raise RuntimeError(
            "GitLab project squash merge policy verification failed:\n"
            + "\n".join(mismatches)
        )


def print_result(payload: dict[str, object]) -> None:
    """输出 project merge / squash 配置摘要。"""

    table = Table(show_header=False, box=None)
    for key in (
        "merge_method",
        "squash_option",
        "squash_commit_template",
        "remove_source_branch_after_merge",
        "merge_commit_template",
    ):
        if key in payload:
            table.add_row(key, str(payload.get(key)))
    console.print("project:")
    console.print(table)


@app.command()
def main(
    project: str = typer.Option(
        ..., "--project", help="GitLab project id 或 group/project。"
    ),
    cwd: Path = typer.Option(
        Path.cwd(),
        "--cwd",
        resolve_path=True,
        file_okay=False,
        dir_okay=True,
        help="让 glab 在哪个目录下执行。",
    ),
    hostname: str | None = typer.Option(None, "--hostname", help="GitLab 实例 host。"),
    as_json: bool = typer.Option(False, "--json", help="输出原始 JSON。"),
) -> None:
    """应用 semi-linear + always squash merge policy。"""

    try:
        response = apply_policy(project=project, cwd=cwd, hostname=hostname)
    except RuntimeError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc

    if as_json:
        typer.echo(json.dumps(response, ensure_ascii=True))
        return
    print_result(response)


if __name__ == "__main__":
    app()
