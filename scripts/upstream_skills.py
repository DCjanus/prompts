#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "upstream-skills.toml"


class UpstreamLookupError(RuntimeError):
    """表示无法读取上游 skill 状态。"""


@dataclass(frozen=True)
class TrackedSkill:
    """描述一个固定到特定上游 commit 的 skill。"""

    name: str
    repository: str
    path: str
    commit: str


@dataclass(frozen=True)
class SkillReport:
    """记录单个 skill 的上游检查结果。"""

    skill: TrackedSkill
    latest_commit: str | None
    status: str
    error: str | None = None

    @property
    def needs_attention(self) -> bool:
        return self.status != "current"


def _required_string(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"skills[{index}].{key} must be a non-empty string")
    return value.strip()


def load_manifest(path: Path) -> list[TrackedSkill]:
    """读取并校验上游 skill 清单。"""
    with path.open("rb") as file:
        payload = tomllib.load(file)

    items = payload.get("skills")
    if not isinstance(items, list) or not items:
        raise ValueError("manifest must contain at least one [[skills]] entry")

    skills: list[TrackedSkill] = []
    names: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"skills[{index}] must be a table")
        skill = TrackedSkill(
            name=_required_string(item, "name", index),
            repository=_required_string(item, "repository", index),
            path=_required_string(item, "path", index).strip("/"),
            commit=_required_string(item, "commit", index).lower(),
        )
        if skill.name in names:
            raise ValueError(f"duplicate skill name: {skill.name}")
        if skill.repository.count("/") != 1:
            raise ValueError(
                f"skills[{index}].repository must use the owner/repository form"
            )
        if not SHA_RE.fullmatch(skill.commit):
            raise ValueError(f"skills[{index}].commit must be a full Git SHA")
        names.add(skill.name)
        skills.append(skill)

    return skills


def fetch_latest_commit(skill: TrackedSkill, *, timeout: float) -> str:
    """读取上游路径最近一次变更的 commit。"""
    encoded_path = quote(skill.path, safe="/")
    url = (
        f"https://api.github.com/repos/{skill.repository}/commits"
        f"?path={encoded_path}&per_page=1"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "DCjanus-prompts-upstream-skill-check",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise UpstreamLookupError(f"GitHub API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise UpstreamLookupError(str(exc)) from exc

    if not isinstance(payload, list) or not payload:
        raise UpstreamLookupError("GitHub API returned no commits for the path")
    sha = payload[0].get("sha") if isinstance(payload[0], dict) else None
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise UpstreamLookupError("GitHub API returned an invalid commit SHA")
    return sha


def check_skills(
    skills: Sequence[TrackedSkill],
    fetcher: Callable[[TrackedSkill], str],
) -> list[SkillReport]:
    """检查所有 skill，并把查询失败作为需关注状态返回。"""
    reports: list[SkillReport] = []
    for skill in skills:
        try:
            latest_commit = fetcher(skill)
        except UpstreamLookupError as exc:
            reports.append(
                SkillReport(
                    skill=skill,
                    latest_commit=None,
                    status="lookup failed",
                    error=str(exc),
                )
            )
            continue

        reports.append(
            SkillReport(
                skill=skill,
                latest_commit=latest_commit,
                status="current" if latest_commit == skill.commit else "changed",
            )
        )
    return reports


def _short_sha(value: str | None) -> str:
    return value[:12] if value else "-"


def render_console(reports: Sequence[SkillReport]) -> str:
    """生成适合终端阅读的检查结果。"""
    lines = ["upstream skill report"]
    for report in reports:
        detail = report.error or _short_sha(report.latest_commit)
        lines.append(
            f"- {report.skill.name}: {report.status} "
            f"(pinned {_short_sha(report.skill.commit)}, latest {detail})"
        )
    return "\n".join(lines) + "\n"


def render_markdown(reports: Sequence[SkillReport]) -> str:
    """生成 GitHub Actions step summary。"""
    attention_count = sum(report.needs_attention for report in reports)
    lines = [
        "# Upstream skill report",
        "",
        f"- Skills scanned: {len(reports)}",
        f"- Skills needing attention: {attention_count}",
        "",
        "| Skill | Pinned | Latest | Status |",
        "| --- | --- | --- | --- |",
    ]
    for report in reports:
        pinned_url = (
            f"https://github.com/{report.skill.repository}/commit/{report.skill.commit}"
        )
        pinned = f"[{_short_sha(report.skill.commit)}]({pinned_url})"
        if report.latest_commit:
            latest_url = (
                f"https://github.com/{report.skill.repository}/commit/"
                f"{report.latest_commit}"
            )
            latest = f"[{_short_sha(report.latest_commit)}]({latest_url})"
        else:
            latest = report.error or "-"
        lines.append(f"| {report.skill.name} | {pinned} | {latest} | {report.status} |")
    return "\n".join(lines) + "\n"


def report_payload(reports: Sequence[SkillReport]) -> dict[str, Any]:
    """生成机器可读的检查结果。"""
    return {
        "skill_count": len(reports),
        "attention_count": sum(report.needs_attention for report in reports),
        "skills": [
            {
                **asdict(report.skill),
                "latest_commit": report.latest_commit,
                "status": report.status,
                "error": report.error,
                "needs_attention": report.needs_attention,
            }
            for report in reports
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="检查本仓库引入的第三方 skill 是否出现上游变更。"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="上游 skill 清单路径",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="GitHub API 请求超时时间，单位秒",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--github-summary",
        action="store_true",
        help="写入 GitHub Actions step summary",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """运行上游 skill 检查。"""
    args = parse_args(argv)
    try:
        skills = load_manifest(args.manifest.expanduser().resolve())
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"failed to load manifest: {exc}", file=sys.stderr)
        return 1

    reports = check_skills(
        skills,
        lambda skill: fetch_latest_commit(skill, timeout=args.timeout),
    )
    if args.json:
        print(json.dumps(report_payload(reports), ensure_ascii=False, indent=2))
    else:
        print(render_console(reports), end="")

    if args.github_summary:
        summary = render_markdown(reports)
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            Path(summary_path).write_text(summary, encoding="utf-8")
        else:
            print(summary, end="")

    return 1 if any(report.needs_attention for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
