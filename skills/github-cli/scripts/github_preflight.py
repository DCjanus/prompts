#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pyyaml>=6.0.3",
#     "rich>=15.0.0",
#     "typer>=0.27.0",
# ]
# ///
"""输出中文 GitHub issue/PR 创建前静态检查摘要。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console


app = typer.Typer(
    add_completion=False, help="输出中文 GitHub issue/PR 创建前静态检查摘要"
)
console = Console(markup=False, width=120)

ISSUE_TEMPLATE_DIR = Path(".github/ISSUE_TEMPLATE")
WORKFLOW_DIR = Path(".github/workflows")

ISSUE_EVENTS = {"issues", "issue_comment"}
PR_EVENTS = {
    "pull_request",
    "pull_request_target",
    "pull_request_review",
    "pull_request_review_comment",
    "merge_group",
}
COMMON_EVENTS = {"workflow_run", "workflow_dispatch"}


@dataclass
class IssueTemplate:
    path: Path
    name: str | None
    description: str | None
    labels: list[str]
    required_fields: list[str]


@dataclass
class WorkflowJob:
    key: str
    name: str | None


@dataclass
class WorkflowInfo:
    path: Path
    name: str | None
    events: list[str]
    jobs: list[WorkflowJob]


def read_text(path: Path) -> str:
    """读取文本文件，容忍编码异常。"""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(errors="replace")


def read_yaml(path: Path) -> dict[str, Any]:
    """读取 YAML，失败时返回空对象。"""
    try:
        data = yaml.safe_load(read_text(path))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def as_list(value: Any) -> list[Any]:
    """把 YAML 标量规整为列表。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def github_on(data: dict[str, Any]) -> Any:
    """读取 workflow on 字段；PyYAML 会把未引号包裹的 on 解析成 True。"""
    return data.get("on", data.get(True))


def issue_template_required_fields(data: dict[str, Any]) -> list[str]:
    """提取 Issue Form 必填字段标签。"""
    fields: list[str] = []
    for item in as_list(data.get("body")):
        if not isinstance(item, dict):
            continue
        attrs = (
            item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        )
        validations = (
            item.get("validations") if isinstance(item.get("validations"), dict) else {}
        )
        if validations.get("required") is True and attrs.get("label"):
            fields.append(str(attrs["label"]))
        for option in as_list(attrs.get("options")):
            if (
                isinstance(option, dict)
                and option.get("required") is True
                and option.get("label")
            ):
                fields.append(str(option["label"]))
    return fields


def load_issue_templates(repo: Path) -> list[IssueTemplate]:
    """加载 Issue Form 模板摘要。"""
    directory = repo / ISSUE_TEMPLATE_DIR
    if not directory.is_dir():
        return []
    templates: list[IssueTemplate] = []
    for path in sorted(directory.glob("*.y*ml")):
        if path.name == "config.yml":
            continue
        data = read_yaml(path)
        templates.append(
            IssueTemplate(
                path=path.relative_to(repo),
                name=str(data["name"]) if data.get("name") else None,
                description=str(data["description"])
                if data.get("description")
                else None,
                labels=[str(label) for label in as_list(data.get("labels"))],
                required_fields=issue_template_required_fields(data),
            )
        )
    return templates


def workflow_events(data: dict[str, Any]) -> list[str]:
    """从 workflow YAML 提取触发事件。"""
    raw = github_on(data)
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return sorted(str(item) for item in raw)
    if isinstance(raw, dict):
        return sorted(str(key) for key in raw)
    return []


def workflow_relevant(events: list[str], mode: str, text: str) -> bool:
    """判断 workflow 是否与 issue/PR 创建相关。"""
    event_set = set(events)
    candidates = ISSUE_EVENTS if mode == "issue" else PR_EVENTS
    if event_set & candidates:
        return True
    if event_set & COMMON_EVENTS:
        lower = text.lower()
        return any(
            word in lower
            for word in (
                "issue",
                "pull_request",
                "pull-requests",
                "check-issue",
                "pull request",
            )
        )
    return False


def workflow_jobs(data: dict[str, Any]) -> list[WorkflowJob]:
    """提取 workflow job 的定位信息。"""
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return []
    found: list[WorkflowJob] = []
    for key, value in sorted(jobs.items()):
        name = None
        if isinstance(value, dict) and value.get("name"):
            name = str(value["name"])
        found.append(WorkflowJob(key=str(key), name=name))
    return found


def load_workflows(repo: Path, mode: str) -> list[WorkflowInfo]:
    """加载相关 workflow 摘要。"""
    directory = repo / WORKFLOW_DIR
    if not directory.is_dir():
        return []
    workflows: list[WorkflowInfo] = []
    for path in sorted(directory.glob("*.y*ml")):
        text = read_text(path)
        data = read_yaml(path)
        events = workflow_events(data)
        if not workflow_relevant(events, mode, text):
            continue
        workflows.append(
            WorkflowInfo(
                path=path.relative_to(repo),
                name=str(data["name"]) if data.get("name") else None,
                events=events,
                jobs=workflow_jobs(data),
            )
        )
    return workflows


def section(title: str) -> None:
    """输出二级标题。"""
    console.print(f"## {title}")


