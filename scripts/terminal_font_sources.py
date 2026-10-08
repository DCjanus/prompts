#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "blake3>=1.0.11",
#     "rich>=15.0.0",
#     "typer>=0.27.3",
# ]
# ///


from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import tomllib
import typer
from blake3 import blake3
from rich.console import Console

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)
console = Console()
DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "terminal-fonts.toml"


def load_manifest(path: Path) -> list[dict]:
    """读取固定版本、下载摘要和上游检查基线。"""
    fonts = tomllib.loads(path.read_text())["fonts"]
    if {font["name"] for font in fonts} != {"sarasa", "lilex"} or len(fonts) != 2:
        raise ValueError("清单必须包含且仅包含 sarasa 和 lilex")
    for font in fonts:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", font["repository"]):
            raise ValueError("无效 GitHub repository")
        if not re.fullmatch(r"[0-9a-f]{64}", font["sha256"]):
            raise ValueError("需要上游资产的 SHA-256 摘要")
        if not isinstance(font["observed_latest"], int):
            raise TypeError("observed_latest 必须是发布 ID")
    return fonts


def release(font: dict, latest: bool = False) -> dict:
    """读取 GitHub 发布；失败直接报错，避免误报未更新。"""
    suffix = "latest" if latest else "tags/" + quote(font["tag"], safe="")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "terminal-fonts"}
    if token := os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"https://api.github.com/repos/{font['repository']}/releases/{suffix}",
        headers=headers,
    )
    with urlopen(request, timeout=60) as response:  # noqa: S310
        return json.load(response)


def approved_asset(font: dict, payload: dict) -> dict:
    """验证固定发布的资产摘要，检测同版本附件被替换。"""
    assets = [asset for asset in payload["assets"] if asset["name"] == font["asset"]]
    if len(assets) != 1 or assets[0].get("digest") != "sha256:" + font["sha256"]:
        raise ValueError(f"{font['name']}: 固定资产缺失或摘要发生变化")
    return assets[0]


@app.command()
def check(
    manifest: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="来源版本清单。")
    ] = DEFAULT_MANIFEST,
) -> None:
    """检查上游 latest 发布及固定资产；有变化或查询失败时退出非零。"""
    failures = []
    for font in load_manifest(manifest):
        try:
            latest = release(font, latest=True)
            approved_asset(font, release(font))
            if latest["id"] != font["observed_latest"]:
                raise ValueError(
                    f"发现新发布 {latest['tag_name']} (ID {latest['id']})；请人工验收后更新清单"
                )
            console.print(f"{font['name']}: 未发现新发布；构建版本 {font['tag']}")
        except (OSError, ValueError, KeyError) as error:
            failures.append(f"{font['name']}: {error}")
    for failure in failures:
        console.print(failure, style="red")
    if failures:
        raise typer.Exit(1)


def build_inputs(repository: Path) -> list[Path]:
    """列出会影响字体构建或随包分发的输入。"""
    return [
        repository / "scripts/merge_terminal_fonts.py",
        repository / "scripts/terminal_font_sources.py",
        repository / "terminal-fonts.toml",
        repository / ".github/workflows/terminal-fonts.yml",
        *sorted((repository / "licenses/terminal-fonts").glob("*.txt")),
    ]


def input_id(repository: Path) -> str:
    """按路径和内容计算构建输入指纹。"""
    hasher = blake3()
    for path in build_inputs(repository):
        name = path.relative_to(repository).as_posix().encode()
        content = path.read_bytes()
        for value in (name, content):
            hasher.update(len(value).to_bytes(8, "big"))
            hasher.update(value)
    return hasher.hexdigest()


def release_is_current(payload: dict, fingerprint: str) -> bool:
    """只有已发布、含字体包且构建输入一致的 release 才能复用。"""
    marker = f"<!-- terminal-font-inputs: {fingerprint} -->"
    return (
        payload.get("draft") is False
        and marker in (payload.get("body") or "")
        and any(
            asset.get("name") == "terminal-fonts.zip"
            and asset.get("state") == "uploaded"
            for asset in payload.get("assets", [])
        )
    )


