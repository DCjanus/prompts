#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "rich>=15.0.0",
#     "typer>=0.26.7",
# ]
# ///

"""配置 GitHub repository 的 squash merge policy。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()
error_console = Console(stderr=True)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="配置 GitHub repository 的 squash-only merge policy。",
)


def normalize_repo(repo: str) -> str:
    """校验并标准化 owner/repo。"""

    repo = repo.strip().removeprefix("https://github.com/")
    repo = repo.removesuffix(".git").strip("/")
    parts = repo.split("/")
    if len(parts) != 2 or not all(parts):
        raise RuntimeError("repo must be in owner/repo format")
    return repo


def policy_payload() -> dict[str, object]:
    """生成 repo-level squash merge 策略配置。"""

    return {
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": False,
        "squash_merge_commit_title": "PR_TITLE",
        "squash_merge_commit_message": "PR_BODY",
        "delete_branch_on_merge": True,
    }


def expected_settings() -> dict[str, object]:
    """生成回读校验需要满足的配置。"""

    return policy_payload()


def run_gh_api(
    *,
    repo: str,
    method: str,
    payload: dict[str, object] | None,
    cwd: Path,
    hostname: str | None,
) -> dict[str, object]:
    """通过 `gh api` 调用 GitHub repository API。"""

    endpoint = f"repos/{normalize_repo(repo)}"
    args = ["gh", "api", endpoint, "--method", method]
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
        message = result.stderr.strip() or result.stdout.strip() or "gh api failed"
        raise RuntimeError(message)

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gh api did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("unexpected API response shape")
    return parsed


def apply_policy(*, repo: str, cwd: Path, hostname: str | None) -> dict[str, object]:
    """写入配置后回读确认。"""

    run_gh_api(
        repo=repo,
        method="PATCH",
        payload=policy_payload(),
        cwd=cwd,
        hostname=hostname,
    )
    response = run_gh_api(
        repo=repo,
        method="GET",
        payload=None,
        cwd=cwd,
        hostname=hostname,
    )
    validate_settings(response)
    return response


def validate_settings(payload: dict[str, object]) -> None:
    """确认 GitHub repository 配置符合预期。"""

    mismatches: list[str] = []
    for key, expected in expected_settings().items():
        actual = payload.get(key)
        if actual != expected:
            mismatches.append(f"- {key}: expected {expected!r}, got {actual!r}")

    if mismatches:
        raise RuntimeError(
            "GitHub repository squash merge policy verification failed:\n"
            + "\n".join(mismatches)
        )


def print_result(payload: dict[str, object]) -> None:
    """输出 repository merge 配置摘要。"""

    table = Table(show_header=False, box=None)
    for key in (
        "allow_squash_merge",
        "allow_merge_commit",
        "allow_rebase_merge",
        "squash_merge_commit_title",
        "squash_merge_commit_message",
        "delete_branch_on_merge",
    ):
        if key in payload:
            table.add_row(key, str(payload.get(key)))
    console.print("repository:")
    console.print(table)


@app.command()
def main(
    repo: str = typer.Option(
        ..., "--repo", help="GitHub repository，格式 owner/repo。"
    ),
    cwd: Path = typer.Option(
        Path.cwd(),
        "--cwd",
        resolve_path=True,
        file_okay=False,
        dir_okay=True,
        help="让 gh 在哪个目录下执行。",
    ),
    hostname: str | None = typer.Option(None, "--hostname", help="GitHub host。"),
    as_json: bool = typer.Option(False, "--json", help="输出原始 JSON。"),
) -> None:
    """应用 squash-only merge policy。"""

    try:
        response = apply_policy(repo=repo, cwd=cwd, hostname=hostname)
    except RuntimeError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc

    if as_json:
        typer.echo(json.dumps(response, ensure_ascii=True))
        return
    print_result(response)


if __name__ == "__main__":
    app()
