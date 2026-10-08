#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = [
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
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from urllib.parse import quote
from urllib.request import Request, urlopen

import tomllib
import typer
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
