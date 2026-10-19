#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "rich>=15.0.0",
#     "typer>=0.27.3",
# ]
# ///

"""配置 GitHub repository 的 squash merge policy。"""

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

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="配置 squash-only 合并；组织仓库同时启用默认分支 merge queue。",
)

QUEUE_RULESET_NAME = "DCjanus merge queue"


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
        "allow_auto_merge": True,
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
    path: str = "",
    paginate: bool = False,
) -> dict | list:
    """通过 `gh api` 调用 GitHub repository API。"""

    endpoint = f"repos/{normalize_repo(repo)}"
    if path:
        endpoint += f"/{path}"
    args = ["gh", "api", endpoint, "--method", method]
    if paginate:
        args.extend(["--paginate", "--slurp"])
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
    if paginate:
        if not isinstance(parsed, list) or not all(
            isinstance(page, list) for page in parsed
        ):
            raise RuntimeError("unexpected paginated API response shape")
        return [item for page in parsed for item in page]
    if not isinstance(parsed, (dict, list)):
        raise TypeError("unexpected API response shape")
    return parsed


def contains_expected(actual: object, expected: object) -> bool:
    """容忍 API 补充默认字段，核对写入值与既有规则均保留。"""

    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and contains_expected(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                any(contains_expected(item, value) for item in actual)
                for value in expected
            )
        )
    return actual == expected


def configure_merge_queue(
    *,
    repo: str,
    cwd: Path,
    hostname: str | None,
    repository: dict,
    required_checks: list[str],
    queue_timeout_minutes: int,
) -> dict:
    """为组织仓库管理独立规则集，保留其它保护与检查。"""

    owner_type = repository.get("owner", {}).get("type")
    if owner_type == "User":
        if required_checks:
            raise RuntimeError(
                "--required-check only applies to organization repositories"
            )
        return {"status": "not_applicable", "reason": "personal repository"}
    if owner_type != "Organization":
        raise RuntimeError("GitHub repository owner.type is missing or unsupported")

    def api(method: str, path: str, payload: dict | None = None, *, paginate=False):
        return run_gh_api(
            repo=repo,
            method=method,
            payload=payload,
            cwd=cwd,
            hostname=hostname,
            path=path,
            paginate=paginate,
        )

    rulesets = api("GET", "rulesets?includes_parents=false&per_page=100", paginate=True)
    owned = [item for item in rulesets if item["name"] == QUEUE_RULESET_NAME]
    if len(owned) > 1:
        raise RuntimeError(
            f"multiple rulesets named {QUEUE_RULESET_NAME!r}; refusing to overwrite"
        )
    current = api("GET", f"rulesets/{owned[0]['id']}") if owned else {}
    branch = repository.get("default_branch")
    if not branch:
        raise RuntimeError("repository default_branch is missing")
    effective = api("GET", f"rules/branches/{quote(branch, safe='')}")
    external = [
        rule
        for rule in effective
        if rule["type"] == "merge_queue" and rule.get("ruleset_id") != current.get("id")
    ]
    if external:
        if required_checks or any(
            rule["parameters"]["merge_method"] != "SQUASH" for rule in external
        ):
            raise RuntimeError(
                "an existing merge queue is managed by another ruleset; configure it there"
            )
        return {
            "status": "existing",
            "ruleset_ids": [rule["ruleset_id"] for rule in external],
        }

    rules = [rule for rule in current.get("rules", []) if rule["type"] != "merge_queue"]
    rules.append(
        {
            "type": "merge_queue",
            "parameters": {
                "check_response_timeout_minutes": queue_timeout_minutes,
                "grouping_strategy": "ALLGREEN",
                "max_entries_to_build": 1,
                "max_entries_to_merge": 1,
                "merge_method": "SQUASH",
                "min_entries_to_merge": 1,
                "min_entries_to_merge_wait_minutes": 0,
            },
        }
    )
    if required_checks:
        checks_rule = next(
            (rule for rule in rules if rule["type"] == "required_status_checks"), None
        )
        if checks_rule is None:
            checks_rule = {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [],
                },
            }
            rules.append(checks_rule)
        checks = checks_rule["parameters"]["required_status_checks"]
        for context in dict.fromkeys(required_checks):
            if not any(check["context"] == context for check in checks):
                checks.append({"context": context})
    payload = {
        "name": QUEUE_RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": current.get("bypass_actors", []),
        "rules": rules,
    }
    path = f"rulesets/{current['id']}" if current else "rulesets"
    written = api("PUT" if current else "POST", path, payload)
    verified = api("GET", f"rulesets/{written['id']}")
    if not contains_expected(verified, payload):
        raise RuntimeError(f"merge queue ruleset {written['id']} verification failed")
    # 使用生效规则核对作用分支，而非仅检查保存的规则集。
    active_rules = api("GET", f"rules/branches/{quote(branch, safe='')}")
    if not any(
        rule["type"] == "merge_queue" and rule.get("ruleset_id") == written["id"]
        for rule in active_rules
    ):
        raise RuntimeError(
            f"merge queue ruleset {written['id']} is not effective on {branch}"
        )
    return {"status": "configured", "ruleset": verified}


def apply_policy(
    *,
    repo: str,
    cwd: Path,
    hostname: str | None,
    required_checks: list[str] | None = None,
    queue_timeout_minutes: int = 90,
) -> dict[str, object]:
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
    response["merge_queue"] = configure_merge_queue(
        repo=repo,
        cwd=cwd,
        hostname=hostname,
        repository=response,
        required_checks=required_checks or [],
        queue_timeout_minutes=queue_timeout_minutes,
    )
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
        "allow_auto_merge",
        "squash_merge_commit_title",
        "squash_merge_commit_message",
        "delete_branch_on_merge",
    ):
        if key in payload:
            table.add_row(key, str(payload.get(key)))
    console.print("repository:")
    console.print(table)
    queue = payload.get("merge_queue", {})
    console.print(f"merge_queue: {queue.get('status')}")
    if "ruleset" in queue:
        console.print(f"ruleset: {queue['ruleset']['id']} ({QUEUE_RULESET_NAME})")


@app.command()
def main(
    repo: str = typer.Option(
        ..., "--repo", help="GitHub repository，格式 owner/repo。"
    ),
    cwd: Path = typer.Option(
        Path(),
        "--cwd",
        resolve_path=True,
        file_okay=False,
        dir_okay=True,
        help="让 gh 在哪个目录下执行。",
    ),
    hostname: str | None = typer.Option(None, "--hostname", help="GitHub host。"),
    required_checks: list[str] | None = typer.Option(
        None,
        "--required-check",
        help="为组织仓库的队列规则集追加必需检查，可重复；省略时保留已有检查。",
    ),
    queue_timeout_minutes: int = typer.Option(
        90,
        "--queue-timeout-minutes",
        min=1,
        max=360,
        help="组织仓库队列等待 CI 结果的分钟数。",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="输出仓库配置及 merge_queue 结果 JSON。"
    ),
) -> None:
    """应用 squash-only merge policy。"""

    try:
        response = apply_policy(
            repo=repo,
            cwd=cwd,
            hostname=hostname,
            required_checks=required_checks,
            queue_timeout_minutes=queue_timeout_minutes,
        )
    except (RuntimeError, TypeError) as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1) from exc

    if as_json:
        typer.echo(json.dumps(response, ensure_ascii=True))
        return
    print_result(response)


if __name__ == "__main__":
    app()