@app.command()
def plan(
    repository: Annotated[
        Path,
        typer.Option(exists=True, file_okay=False, help="仓库目录；默认脚本所在仓库。"),
    ] = DEFAULT_MANIFEST.parent,
    base: Annotated[
        str | None,
        typer.Option(help="PR base 的完整 commit SHA；须与 --head 同时提供。"),
    ] = None,
    head: Annotated[
        str | None,
        typer.Option(help="PR head 的完整 commit SHA；须与 --base 同时提供。"),
    ] = None,
    github_output: Annotated[
        Path | None,
        typer.Option(
            dir_okay=False,
            help="追加 build_required 与 input_id 到 GitHub Actions 输出文件。",
        ),
    ] = None,
) -> None:
    """决定是否构建；无相关 PR 变化或已有相同输入的 release 时跳过。

    默认读取固定字体 release；仅首次发布的 404 视为需要构建，其他查询失败报错。
    """
    if (base is None) != (head is None):
        raise typer.BadParameter("--base 与 --head 必须同时提供")
    repository = repository.resolve()
    fingerprint = input_id(repository)
    relevant = True
    if base is not None:
        if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (base, head)):
            raise typer.BadParameter("--base 与 --head 必须是完整 commit SHA")
        changed = subprocess.run(
            ["git", "-C", str(repository), "diff", "--name-only", f"{base}...{head}"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.splitlines()
        inputs = {
            path.relative_to(repository).as_posix() for path in build_inputs(repository)
        }
        relevant = any(
            name in inputs or name.startswith("licenses/terminal-fonts/")
            for name in changed
        )
    required = relevant
    if relevant:
        try:
            payload = release(
                {"repository": "DCjanus/prompts", "tag": "terminal-fonts-latest"}
            )
            required = not release_is_current(payload, fingerprint)
        except HTTPError as error:
            if error.code != 404:
                raise
    values = f"build_required={str(required).lower()}\ninput_id={fingerprint}\n"
    if github_output is not None:
        with github_output.open("a") as output:
            output.write(values)
    console.print("需要构建字体" if required else "构建输入未变化，跳过构建及发布")
    console.print(f"构建输入：{fingerprint}")


@app.command()
def fetch(
    output_dir: Annotated[
        Path, typer.Option(file_okay=False, help="输出来源目录；必须不存在。")
    ],
    manifest: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="来源版本清单。")
    ] = DEFAULT_MANIFEST,
) -> None:
    """下载固定版本，校验 SHA-256，仅解包所需字体；不自动追随 latest。"""
    if output_dir.exists():
        raise typer.BadParameter("输出目录已存在", param_hint="--output-dir")
    with TemporaryDirectory(prefix="terminal-font-sources-") as temp:
        staging = Path(temp)
        for font in load_manifest(manifest):
            asset = approved_asset(font, release(font))
            url = asset["browser_download_url"]
            expected = f"https://github.com/{font['repository']}/releases/download/"
            if not url.startswith(expected):
                raise ValueError("资产不是预期的 GitHub 下载地址")
            archive = staging / font["asset"]
            hasher = hashlib.sha256()  # 匹配 GitHub 提供的资产摘要。
            console.print(f"下载 {font['name']} {font['tag']}…")
            with urlopen(url, timeout=60) as response, archive.open("wb") as target:  # noqa: S310
                while chunk := response.read(1024 * 1024):
                    hasher.update(chunk)
                    target.write(chunk)
            if hasher.hexdigest() != font["sha256"]:
                raise ValueError(f"{font['name']}: 下载校验失败")
            directory = staging / font["name"]
            directory.mkdir()
            with zipfile.ZipFile(archive) as bundle:
                for member in font["members"]:
                    # 仅选择白名单成员并以 basename 写出，拒绝任意路径解包。
                    with (
                        bundle.open(member) as source,
                        (directory / Path(member).name).open("wb") as target,
                    ):
                        shutil.copyfileobj(source, target)
        output_dir.mkdir(parents=True)
        for name in ("sarasa", "lilex"):
            shutil.copytree(staging / name, output_dir / name)
        shutil.copyfile(manifest, output_dir / "terminal-fonts.toml")
    console.print(f"已校验并输出：{output_dir}")


if __name__ == "__main__":
    app()
