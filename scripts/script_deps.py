#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "packaging>=26.2",
#     "rich>=15.0.0",
#     "typer>=0.27.0",
# ]
# ///

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from rich.console import Console
from rich.table import Table
import typer

console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=False)

SCRIPT_BLOCK_RE = re.compile(r"(?m)^# /// script\s*\n(?P<body>(?:#.*\n)*?)^# ///\s*$")


@dataclass(frozen=True)
class DependencyOccurrence:
    path: Path
    raw: str
    requirement: Requirement | None
    error: str | None = None


@dataclass
class PackageReport:
    name: str
    latest: str | None = None
    latest_error: str | None = None
    occurrences: list[DependencyOccurrence] = field(default_factory=list)

    @property
    def constraints(self) -> list[str]:
        values = {
            str(occurrence.requirement.specifier) or "(unbounded)"
            for occurrence in self.occurrences
            if occurrence.requirement is not None
        }
        return sorted(values)

    @property
    def files(self) -> list[str]:
        return sorted({str(occurrence.path) for occurrence in self.occurrences})


@dataclass(frozen=True)
class UpgradeAction:
    path: Path
    package: str
    requirement: str


def read_script_metadata(path: Path) -> dict[str, Any] | None:
    """读取 PEP 723 script metadata。"""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None

    match = SCRIPT_BLOCK_RE.search(text)
    if match is None:
        return None

    body = []
    for line in match.group("body").splitlines():
        if line.startswith("# "):
            body.append(line[2:])
        elif line.startswith("#"):
            body.append(line[1:])
        else:
            body.append(line)

    import tomllib

    return tomllib.loads("\n".join(body))


def list_python_files(root: Path) -> list[Path]:
    """优先扫描 Git 跟踪文件，避免虚拟环境和缓存目录。"""
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return sorted(
            path
            for path in root.rglob("*.py")
            if ".git" not in path.relative_to(root).parts
            and ".venv" not in path.relative_to(root).parts
        )

    return sorted(root / line for line in result.stdout.splitlines() if line)


def collect_dependencies(root: Path) -> tuple[dict[str, PackageReport], list[str]]:
    """收集所有 uv script 依赖声明。"""
    reports: dict[str, PackageReport] = {}
    errors: list[str] = []

    for path in list_python_files(root):
        metadata = read_script_metadata(path)
        if metadata is None:
            continue

        for raw in metadata.get("dependencies", []):
            rel_path = path.relative_to(root)
            try:
                requirement = Requirement(raw)
            except InvalidRequirement as exc:
                package = raw.split(";", 1)[0].split("[", 1)[0].strip() or raw
                name = canonicalize_name(package)
                reports.setdefault(name, PackageReport(name=name)).occurrences.append(
                    DependencyOccurrence(rel_path, raw, None, str(exc))
                )
                errors.append(f"{rel_path}: invalid requirement {raw!r}: {exc}")
                continue

            name = canonicalize_name(requirement.name)
            reports.setdefault(name, PackageReport(name=name)).occurrences.append(
                DependencyOccurrence(rel_path, raw, requirement)
            )

    return reports, errors


def fetch_latest_version(package: str, timeout: float) -> tuple[str | None, str | None]:
    """从 PyPI JSON API 读取最新版本。"""
    url = f"https://pypi.org/pypi/{quote(package)}/json"
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return None, str(exc)

    version = payload.get("info", {}).get("version")
    if not isinstance(version, str) or not version:
        return None, "missing info.version in PyPI response"
    return version, None


def declared_versions(report: PackageReport) -> list[Version]:
    """提取声明中的可比较版本下限或精确版本。"""
    versions: list[Version] = []
    for occurrence in report.occurrences:
        requirement = occurrence.requirement
        if requirement is None:
            continue
        for specifier in requirement.specifier:
            if specifier.operator not in {"==", "===", ">=", ">", "~="}:
                continue
            try:
                versions.append(Version(specifier.version))
            except InvalidVersion:
                continue
    return versions


def package_status(report: PackageReport) -> str:
    """判断依赖声明是否值得关注。"""
    if any(occurrence.error for occurrence in report.occurrences):
        return "invalid requirement"
    if report.latest_error:
        return "lookup failed"
    if not report.latest:
        return "unknown"
    if "(unbounded)" in report.constraints:
        return "unbounded"

    versions = declared_versions(report)
    if not versions:
        return "no comparable floor"

    try:
        latest = Version(report.latest)
    except InvalidVersion:
        return "unknown"

    constraints_are_mixed = len(report.constraints) > 1
    if max(versions) < latest:
        return (
            "minimum behind latest; mixed constraints"
            if constraints_are_mixed
            else "minimum behind latest"
        )
    if constraints_are_mixed:
        return "mixed constraints"
    return "ok"


def needs_attention(status: str) -> bool:
    return status != "ok"


def build_reports(root: Path, timeout: float) -> tuple[list[PackageReport], list[str]]:
    reports, errors = collect_dependencies(root)
    for report in reports.values():
        report.latest, report.latest_error = fetch_latest_version(report.name, timeout)
    return sorted(reports.values(), key=lambda item: item.name), errors


def upgrade_requirement(report: PackageReport, requirement: Requirement) -> str | None:
    """构造保留 extras 和 marker 的最新下限声明。"""
    if not report.latest or report.latest_error or requirement.url:
        return None

    extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
    marker = f"; {requirement.marker}" if requirement.marker else ""
    return f"{requirement.name}{extras}>={report.latest}{marker}"