def print_checked(
    repo: Path,
    mode: str,
    templates: list[IssueTemplate],
    workflows: list[WorkflowInfo],
) -> None:
    section("已检查")
    config_path = repo / ISSUE_TEMPLATE_DIR / "config.yml"
    pr_template_file = repo / ".github/PULL_REQUEST_TEMPLATE.md"
    pr_template_dir = repo / ".github/PULL_REQUEST_TEMPLATE"
    workflow_count = (
        len(list((repo / WORKFLOW_DIR).glob("*.y*ml")))
        if (repo / WORKFLOW_DIR).is_dir()
        else 0
    )
    if mode == "issue":
        console.print(
            f"- {ISSUE_TEMPLATE_DIR / 'config.yml'}：{'存在' if config_path.is_file() else '不存在'}"
        )
        console.print(
            f"- {ISSUE_TEMPLATE_DIR}/：发现 {len(templates)} 个模板"
            if (repo / ISSUE_TEMPLATE_DIR).is_dir()
            else f"- {ISSUE_TEMPLATE_DIR}/：不存在"
        )
    else:
        console.print(
            f"- {pr_template_file.relative_to(repo)}：{'存在' if pr_template_file.is_file() else '不存在'}"
        )
        console.print(
            f"- {pr_template_dir.relative_to(repo)}/：{'存在' if pr_template_dir.is_dir() else '不存在'}"
        )
    console.print(f"- {WORKFLOW_DIR}/：发现 {workflow_count} 个 workflow")
    console.print(f"- {mode} 相关 workflow：发现 {len(workflows)} 个")
    console.print(
        "- 外部 GitHub App / branch protection / ruleset：无法通过本地静态扫描确认\n"
    )


def print_issue_config(repo: Path) -> None:
    section("Issue 模板配置")
    config = repo / ISSUE_TEMPLATE_DIR / "config.yml"
    if not config.is_file():
        console.print("- 未发现 .github/ISSUE_TEMPLATE/config.yml\n")
        return
    data = read_yaml(config)
    blank = data.get("blank_issues_enabled", "未声明")
    if isinstance(blank, bool):
        blank = str(blank).lower()
    console.print(f"- blank_issues_enabled：{blank}")
    console.print(f"- contact_links：{'有' if data.get('contact_links') else '无'}\n")


def print_issue_templates(templates: list[IssueTemplate]) -> None:
    section("Issue 模板")
    if not templates:
        console.print("- 未发现 Issue Form 模板\n")
        return
    for template in templates:
        suffix = f"：{template.name}" if template.name else ""
        console.print(f"- {template.path}{suffix}")
    console.print()


def print_pr_templates(repo: Path) -> None:
    section("PR 模板")
    paths: list[Path] = []
    md = repo / ".github/PULL_REQUEST_TEMPLATE.md"
    if md.is_file():
        paths.append(md)
    directory = repo / ".github/PULL_REQUEST_TEMPLATE"
    if directory.is_dir():
        paths.extend(sorted(directory.glob("*.md")))
    if not paths:
        console.print("- 未发现 PR 模板\n")
        return
    for path in paths:
        rel = path.relative_to(repo)
        console.print(f"- {rel}")
    console.print()


def print_workflows(workflows: list[WorkflowInfo], mode: str) -> None:
    section(f"{'Issue' if mode == 'issue' else 'PR'} 相关 workflow")
    if not workflows:
        console.print("- 未发现相关 workflow\n")
        return
    for workflow in workflows:
        console.print(f"- {workflow.path}")
        if workflow.name:
            console.print(f"  workflow：{workflow.name}")
        console.print(
            f"  触发事件：{', '.join(workflow.events) if workflow.events else '未静态识别'}"
        )
        if workflow.jobs:
            console.print("  jobs：")
            for job in workflow.jobs:
                suffix = f"：{job.name}" if job.name else ""
                console.print(f"    - {job.key}{suffix}")
    console.print()


def print_recommendations(mode: str, workflows: list[WorkflowInfo]) -> None:
    section("建议")
    if mode == "issue":
        if workflows:
            console.print(
                "- 如果 workflow 依赖 Issue Form 自动应用的标签或字段，优先使用网页 Issue Form，不要用普通 `gh issue create` 绕过表单。"
            )
        console.print(
            "- 创建后等待 10-30 秒并复查：`gh issue view <number> --json state,stateReason,labels,comments,url`"
        )
        console.print(
            "- 如果缺少模板要求的标签、被自动关闭、或出现自动检查评论，先修正或重开，不要直接报告完成。"
        )
    else:
        console.print(
            "- PR 正文不要绕过模板；若 workflow 使用 `pull_request_target` 或 `issues: write`，创建后重点检查标签、评论和 checks。"
        )
        console.print(
            "- 创建后等待 10-30 秒并复查：`gh pr view <number> --json state,labels,comments,url,statusCheckRollup`"
        )
        console.print(
            "- 分支保护、ruleset 和外部 GitHub App 不能靠本地静态扫描完全确认。"
        )


@app.command()
def main(
    mode: Annotated[
        str,
        typer.Option("--mode", help="检查 issue 或 PR 创建约束", case_sensitive=False),
    ],
    repo: Annotated[Path, typer.Option("--repo", help="仓库路径，默认当前目录")] = Path(
        "."
    ),
) -> None:
    """输出中文 GitHub issue/PR 创建前静态检查摘要。"""
    mode = mode.lower()
    if mode not in {"issue", "pr"}:
        raise typer.BadParameter("--mode 必须是 issue 或 pr")
    repo = repo.resolve()
    if not (repo / ".git").exists() and not (repo / ".github").exists():
        raise typer.BadParameter(f"不是可识别的仓库目录：{repo}")

    templates = load_issue_templates(repo) if mode == "issue" else []
    workflows = load_workflows(repo, mode)

    console.print(f"# GitHub 创建前检查：{mode}\n")
    print_checked(repo, mode, templates, workflows)
    if mode == "issue":
        print_issue_config(repo)
        print_issue_templates(templates)
    else:
        print_pr_templates(repo)
    print_workflows(workflows, mode)
    print_recommendations(mode, workflows)


if __name__ == "__main__":
    app()
