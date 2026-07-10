#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "httpx2>=2.5.0",
#     "pydantic>=2.13.4",
#     "pyyaml>=6.0.3",
#     "rich>=15.0.0",
#     "typer>=0.26.8",
# ]
# ///

"""统一检查并创建 GitHub issue，支持 Markdown 模板与 YAML Issue Form。"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal
from urllib.parse import quote, urlparse

import httpx2
import typer
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator
from rich.console import Console
from rich.table import Table


API_VERSION = "2022-11-28"
METADATA_PERMISSIONS = {"ADMIN", "MAINTAIN", "WRITE", "TRIAGE"}
TEMPLATE_SUFFIXES = {".md", ".yml", ".yaml"}

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="统一检查并创建 GitHub issue，保留模板预设 labels/assignees。",
)
console = Console(markup=False, width=120)
error_console = Console(stderr=True, markup=False, width=120)


class GitHubIssueError(RuntimeError):
    """表示可向用户解释的 GitHub issue 操作错误。"""


class RepoRef(BaseModel):
    """标准化后的 GitHub repository 标识。"""

    owner: str
    name: str
    hostname: str = "github.com"

    @property
    def full_name(self) -> str:
        """返回 owner/repo。"""

        return f"{self.owner}/{self.name}"


class FormField(BaseModel):
    """Issue Form 的单个字段。"""

    type: str
    id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    validations: dict[str, Any] = Field(default_factory=dict)


def normalize_string_list(value: Any) -> list[str]:
    """把逗号分隔字符串或 YAML 数组规整为字符串列表。"""

    if value is None or value == "":
        return []
    values = value if isinstance(value, list) else str(value).split(",")
    return [str(item).strip() for item in values if str(item).strip()]


class IssueForm(BaseModel):
    """GitHub YAML Issue Form 的顶层结构。"""

    name: str
    description: str
    title: str = ""
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    type: str | None = None
    body: list[FormField]

    @field_validator("labels", "assignees", "projects", mode="before")
    @classmethod
    def normalize_lists(cls, value: Any) -> list[str]:
        """兼容字符串与数组两种官方语法。"""

        return normalize_string_list(value)


class TemplateSpec(BaseModel):
    """供 inspect、create 和回读验证使用的模板摘要。"""

    filename: str
    kind: Literal["issue-form", "markdown"]
    name: str
    description: str | None = None
    default_title: str = ""
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    issue_type: str | None = None
    required_fields: list[str] = Field(default_factory=list)
    required_checkboxes: list[str] = Field(default_factory=list)
    submit_identifier: str


class RepoInfo(BaseModel):
    """创建 issue 所需的 repository GraphQL 信息。"""

    id: str
    viewer_permission: str = Field(alias="viewerPermission")


class VerificationResult(BaseModel):
    """创建后的回读结果与模板元数据校验。"""

    ok: bool
    repository: str
    template: str | None
    issue: dict[str, Any]
    expected_labels: list[str]
    expected_assignees: list[str]
    missing_labels: list[str]
    missing_assignees: list[str]


def parse_repo(repo: str, hostname: str | None = None) -> RepoRef:
    """解析 owner/repo、host/owner/repo 或 GitHub repository URL。"""

    raw = repo.strip()
    parsed_host = hostname
    if "://" in raw:
        parsed = urlparse(raw)
        parsed_host = parsed_host or parsed.hostname
        raw = parsed.path
    raw = raw.removesuffix(".git").strip("/")
    parts = raw.split("/")
    if len(parts) == 3 and parsed_host is None:
        parsed_host, owner, name = parts
    elif len(parts) == 2:
        owner, name = parts
    else:
        raise GitHubIssueError(
            "repo must be owner/repo, host/owner/repo, or a GitHub repository URL"
        )
    if not owner or not name:
        raise GitHubIssueError("repo owner and name must not be empty")
    return RepoRef(owner=owner, name=name, hostname=parsed_host or "github.com")


def resolve_token(hostname: str) -> str:
    """优先从环境变量读取 token，最后回退到 gh 的安全凭据存储。"""

    candidates = (
        ("GH_TOKEN", "GITHUB_TOKEN")
        if hostname == "github.com"
        else (
            "GH_ENTERPRISE_TOKEN",
            "GITHUB_ENTERPRISE_TOKEN",
            "GH_TOKEN",
            "GITHUB_TOKEN",
        )
    )
    for name in candidates:
        token = os.environ.get(name, "").strip()
        if token:
            return token

    try:
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", hostname],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitHubIssueError(
            "no GitHub token found in the environment and gh is not installed"
        ) from exc
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        message = result.stderr.strip() or "gh auth token returned no token"
        raise GitHubIssueError(message)
    return token


class GitHubApi:
    """使用 token 直接调用 GitHub REST 与 GraphQL API。"""

    def __init__(self, repo: RepoRef, token: str) -> None:
        self.repo = repo
        if repo.hostname == "github.com":
            self.rest_base = "https://api.github.com"
            self.graphql_url = "https://api.github.com/graphql"
        else:
            self.rest_base = f"https://{repo.hostname}/api/v3"
            self.graphql_url = f"https://{repo.hostname}/api/graphql"
        self.client = httpx2.Client(
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "dcjanus-github-issue-cli",
            },
            follow_redirects=True,
            timeout=30.0,
        )

    def close(self) -> None:
        """关闭 HTTP 连接池。"""

        self.client.close()

    def request_json(
        self, method: str, endpoint: str, *, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """调用 REST API 并要求返回 JSON object。"""

        response = self.client.request(
            method, f"{self.rest_base}/{endpoint.lstrip('/')}", json=payload
        )
        return self._json_response(response)

    def request_text(self, endpoint: str) -> str:
        """调用 REST Contents API 并读取原始文件。"""

        response = self.client.get(
            f"{self.rest_base}/{endpoint.lstrip('/')}",
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        self._raise_for_status(response)
        return response.text

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """执行 GraphQL 请求并返回 data。"""

        response = self.client.post(
            self.graphql_url, json={"query": query, "variables": variables}
        )
        payload = self._json_response(response)
        errors = payload.get("errors")
        if errors:
            messages = "; ".join(
                str(item.get("message", item)) if isinstance(item, dict) else str(item)
                for item in errors
            )
            raise GitHubIssueError(f"GitHub GraphQL error: {messages}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise GitHubIssueError("GitHub GraphQL response has no data object")
        return data

    def _json_response(self, response: httpx2.Response) -> dict[str, Any]:
        """校验 HTTP 状态与 JSON 响应形状。"""

        self._raise_for_status(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubIssueError("GitHub API did not return valid JSON") from exc
        if not isinstance(payload, dict):
            raise GitHubIssueError("unexpected GitHub API response shape")
        return payload

    @staticmethod
    def _raise_for_status(response: httpx2.Response) -> None:
        """把 HTTP 错误转换为不泄露 token 的稳定错误。"""

        if response.is_success:
            return
        try:
            payload = response.json()
        except ValueError:
            payload = None
        message = (
            str(payload.get("message"))
            if isinstance(payload, dict) and payload.get("message")
            else response.text.strip()
        )
        detail = message or response.reason_phrase or "request failed"
        raise GitHubIssueError(f"GitHub API HTTP {response.status_code}: {detail}")


def validate_template_filename(filename: str) -> str:
    """只接受 Issue Template 目录下的单个 Markdown/YAML 文件名。"""

    path = PurePosixPath(filename)
    if path.name != filename or path.suffix.lower() not in TEMPLATE_SUFFIXES:
        raise GitHubIssueError(
            "template must be a .md, .yml, or .yaml filename from .github/ISSUE_TEMPLATE"
        )
    return filename


def template_requirements(form: IssueForm) -> tuple[list[str], list[str]]:
    """提取 YAML Issue Form 的必填回答与 checkbox。"""

    required_fields: list[str] = []
    required_checkboxes: list[str] = []
    for field in form.body:
        label = field.attributes.get("label")
        if field.validations.get("required") is True and label:
            required_fields.append(str(label))
        options = field.attributes.get("options")
        if not isinstance(options, list):
            continue
        for option in options:
            if (
                isinstance(option, dict)
                and option.get("required") is True
                and option.get("label")
            ):
                required_checkboxes.append(str(option["label"]))
    return required_fields, required_checkboxes


def parse_markdown_frontmatter(text: str) -> dict[str, Any]:
    """解析 Markdown issue template 的 YAML frontmatter。"""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise GitHubIssueError("Markdown issue template has no YAML frontmatter")
    try:
        end = next(
            index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise GitHubIssueError(
            "Markdown issue template frontmatter is not closed"
        ) from exc
    try:
        payload = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise GitHubIssueError(f"invalid Markdown template frontmatter: {exc}") from exc
    if not isinstance(payload, dict):
        raise GitHubIssueError("Markdown template frontmatter must be an object")
    return payload


def parse_template(filename: str, text: str) -> TemplateSpec:
    """把 YAML Issue Form 或 Markdown template 转换为统一摘要。"""

    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in {".yml", ".yaml"}:
        try:
            raw = yaml.safe_load(text)
            form = IssueForm.model_validate(raw)
        except (yaml.YAMLError, ValidationError) as exc:
            raise GitHubIssueError(f"invalid YAML Issue Form: {exc}") from exc
        required_fields, required_checkboxes = template_requirements(form)
        return TemplateSpec(
            filename=filename,
            kind="issue-form",
            name=form.name,
            description=form.description,
            default_title=form.title,
            labels=form.labels,
            assignees=form.assignees,
            projects=form.projects,
            issue_type=form.type,
            required_fields=required_fields,
            required_checkboxes=required_checkboxes,
            submit_identifier=form.name,
        )

    metadata = parse_markdown_frontmatter(text)
    name = str(metadata.get("name", "")).strip()
    if not name:
        raise GitHubIssueError("Markdown issue template frontmatter has no name")
    return TemplateSpec(
        filename=filename,
        kind="markdown",
        name=name,
        description=str(metadata.get("about", "")).strip() or None,
        default_title=str(metadata.get("title", "")),
        labels=normalize_string_list(metadata.get("labels")),
        assignees=normalize_string_list(metadata.get("assignees")),
        submit_identifier=name,
    )


def fetch_template(api: GitHubApi, filename: str) -> TemplateSpec:
    """从 repository 默认分支读取并解析 issue template。"""

    filename = validate_template_filename(filename)
    endpoint = (
        f"repos/{api.repo.full_name}/contents/.github/ISSUE_TEMPLATE/"
        f"{quote(filename, safe='')}"
    )
    return parse_template(filename, api.request_text(endpoint))


def heading_response(body: str, label: str) -> str | None:
    """读取 Issue Form Markdown 中某个三级标题后的回答。"""

    pattern = re.compile(rf"(?ms)^###\s+{re.escape(label)}\s*$\n(.*?)(?=^###\s+|\Z)")
    match = pattern.search(body)
    return match.group(1).strip() if match else None


def validate_template_body(template: TemplateSpec, body: str) -> None:
    """阻止正文绕过 YAML Issue Form 的 required 约束。"""

    missing_fields = [
        label
        for label in template.required_fields
        if heading_response(body, label) in {None, "", "_No response_"}
    ]
    missing_checkboxes = [
        label
        for label in template.required_checkboxes
        if re.search(rf"(?mi)^-\s*\[[xX]\]\s*{re.escape(label)}\s*$", body) is None
    ]
    if missing_fields or missing_checkboxes:
        raise GitHubIssueError(
            "body does not satisfy required Issue Form fields: "
            f"missing answers={missing_fields}, missing checkboxes={missing_checkboxes}"
        )


def fetch_repo_info(api: GitHubApi) -> RepoInfo:
    """读取 repository ID 与当前用户权限。"""

    query = """
    query RepositoryInfo($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        id
        viewerPermission
      }
    }
    """
    data = api.graphql(query, {"owner": api.repo.owner, "name": api.repo.name}).get(
        "repository"
    )
    if not isinstance(data, dict):
        raise GitHubIssueError(f"repository not found: {api.repo.full_name}")
    return RepoInfo.model_validate(data)


def ensure_plain_metadata_permission(
    permission: str, labels: list[str], assignees: list[str]
) -> None:
    """阻止 REST 在权限不足时静默丢弃 labels/assignees。"""

    if (labels or assignees) and permission not in METADATA_PERMISSIONS:
        raise GitHubIssueError(
            "current repository permission cannot set labels/assignees on a plain API-created issue; "
            "use a repository template or the web form instead"
        )


def create_plain_issue(
    api: GitHubApi,
    *,
    title: str,
    body: str,
    labels: list[str],
    assignees: list[str],
) -> dict[str, Any]:
    """通过 REST API 创建无模板 issue。"""

    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    if assignees:
        payload["assignees"] = assignees
    return api.request_json(
        "POST", f"repos/{api.repo.full_name}/issues", payload=payload
    )


def create_template_issue(
    api: GitHubApi,
    *,
    repo_id: str,
    title: str,
    body: str,
    template: TemplateSpec,
) -> dict[str, Any]:
    """通过 GraphQL issueTemplate 创建 issue 并应用模板元数据。"""

    mutation = """
    mutation CreateIssue(
      $repositoryId: ID!
      $title: String!
      $body: String!
      $issueTemplate: String!
    ) {
      createIssue(input: {
        repositoryId: $repositoryId
        title: $title
        body: $body
        issueTemplate: $issueTemplate
      }) {
        issue {
          number
          url
        }
      }
    }
    """
    data = api.graphql(
        mutation,
        {
            "repositoryId": repo_id,
            "title": title,
            "body": body,
            "issueTemplate": template.submit_identifier,
        },
    )
    create_payload = data.get("createIssue")
    issue = create_payload.get("issue") if isinstance(create_payload, dict) else None
    if not isinstance(issue, dict):
        raise GitHubIssueError(
            "GitHub GraphQL response did not include the created issue"
        )
    return issue


def read_issue(api: GitHubApi, number: int) -> dict[str, Any]:
    """通过 REST 回读刚创建的 issue。"""

    return api.request_json("GET", f"repos/{api.repo.full_name}/issues/{number}")


def verify_issue(
    *,
    repo: RepoRef,
    template: TemplateSpec | None,
    issue: dict[str, Any],
    expected_labels: list[str],
    expected_assignees: list[str],
) -> VerificationResult:
    """确认模板或显式请求的 labels/assignees 已真正落到 issue。"""

    actual_labels = {
        str(item.get("name"))
        for item in issue.get("labels", [])
        if isinstance(item, dict) and item.get("name")
    }
    actual_assignees = {
        str(item.get("login"))
        for item in issue.get("assignees", [])
        if isinstance(item, dict) and item.get("login")
    }
    missing_labels = sorted(set(expected_labels) - actual_labels)
    missing_assignees = sorted(set(expected_assignees) - actual_assignees)
    summary = {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "state_reason": issue.get("state_reason"),
        "url": issue.get("html_url"),
        "labels": sorted(actual_labels),
        "assignees": sorted(actual_assignees),
        "comments": issue.get("comments"),
        "created_at": issue.get("created_at"),
    }
    return VerificationResult(
        ok=not missing_labels and not missing_assignees,
        repository=repo.full_name,
        template=template.filename if template else None,
        issue=summary,
        expected_labels=expected_labels,
        expected_assignees=expected_assignees,
        missing_labels=missing_labels,
        missing_assignees=missing_assignees,
    )


def template_payload(template: TemplateSpec) -> dict[str, Any]:
    """返回适合 JSON 输出的模板摘要。"""

    return template.model_dump(mode="json")


def print_template(template: TemplateSpec, repo: RepoRef) -> None:
    """输出人类可读的模板摘要。"""

    table = Table(show_header=False, box=None)
    table.add_row("repository", repo.full_name)
    table.add_row("filename", template.filename)
    table.add_row("kind", template.kind)
    table.add_row("name", template.name)
    table.add_row("submit identifier", template.submit_identifier)
    table.add_row("labels", ", ".join(template.labels) or "-")
    table.add_row("assignees", ", ".join(template.assignees) or "-")
    table.add_row("required fields", ", ".join(template.required_fields) or "-")
    table.add_row("required checkboxes", ", ".join(template.required_checkboxes) or "-")
    console.print(table)


def print_creation_result(result: VerificationResult, *, dry_run: bool) -> None:
    """输出创建计划或回读结果。"""

    if dry_run:
        console.print("dry-run: no issue was created")
        return
    table = Table(show_header=False, box=None)
    table.add_row("repository", result.repository)
    table.add_row("url", str(result.issue.get("html_url") or result.issue.get("url")))
    table.add_row("labels verified", "yes" if not result.missing_labels else "no")
    table.add_row("assignees verified", "yes" if not result.missing_assignees else "no")
    console.print(table)


def normalize_options(values: list[str] | None) -> list[str]:
    """规整可重复、可逗号分隔的 CLI 选项。"""

    normalized: list[str] = []
    for value in values or []:
        normalized.extend(normalize_string_list(value))
    return list(dict.fromkeys(normalized))


def open_api(repo: RepoRef) -> GitHubApi:
    """使用当前鉴权创建 GitHub API client。"""

    return GitHubApi(repo, resolve_token(repo.hostname))


@app.command("inspect")
def inspect_template(
    repo: Annotated[str, typer.Option("--repo", help="GitHub repository。")],
    template: Annotated[
        str, typer.Option("--template", help="Issue template 文件名。")
    ],
    hostname: Annotated[
        str | None, typer.Option("--hostname", help="GitHub host。")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """读取远端 issue template 的元数据与必填字段。"""

    api: GitHubApi | None = None
    try:
        repo_ref = parse_repo(repo, hostname)
        api = open_api(repo_ref)
        spec = fetch_template(api, template)
        if as_json:
            typer.echo(json.dumps(template_payload(spec), ensure_ascii=False))
        else:
            print_template(spec, repo_ref)
    except GitHubIssueError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    finally:
        if api is not None:
            api.close()


@app.command("create")
def create_issue(
    repo: Annotated[str, typer.Option("--repo", help="GitHub repository。")],
    title: Annotated[str, typer.Option("--title", help="Issue 标题。")],
    body_file: Annotated[
        Path,
        typer.Option(
            "--body-file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="已整理好的 Markdown 正文文件。",
        ),
    ],
    template: Annotated[
        str | None,
        typer.Option(
            "--template", help="Issue template 文件名；不传则创建普通 issue。"
        ),
    ] = None,
    label: Annotated[
        list[str] | None,
        typer.Option("--label", help="普通 issue 的 label，可重复或逗号分隔。"),
    ] = None,
    assignee: Annotated[
        list[str] | None,
        typer.Option("--assignee", help="普通 issue 的 assignee，可重复或逗号分隔。"),
    ] = None,
    hostname: Annotated[
        str | None, typer.Option("--hostname", help="GitHub host。")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="只检查，不创建 issue。")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """通过直接 API 调用创建 issue，并回读验证元数据。"""

    api: GitHubApi | None = None
    try:
        repo_ref = parse_repo(repo, hostname)
        clean_title = title.strip()
        if not clean_title:
            raise GitHubIssueError("title must not be empty")
        body = body_file.read_text(encoding="utf-8")
        if not body.strip():
            raise GitHubIssueError("body file must not be empty")

        labels = normalize_options(label)
        assignees = normalize_options(assignee)
        if template and (labels or assignees):
            raise GitHubIssueError(
                "--template cannot be combined with --label or --assignee; template metadata is applied server-side"
            )

        api = open_api(repo_ref)
        repo_info = fetch_repo_info(api)
        spec = fetch_template(api, template) if template else None
        if spec:
            validate_template_body(spec, body)
        expected_labels = spec.labels if spec else labels
        expected_assignees = spec.assignees if spec else assignees
        if spec is None:
            ensure_plain_metadata_permission(
                repo_info.viewer_permission, expected_labels, expected_assignees
            )

        if dry_run:
            payload = {
                "ok": True,
                "dry_run": True,
                "repository": repo_ref.full_name,
                "viewer_permission": repo_info.viewer_permission,
                "title": clean_title,
                "body_file": str(body_file),
                "template": template_payload(spec) if spec else None,
                "expected_labels": expected_labels,
                "expected_assignees": expected_assignees,
            }
            if as_json:
                typer.echo(json.dumps(payload, ensure_ascii=False))
            else:
                if spec:
                    print_template(spec, repo_ref)
                print_creation_result(
                    VerificationResult(
                        ok=True,
                        repository=repo_ref.full_name,
                        template=spec.filename if spec else None,
                        issue={},
                        expected_labels=expected_labels,
                        expected_assignees=expected_assignees,
                        missing_labels=[],
                        missing_assignees=[],
                    ),
                    dry_run=True,
                )
            return

        created = (
            create_template_issue(
                api,
                repo_id=repo_info.id,
                title=clean_title,
                body=body,
                template=spec,
            )
            if spec
            else create_plain_issue(
                api,
                title=clean_title,
                body=body,
                labels=labels,
                assignees=assignees,
            )
        )
        number = created.get("number")
        if not isinstance(number, int):
            raise GitHubIssueError("created issue response has no numeric issue number")
        issue = read_issue(api, number)
        result = verify_issue(
            repo=repo_ref,
            template=spec,
            issue=issue,
            expected_labels=expected_labels,
            expected_assignees=expected_assignees,
        )
        if as_json:
            typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))
        else:
            print_creation_result(result, dry_run=False)
        if not result.ok:
            raise GitHubIssueError(
                "issue was created but metadata verification failed: "
                f"missing labels={result.missing_labels}, missing assignees={result.missing_assignees}; "
                f"url={issue.get('html_url')}"
            )
    except (GitHubIssueError, OSError) as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    finally:
        if api is not None:
            api.close()


if __name__ == "__main__":
    app()
