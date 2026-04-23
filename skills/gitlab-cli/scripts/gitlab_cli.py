#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "rich>=14.2.0",
#     "typer>=0.20.0",
# ]
# ///

"""封装高频 GitLab `glab api` 场景的单入口 CLI。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import typer
from rich.console import Console
from rich.table import Table

console = Console()
error_console = Console(stderr=True)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="通过稳定子命令封装高频 GitLab API 用法。",
)
ci_app = typer.Typer(add_completion=False, no_args_is_help=True, help="CI 配置校验。")
mr_app = typer.Typer(add_completion=False, no_args_is_help=True, help="MR 创建与更新。")
issue_app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="Issue 创建与更新。"
)

app.add_typer(ci_app, name="ci")
app.add_typer(mr_app, name="mr")
app.add_typer(issue_app, name="issue")

ToggleChoice = Literal["true", "false"]


def encode_project(project: str) -> str:
    """把项目路径编码成 GitLab API 可接受的形式。"""

    project = project.strip()
    if not project:
        raise RuntimeError("project must not be empty")
    if project.isdigit():
        return project
    return quote(project, safe="")


def project_endpoint(project: str | None, suffix: str) -> str:
    """生成带项目上下文的 API endpoint。"""

    prefix = f"projects/{encode_project(project)}" if project else "projects/:id"
    clean_suffix = suffix.lstrip("/")
    return f"{prefix}/{clean_suffix}"


def run_command(
    args: list[str], cwd: Path, stdin_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    """执行子进程并返回结果。"""

    return subprocess.run(
        args,
        cwd=str(cwd),
        input=stdin_text,
        text=True,
        capture_output=True,
        check=False,
    )


def run_git(args: list[str], cwd: Path) -> str:
    """在目标仓库内执行 Git 并返回标准输出。"""

    result = run_command(["git", *args], cwd=cwd)
    if result.returncode != 0:
        stderr = result.stderr.strip() or "git command failed"
        raise RuntimeError(stderr)
    return result.stdout.strip()


def current_branch(cwd: Path) -> str:
    """解析当前仓库分支名。"""

    branch = run_git(["branch", "--show-current"], cwd=cwd).strip()
    if not branch:
        raise RuntimeError(
            "failed to resolve current git branch; pass --source-branch explicitly"
        )
    return branch


def bool_from_choice(value: ToggleChoice | None) -> bool | None:
    """把 `true` / `false` 字符串转换成布尔值。"""

    if value is None:
        return None
    return value == "true"


def read_text(path: Path) -> str:
    """读取 UTF-8 文本文件。"""

    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"failed to read file: {path}") from exc


def ensure_payload_fields(payload: dict[str, object]) -> dict[str, object]:
    """移除值为 `None` 的字段，并确保剩余字段非空。"""

    clean_payload = {key: value for key, value in payload.items() if value is not None}
    if not clean_payload:
        raise RuntimeError("no fields to submit")
    return clean_payload


def run_glab_api(
    *,
    endpoint: str,
    method: str,
    payload: dict[str, object] | None,
    cwd: Path,
    hostname: str | None,
) -> dict[str, object]:
    """通过 `glab api` 调用 GitLab REST API 并返回 JSON。"""

    args = ["glab", "api", endpoint, "--method", method]
    if hostname:
        args.extend(["--hostname", hostname])

    stdin_text: str | None = None
    if payload is not None:
        args.extend(["--input", "-"])
        args.extend(["--header", "Content-Type: application/json"])
        stdin_text = json.dumps(payload, ensure_ascii=True)

    result = run_command(args, cwd=cwd, stdin_text=stdin_text)
    if result.returncode != 0:
        stderr = (
            result.stderr.strip() or result.stdout.strip() or "glab api call failed"
        )
        raise RuntimeError(stderr)

    raw = result.stdout.strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("glab api did not return valid JSON") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError("unexpected API response shape")
    return parsed


def print_json(payload: dict[str, object]) -> None:
    """输出紧凑 JSON。"""

    typer.echo(json.dumps(payload, ensure_ascii=True))


def print_ci_result(payload: dict[str, object], show_merged_yaml: bool) -> None:
    """输出 CI lint 结果摘要。"""

    table = Table(show_header=False, box=None)
    table.add_row("valid", str(payload.get("valid")))
    table.add_row("errors", str(len(payload.get("errors", []))))
    table.add_row("warnings", str(len(payload.get("warnings", []))))

    jobs = payload.get("jobs")
    if isinstance(jobs, list):
        table.add_row("jobs", str(len(jobs)))

    console.print(table)

    errors = payload.get("errors", [])
    if isinstance(errors, list) and errors:
        error_console.print("errors:")
        for item in errors:
            error_console.print(f"- {item}")

    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        console.print("warnings:")
        for item in warnings:
            console.print(f"- {item}")

    if show_merged_yaml:
        merged_yaml = payload.get("merged_yaml")
        if isinstance(merged_yaml, str) and merged_yaml:
            console.print("\nmerged_yaml:")
            console.print(merged_yaml.rstrip())


def print_resource_result(resource_name: str, payload: dict[str, object]) -> None:
    """输出 MR / Issue 创建或更新结果。"""

    table = Table(show_header=False, box=None)
    title = payload.get("title")
    iid = payload.get("iid")
    web_url = payload.get("web_url")
    state = payload.get("state")

    if title is not None:
        table.add_row("title", str(title))
    if iid is not None:
        table.add_row("iid", str(iid))
    if state is not None:
        table.add_row("state", str(state))
    if web_url is not None:
        table.add_row("url", str(web_url))

    console.print(f"{resource_name}:")
    console.print(table)
    if isinstance(web_url, str) and web_url:
        console.print(web_url)


@ci_app.command("lint")
def ci_lint(
    path: Path = typer.Argument(Path(".gitlab-ci.yml"), help="要校验的 CI 配置文件。"),
    cwd: Path = typer.Option(
        Path.cwd(),
        "--cwd",
        resolve_path=True,
        file_okay=False,
        dir_okay=True,
        help="让 glab 在哪个仓库目录下执行。",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="GitLab project id 或 group/project。未提供时尝试使用当前仓库。",
    ),
    hostname: str | None = typer.Option(None, "--hostname", help="GitLab 实例 host。"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="是否做 pipeline simulation。"
    ),
    include_jobs: bool = typer.Option(False, "--include-jobs", help="返回 jobs 列表。"),
    ref: str | None = typer.Option(None, "--ref", help="dry-run 时使用的分支或 tag。"),
    show_merged_yaml: bool = typer.Option(
        False, "--show-merged-yaml", help="同时输出 merged_yaml。"
    ),
    as_json: bool = typer.Option(False, "--json", help="输出原始 JSON。"),
) -> None:
    """校验本地 `.gitlab-ci.yml`。"""

    try:
        payload = {
            "content": read_text(path),
            "dry_run": dry_run,
            "include_jobs": include_jobs,
            "ref": ref,
        }
        response = run_glab_api(
            endpoint=project_endpoint(project, "ci/lint"),
            method="POST",
            payload=ensure_payload_fields(payload),
            cwd=cwd,
            hostname=hostname,
        )
    except RuntimeError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc

    if as_json:
        print_json(response)
        return

    print_ci_result(response, show_merged_yaml=show_merged_yaml)
    if response.get("valid") is False:
        raise typer.Exit(code=1)


@mr_app.command("create")
def mr_create(
    title: str = typer.Option(..., "--title", help="MR 标题。"),
    target_branch: str = typer.Option(..., "--target-branch", help="目标分支。"),
    cwd: Path = typer.Option(
        Path.cwd(),
        "--cwd",
        resolve_path=True,
        file_okay=False,
        dir_okay=True,
        help="让 glab/git 在哪个仓库目录下执行。",
    ),
    source_branch: str | None = typer.Option(
        None, "--source-branch", help="源分支。未提供时自动读取当前分支。"
    ),
    description_file: Path | None = typer.Option(
        None, "--description-file", resolve_path=True, help="从文件读取 MR 正文。"
    ),
    project: str | None = typer.Option(
        None, "--project", help="GitLab project id 或 group/project。"
    ),
    hostname: str | None = typer.Option(None, "--hostname", help="GitLab 实例 host。"),
    label: list[str] = typer.Option([], "--label", help="标签；可重复指定。"),
    reviewer_id: list[int] = typer.Option(
        [], "--reviewer-id", help="reviewer 用户 ID；可重复指定。"
    ),
    assignee_id: list[int] = typer.Option(
        [], "--assignee-id", help="assignee 用户 ID；可重复指定。"
    ),
    milestone_id: int | None = typer.Option(None, "--milestone-id", help="里程碑 ID。"),
    remove_source_branch: ToggleChoice | None = typer.Option(
        None, "--remove-source-branch", help="是否在合并后删分支。"
    ),
    squash: ToggleChoice | None = typer.Option(
        None, "--squash", help="是否合并时 squash。"
    ),
    draft: bool = typer.Option(False, "--draft", help="自动补 `Draft:` 前缀。"),
    as_json: bool = typer.Option(False, "--json", help="输出原始 JSON。"),
) -> None:
    """创建 MR。"""

    try:
        resolved_title = title
        if draft and not resolved_title.startswith(("Draft:", "[Draft]", "(Draft)")):
            resolved_title = f"Draft: {resolved_title}"

        payload = ensure_payload_fields(
            {
                "title": resolved_title,
                "target_branch": target_branch,
                "source_branch": source_branch or current_branch(cwd),
                "description": read_text(description_file) if description_file else None,
                "labels": ",".join(label) if label else None,
                "reviewer_ids": reviewer_id or None,
                "assignee_ids": assignee_id or None,
                "milestone_id": milestone_id,
                "remove_source_branch": bool_from_choice(remove_source_branch),
                "squash": bool_from_choice(squash),
            }
        )
        response = run_glab_api(
            endpoint=project_endpoint(project, "merge_requests"),
            method="POST",
            payload=payload,
            cwd=cwd,
            hostname=hostname,
        )
    except RuntimeError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc

    if as_json:
        print_json(response)
        return
    print_resource_result("merge_request", response)


@mr_app.command("update")
def mr_update(
    iid: int = typer.Argument(..., help="要更新的 MR IID。"),
    cwd: Path = typer.Option(
        Path.cwd(),
        "--cwd",
        resolve_path=True,
        file_okay=False,
        dir_okay=True,
        help="让 glab 在哪个仓库目录下执行。",
    ),
    project: str | None = typer.Option(
        None, "--project", help="GitLab project id 或 group/project。"
    ),
    hostname: str | None = typer.Option(None, "--hostname", help="GitLab 实例 host。"),
    title: str | None = typer.Option(None, "--title", help="新的 MR 标题。"),
    description_file: Path | None = typer.Option(
        None, "--description-file", resolve_path=True, help="从文件读取新的 MR 正文。"
    ),
    label: list[str] = typer.Option(
        [], "--label", help="替换后的标签列表；可重复指定。"
    ),
    clear_labels: bool = typer.Option(False, "--clear-labels", help="清空标签。"),
    reviewer_id: list[int] = typer.Option(
        [], "--reviewer-id", help="替换后的 reviewer ID 列表；可重复指定。"
    ),
    assignee_id: list[int] = typer.Option(
        [], "--assignee-id", help="替换后的 assignee ID 列表；可重复指定。"
    ),
    milestone_id: int | None = typer.Option(
        None, "--milestone-id", help="新的里程碑 ID。"
    ),
    remove_source_branch: ToggleChoice | None = typer.Option(
        None, "--remove-source-branch", help="是否在合并后删分支。"
    ),
    squash: ToggleChoice | None = typer.Option(
        None, "--squash", help="是否合并时 squash。"
    ),
    as_json: bool = typer.Option(False, "--json", help="输出原始 JSON。"),
) -> None:
    """更新 MR。"""

    try:
        payload = ensure_payload_fields(
            {
                "title": title,
                "description": read_text(description_file) if description_file else None,
                "labels": "" if clear_labels else ",".join(label) if label else None,
                "reviewer_ids": reviewer_id or None,
                "assignee_ids": assignee_id or None,
                "milestone_id": milestone_id,
                "remove_source_branch": bool_from_choice(remove_source_branch),
                "squash": bool_from_choice(squash),
            }
        )
        response = run_glab_api(
            endpoint=project_endpoint(project, f"merge_requests/{iid}"),
            method="PUT",
            payload=payload,
            cwd=cwd,
            hostname=hostname,
        )
    except RuntimeError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc

    if as_json:
        print_json(response)
        return
    print_resource_result("merge_request", response)


@issue_app.command("create")
def issue_create(
    title: str = typer.Option(..., "--title", help="Issue 标题。"),
    cwd: Path = typer.Option(
        Path.cwd(),
        "--cwd",
        resolve_path=True,
        file_okay=False,
        dir_okay=True,
        help="让 glab 在哪个仓库目录下执行。",
    ),
    description_file: Path | None = typer.Option(
        None, "--description-file", resolve_path=True, help="从文件读取 Issue 正文。"
    ),
    project: str | None = typer.Option(
        None, "--project", help="GitLab project id 或 group/project。"
    ),
    hostname: str | None = typer.Option(None, "--hostname", help="GitLab 实例 host。"),
    label: list[str] = typer.Option([], "--label", help="标签；可重复指定。"),
    assignee_id: list[int] = typer.Option(
        [], "--assignee-id", help="assignee 用户 ID；可重复指定。"
    ),
    milestone_id: int | None = typer.Option(None, "--milestone-id", help="里程碑 ID。"),
    confidential: bool = typer.Option(
        False, "--confidential", help="创建 confidential issue。"
    ),
    due_date: str | None = typer.Option(
        None, "--due-date", help="截止日期，格式 YYYY-MM-DD。"
    ),
    as_json: bool = typer.Option(False, "--json", help="输出原始 JSON。"),
) -> None:
    """创建 Issue。"""

    try:
        payload = ensure_payload_fields(
            {
                "title": title,
                "description": read_text(description_file) if description_file else None,
                "labels": ",".join(label) if label else None,
                "assignee_ids": assignee_id or None,
                "milestone_id": milestone_id,
                "confidential": confidential or None,
                "due_date": due_date,
            }
        )
        response = run_glab_api(
            endpoint=project_endpoint(project, "issues"),
            method="POST",
            payload=payload,
            cwd=cwd,
            hostname=hostname,
        )
    except RuntimeError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc

    if as_json:
        print_json(response)
        return
    print_resource_result("issue", response)


@issue_app.command("update")
def issue_update(
    iid: int = typer.Argument(..., help="要更新的 Issue IID。"),
    cwd: Path = typer.Option(
        Path.cwd(),
        "--cwd",
        resolve_path=True,
        file_okay=False,
        dir_okay=True,
        help="让 glab 在哪个仓库目录下执行。",
    ),
    project: str | None = typer.Option(
        None, "--project", help="GitLab project id 或 group/project。"
    ),
    hostname: str | None = typer.Option(None, "--hostname", help="GitLab 实例 host。"),
    title: str | None = typer.Option(None, "--title", help="新的 Issue 标题。"),
    description_file: Path | None = typer.Option(
        None,
        "--description-file",
        resolve_path=True,
        help="从文件读取新的 Issue 正文。",
    ),
    label: list[str] = typer.Option(
        [], "--label", help="替换后的标签列表；可重复指定。"
    ),
    clear_labels: bool = typer.Option(False, "--clear-labels", help="清空标签。"),
    assignee_id: list[int] = typer.Option(
        [], "--assignee-id", help="替换后的 assignee ID 列表；可重复指定。"
    ),
    milestone_id: int | None = typer.Option(
        None, "--milestone-id", help="新的里程碑 ID。"
    ),
    confidential: ToggleChoice | None = typer.Option(
        None, "--confidential", help="是否设置为 confidential。"
    ),
    due_date: str | None = typer.Option(
        None, "--due-date", help="截止日期，格式 YYYY-MM-DD。"
    ),
    as_json: bool = typer.Option(False, "--json", help="输出原始 JSON。"),
) -> None:
    """更新 Issue。"""

    try:
        payload = ensure_payload_fields(
            {
                "title": title,
                "description": read_text(description_file) if description_file else None,
                "labels": "" if clear_labels else ",".join(label) if label else None,
                "assignee_ids": assignee_id or None,
                "milestone_id": milestone_id,
                "confidential": bool_from_choice(confidential),
                "due_date": due_date,
            }
        )
        response = run_glab_api(
            endpoint=project_endpoint(project, f"issues/{iid}"),
            method="PUT",
            payload=payload,
            cwd=cwd,
            hostname=hostname,
        )
    except RuntimeError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc

    if as_json:
        print_json(response)
        return
    print_resource_result("issue", response)


if __name__ == "__main__":
    app()