def collect_upgrade_actions(
    root: Path, reports: list[PackageReport]
) -> tuple[list[UpgradeAction], list[str]]:
    """生成 uv add --script 升级动作。"""
    actions: dict[tuple[Path, str], UpgradeAction] = {}
    skipped: list[str] = []

    for report in reports:
        for occurrence in report.occurrences:
            if occurrence.requirement is None:
                skipped.append(
                    f"{occurrence.path}: invalid requirement {occurrence.raw!r}"
                )
                continue

            requirement = upgrade_requirement(report, occurrence.requirement)
            if requirement is None:
                skipped.append(
                    f"{occurrence.path}: cannot upgrade {occurrence.raw!r} automatically"
                )
                continue
            if occurrence.raw == requirement:
                continue

            path = root / occurrence.path
            key = (path, report.name)
            actions[key] = UpgradeAction(
                path=path,
                package=report.name,
                requirement=requirement,
            )

    return sorted(actions.values(), key=lambda item: (item.path, item.package)), skipped


def run_upgrade_actions(actions: list[UpgradeAction], *, dry_run: bool) -> None:
    """调用 uv add --script 更新依赖声明。"""
    if not actions:
        console.print("[green]No upgrade actions needed.[/green]")
        return

    for action in actions:
        command = [
            "uv",
            "add",
            "--script",
            str(action.path),
            action.requirement,
        ]
        console.print(f"{'Would run' if dry_run else 'Running'}: {' '.join(command)}")
        if not dry_run:
            subprocess.run(command, check=True)


def report_to_payload(
    reports: list[PackageReport], errors: list[str]
) -> dict[str, Any]:
    packages = []
    for report in reports:
        status = package_status(report)
        packages.append(
            {
                "name": report.name,
                "latest": report.latest,
                "latest_error": report.latest_error,
                "constraints": report.constraints,
                "files": report.files,
                "status": status,
                "needs_attention": needs_attention(status),
            }
        )

    return {
        "package_count": len(packages),
        "attention_count": sum(1 for package in packages if package["needs_attention"]),
        "packages": packages,
        "errors": errors,
    }


def render_table(reports: list[PackageReport], *, only_attention: bool) -> None:
    table = Table(title="uv script dependency report")
    table.add_column("package")
    table.add_column("latest")
    table.add_column("declared")
    table.add_column("scripts", justify="right")
    table.add_column("status")

    for report in reports:
        status = package_status(report)
        if only_attention and not needs_attention(status):
            continue
        table.add_row(
            report.name,
            report.latest or "-",
            ", ".join(report.constraints) or "-",
            str(len(report.files)),
            status,
        )

    console.print(table)


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_markdown(reports: list[PackageReport], errors: list[str]) -> str:
    attention_count = sum(
        1 for report in reports if needs_attention(package_status(report))
    )
    lines = [
        "# uv script dependency report",
        "",
        f"- Packages scanned: {len(reports)}",
        f"- Packages needing attention: {attention_count}",
        "",
        "| Package | Latest | Declared | Scripts | Status |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for report in reports:
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_escape(report.name),
                    markdown_escape(report.latest or "-"),
                    markdown_escape(", ".join(report.constraints) or "-"),
                    str(len(report.files)),
                    markdown_escape(package_status(report)),
                ]
            )
            + " |"
        )

    if errors:
        lines.extend(["", "## Parse errors", ""])
        lines.extend(f"- {markdown_escape(error)}" for error in errors)

    return "\n".join(lines) + "\n"


@app.command(help="检查或升级仓库内 PEP 723 uv script 依赖声明。")
def main(
    root: Annotated[Path, typer.Option("--root", "-C", help="仓库根目录")] = Path("."),
    timeout: Annotated[float, typer.Option(help="PyPI 请求超时时间，单位秒")] = 10.0,
    json_output: Annotated[
        bool, typer.Option("--json", "-j", help="输出 JSON")
    ] = False,
    github_summary: Annotated[
        bool,
        typer.Option("--github-summary", help="写入 GitHub Actions step summary"),
    ] = False,
    only_attention: Annotated[
        bool,
        typer.Option("--only-attention", help="终端表格只显示需要关注的依赖"),
    ] = False,
    fail_on_attention: Annotated[
        bool,
        typer.Option("--fail-on-attention", help="发现需要关注的依赖时返回非 0"),
    ] = False,
    upgrade: Annotated[
        bool,
        typer.Option("--upgrade", help="使用 uv add --script 自动升级依赖声明下限"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="配合 --upgrade 使用，只输出将执行的命令"),
    ] = False,
) -> None:
    resolved_root = root.expanduser().resolve()
    reports, errors = build_reports(resolved_root, timeout)
    payload = report_to_payload(reports, errors)

    if dry_run and not upgrade:
        raise typer.BadParameter("--dry-run 必须和 --upgrade 一起使用")

    if upgrade:
        actions, skipped = collect_upgrade_actions(resolved_root, reports)
        run_upgrade_actions(actions, dry_run=dry_run)
        if skipped:
            console.print("[yellow]Skipped automatic upgrades:[/yellow]")
            for item in skipped:
                console.print(f"- {item}")
        if not dry_run:
            reports, errors = build_reports(resolved_root, timeout)
            payload = report_to_payload(reports, errors)

    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        render_table(reports, only_attention=only_attention)

    if github_summary:
        summary = render_markdown(reports, errors)
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            Path(summary_path).write_text(summary, encoding="utf-8")
        else:
            console.print(summary)

    if errors or (fail_on_attention and payload["attention_count"]):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    try:
        app()
    except KeyboardInterrupt:
        console.print("[red]Interrupted[/red]", file=sys.stderr)
        raise typer.Exit(code=130)
