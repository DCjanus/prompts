#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pyyaml>=6.0.3",
#     "rich>=15.0.0",
#     "typer>=0.26.8",
# ]
# ///
"""输出中文 GitHub issue/PR 创建前静态检查摘要。"""

from __future__ import annotations

import re
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

SUSPICIOUS_TOKENS = (
    "issues: write",
    "pull-requests: write",
    "actions/github-script",
    "github.rest.issues.",
    "github.rest.pulls.",
    "gh issue",
    "gh pr",
    "gh api",
    "state: 'closed'",
    'state: "closed"',
    "state_reason",
    "stateReason",
    "addLabels",
    "removeLabel",
    "createComment",
    "updateComment",
    "close",
    "closed",
    "label",
    "labels",
    "template",
    "ISSUE_TEMPLATE",
    "PULL_REQUEST_TEMPLATE",
    "check-issue",
    "bypass",
    "required",
)

SCRIPT_PATH_RE = re.compile(
    r"(?P<path>(?:scripts|\.github)/(?:[\w@.+-]+/)*[\w@.+-]+\.(?:mjs|js|ts|py|sh|bash|yml|yaml))"
)


@dataclass
class IssueTemplate:
    path: Path
    name: str | None
    description: str | None
    labels: list[str]
    required_fields: list[str]


@dataclass
class WorkflowInfo:
    path: Path
    events: list[str]
    permissions: list[str]
    suspicious: list[str]
    scripts: list[Path]


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


def workflow_permissions(data: dict[str, Any], text: str) -> list[str]:
    """提取 workflow 权限声明。"""
    found: set[str] = set()
    permissions = data.get("permissions")
    if isinstance(permissions, dict):
        for key, value in permissions.items():
            found.add(f"{key}: {value}")
    for match in re.finditer(
        r"(?m)^\s*(issues|pull-requests|contents|checks|statuses|actions):\s*(\w+)\s*$",
        text,
    ):
        found.add(f"{match.group(1)}: {match.group(2)}")
    return sorted(found)


def extract_suspicious(text: str) -> list[str]:
    """提取风险关键词。"""
    return [token for token in SUSPICIOUS_TOKENS if token in text]


def extract_scripts(repo: Path, text: str) -> list[Path]:
    """提取 workflow 引用的本地脚本。"""
    scripts: set[Path] = set()
    for match in SCRIPT_PATH_RE.finditer(text):
        rel = Path(match.group("path"))
        if (repo / rel).is_file():
            scripts.add(rel)
    return sorted(scripts)


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
                events=events,
                permissions=workflow_permissions(data, text),
                suspicious=extract_suspicious(text),
                scripts=extract_scripts(repo, text),
            )
        )
    return workflows


def summarize_script(repo: Path, rel_path: Path) -> tuple[list[str], list[str]]:
    """提取本地脚本中的明显规则信号。"""
    path = repo / rel_path
    if not path.is_file():
        return [], []
    text = read_text(path)
    suspicious = extract_suspicious(text)
    rules = []
    for pattern, summary in (
        (
            r"state_reason|stateReason|not_planned|state:\s*['\"]closed['\"]",
            "可能关闭 issue/PR 或设置关闭原因",
        ),
        (r"createComment|issues\.createComment|gh issue comment", "可能创建自动评论"),
        (r"addLabels|issues\.addLabels|gh issue edit .*label", "可能添加标签"),
        (r"labels?\.|issue\.labels|pull_request\.labels", "读取或依赖标签"),
        (r"heading|headings|remark|markdown", "可能检查 Markdown 标题/正文结构"),
        (r"required|checkbox|terms", "可能检查必填字段或复选框"),
        (r"ISSUE_TEMPLATE|PULL_REQUEST_TEMPLATE|template", "可能检查模板合规性"),
    ):
        if re.search(pattern, text, re.IGNORECASE):
            rules.append(summary)
    return suspicious, rules


def section(title: str) -> None:
    """输出二级标题。"""
    console.print(f"## {title}")


def print_checked(
    repo: Path,
    mode: str,
    templates: list[IssueTemplate],
    workflows: list[WorkflowInfo],
    scripts: list[Path],
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
    console.print(f"- {mode} 相关 workflow 引用的本地脚本：发现 {len(scripts)} 个")
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
        console.print(
            f"  触发事件：{', '.join(workflow.events) if workflow.events else '未静态识别'}"
        )
        if workflow.permissions:
            console.print("  权限：")
            for perm in workflow.permissions:
                console.print(f"    - {perm}")
        if workflow.suspicious:
            console.print("  风险信号：")
            for item in workflow.suspicious:
                console.print(f"    - {item}")
        if workflow.scripts:
            console.print("  引用本地脚本：")
            for script in workflow.scripts:
                console.print(f"    - {script}")
    console.print()


def print_scripts(repo: Path, scripts: list[Path]) -> None:
    section("本地脚本摘要")
    if not scripts:
        console.print("- 未发现相关本地脚本\n")
        return
    for script in scripts:
        suspicious, rules = summarize_script(repo, script)
        console.print(f"- {script}")
        if suspicious:
            console.print("  风险信号：")
            for item in suspicious:
                console.print(f"    - {item}")
        if rules:
            console.print("  检测到的规则：")
            for rule in rules:
                console.print(f"    - {rule}")
    console.print()


def print_recommendations(
    mode: str, workflows: list[WorkflowInfo], scripts: list[Path]
) -> None:
    section("建议")
    if mode == "issue":
        if workflows or scripts:
            console.print(
                "- 如果 workflow/script 依赖 Issue Form 自动应用的标签或字段，优先使用网页 Issue Form，不要用普通 `gh issue create` 绕过表单。"
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
    scripts = sorted({script for workflow in workflows for script in workflow.scripts})

    console.print(f"# GitHub 创建前检查：{mode}\n")
    print_checked(repo, mode, templates, workflows, scripts)
    if mode == "issue":
        print_issue_config(repo)
        print_issue_templates(templates)
    else:
        print_pr_templates(repo)
    print_workflows(workflows, mode)
    print_scripts(repo, scripts)
    print_recommendations(mode, workflows, scripts)


if __name__ == "__main__":
    app()
