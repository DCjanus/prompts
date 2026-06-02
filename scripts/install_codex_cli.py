#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pydantic>=2.13.4",
#     "rich>=15.0.0",
#     "typer>=0.26.5",
#     "zstandard>=0.25.0",
# ]
# ///

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from rich.console import Console
from rich.progress import BarColumn
from rich.progress import DownloadColumn
from rich.progress import Progress
from rich.progress import TextColumn
from rich.progress import TimeRemainingColumn
from rich.progress import TransferSpeedColumn
from rich.table import Table
import typer
import zstandard

GITHUB_HOST = "github.com"
API_BASE = "https://api.github.com"
OWNER = "openai"
REPO = "codex"
API_VERSION = "2026-03-10"

console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=False)

ArchiveKind = Literal["zst", "tar.zst", "tar.gz", "zip", "direct"]
StateStatus = Literal["match", "missing", "stale"]


class ReleaseAsset(BaseModel):
    name: str
    url: str
    browser_download_url: str
    size: int = 0
    digest: str | None = None


class Release(BaseModel):
    tag_name: str
    prerelease: bool = False
    draft: bool = False
    created_at: str | None = None
    published_at: str | None = None
    assets: list[ReleaseAsset]


class InstallSpec(BaseModel):
    install_dir: Path | None = Field(default=None)

    @field_validator("install_dir")
    @classmethod
    def expand_install_dir(cls, value: Path | None) -> Path | None:
        if value is None:
            return value
        return value.expanduser()


@dataclass(frozen=True)
class AuthToken:
    value: str | None
    source: str


@dataclass(frozen=True)
class PlatformTarget:
    triple: str
    executable_name: str


@dataclass(frozen=True)
class SelectedAsset:
    asset: ReleaseAsset
    kind: ArchiveKind


@dataclass(frozen=True)
class InstallResult:
    release: Release
    selected: SelectedAsset
    install_dir: Path
    target_path: Path
    auth_source: str
    path_warning: str | None
    status: Literal["installed", "updated", "unchanged"]
    downloaded: bool


@dataclass(frozen=True)
class ReleaseSelection:
    release: Release
    candidates_count: int


class InstallState(BaseModel):
    target_path: str
    release_tag: str
    asset_name: str
    asset_digest: str | None = None
    executable_sha256: str


def xdg_bin_dir() -> Path:
    """返回用户级可执行文件目录。"""
    xdg_bin_home = os.environ.get("XDG_BIN_HOME")
    if xdg_bin_home:
        return Path(xdg_bin_home).expanduser()
    return Path.home() / ".local" / "bin"


def xdg_state_file() -> Path:
    """返回安装器状态文件路径。"""
    state_home = os.environ.get("XDG_STATE_HOME")
    base = (
        Path(state_home).expanduser()
        if state_home
        else Path.home() / ".local" / "state"
    )
    return base / "prompts" / "install_codex_cli.json"


def current_platform_target() -> PlatformTarget:
    """把当前系统映射到 Codex release asset 使用的 Rust target triple。"""
    system = platform.system().lower()
    machine = platform.machine().lower()

    arch_map = {
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }
    arch = arch_map.get(machine)
    if arch is None:
        raise RuntimeError(f"不支持的 CPU 架构: {machine}")

    if system == "darwin":
        return PlatformTarget(f"{arch}-apple-darwin", "codex")
    if system == "linux":
        return PlatformTarget(f"{arch}-unknown-linux-musl", "codex")
    if system == "windows":
        return PlatformTarget(f"{arch}-pc-windows-msvc", "codex.exe")
    raise RuntimeError(f"不支持的操作系统: {system}")


def github_token() -> AuthToken:
    """按环境变量、GitHub CLI、匿名的顺序获取 GitHub token。"""
    for env_name in ("GH_TOKEN", "GITHUB_TOKEN"):
        token = os.environ.get(env_name)
        if token:
            return AuthToken(token, env_name)

    gh = shutil.which("gh")
    if gh is None:
        return AuthToken(None, "anonymous")

    try:
        result = subprocess.run(
            [gh, "auth", "token", "--hostname", GITHUB_HOST],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return AuthToken(None, "anonymous")

    token = result.stdout.strip()
    if token:
        return AuthToken(token, "gh")
    return AuthToken(None, "anonymous")


def request_headers(token: AuthToken, *, octet_stream: bool = False) -> dict[str, str]:
    accept = (
        "application/octet-stream" if octet_stream else "application/vnd.github+json"
    )
    headers = {
        "Accept": accept,
        "User-Agent": "prompts-install-codex-cli",
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token.value:
        headers["Authorization"] = f"Bearer {token.value}"
    return headers


def urlopen_json(url: str, token: AuthToken) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=request_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API 请求失败: HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API 请求失败: {exc}") from exc


def urlopen_bytes(url: str, token: AuthToken, *, description: str) -> bytes:
    request = urllib.request.Request(
        url, headers=request_headers(token, octet_stream=True)
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            total = response.length
            chunks: list[bytes] = []
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(description, total=total)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    progress.update(task, advance=len(chunk))
            return b"".join(chunks)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"下载 release asset 失败: HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"下载 release asset 失败: {exc}") from exc


def step(message: str) -> None:
    console.print(f"[bold cyan]=>[/bold cyan] {message}")


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    raise AssertionError("unreachable")


def fetch_latest_release(token: AuthToken) -> ReleaseSelection:
    """读取 openai/codex 最新 release，包含 prerelease。"""
    raw = urlopen_json(f"{API_BASE}/repos/{OWNER}/{REPO}/releases?per_page=1", token)
    if not isinstance(raw, list):
        raise RuntimeError("GitHub releases 响应结构不符合预期")

    try:
        releases = [Release.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise RuntimeError(f"GitHub release 响应结构不符合预期: {exc}") from exc

    candidates = [release for release in releases if not release.draft]
    if not candidates:
        raise RuntimeError("openai/codex 没有可安装的 release")
    release = max(
        candidates, key=lambda release: release.published_at or release.created_at or ""
    )
    return ReleaseSelection(release=release, candidates_count=len(candidates))


def select_codex_asset(release: Release, target: PlatformTarget) -> SelectedAsset:
    """选择当前平台对应的 Codex CLI 预编译产物。"""
    preferred: list[tuple[str, ArchiveKind]] = [
        (f"codex-{target.triple}.zst", "zst"),
        (f"codex-{target.triple}.tar.zst", "tar.zst"),
        (f"codex-{target.triple}.tar.gz", "tar.gz"),
        (f"codex-{target.triple}.exe.zst", "zst"),
        (f"codex-{target.triple}.exe.tar.zst", "tar.zst"),
        (f"codex-{target.triple}.zip", "zip"),
        (f"codex-{target.triple}.exe.zip", "zip"),
        (f"codex-{target.triple}.exe", "direct"),
    ]
    assets = {asset.name: asset for asset in release.assets}
    for name, kind in preferred:
        if name in assets:
            return SelectedAsset(assets[name], kind)

    available = "\n".join(
        f"  - {asset.name}"
        for asset in release.assets
        if asset.name.startswith("codex-")
    )
    raise RuntimeError(
        f"未找到当前平台对应的 Codex CLI asset: {target.triple}\n可用 codex asset:\n{available}"
    )


def asset_binary_basename(asset_name: str) -> str:
    """从 archive 文件名推导内部 binary 常见文件名。"""
    for suffix in (".tar.zst", ".tar.gz", ".zip", ".zst"):
        if asset_name.endswith(suffix):
            return asset_name[: -len(suffix)]
    return asset_name


def decompress_zst(payload: bytes) -> bytes:
    """解压 zstd payload。"""
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(payload)) as reader:
        return reader.read()


def extract_executable(
    payload: bytes, selected: SelectedAsset, executable_name: str
) -> bytes:
    """从 release asset 中取出 codex 可执行文件内容。"""
    if selected.kind == "direct":
        return payload

    if selected.kind == "zst":
        return decompress_zst(payload)

    fallback_name = asset_binary_basename(selected.asset.name)
    if selected.kind == "tar.zst":
        payload = decompress_zst(payload)

    if selected.kind == "tar.gz":
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            regular_members = [
                member for member in archive.getmembers() if member.isfile()
            ]
            for member in regular_members:
                name = Path(member.name).name
                if name not in {executable_name, fallback_name}:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    break
                return extracted.read()
            if len(regular_members) == 1:
                extracted = archive.extractfile(regular_members[0])
                if extracted is not None:
                    return extracted.read()

    if selected.kind == "tar.zst":
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            regular_members = [
                member for member in archive.getmembers() if member.isfile()
            ]
            for member in regular_members:
                name = Path(member.name).name
                if name not in {executable_name, fallback_name}:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    break
                return extracted.read()
            if len(regular_members) == 1:
                extracted = archive.extractfile(regular_members[0])
                if extracted is not None:
                    return extracted.read()

    if selected.kind == "zip":
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            regular_infos = [info for info in archive.infolist() if not info.is_dir()]
            for info in regular_infos:
                name = Path(info.filename).name
                if name in {executable_name, fallback_name}:
                    return archive.read(info)
            if len(regular_infos) == 1:
                return archive.read(regular_infos[0])

    raise RuntimeError(f"asset 中未找到可执行文件: {executable_name}")


def install_executable(
    content: bytes,
    target_path: Path,
) -> Literal["installed", "updated", "unchanged"]:
    """按内容差异原子写入目标可执行文件。"""
    if target_path.exists():
        existing = target_path.read_bytes()
        if existing == content:
            return "unchanged"
        status: Literal["installed", "updated", "unchanged"] = "updated"
    else:
        status = "installed"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target_path.parent,
        prefix=f".{target_path.name}.",
        delete=False,
    ) as tmp_file:
        tmp_path = Path(tmp_file.name)
        tmp_file.write(content)

    mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP
    mode |= stat.S_IROTH | stat.S_IXOTH
    tmp_path.chmod(mode)
    os.replace(tmp_path, target_path)
    return status


def target_key(target_path: Path) -> str:
    try:
        return str(target_path.resolve())
    except OSError:
        return str(target_path.expanduser().absolute())


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_state() -> dict[str, InstallState]:
    path = xdg_state_file()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    states: dict[str, InstallState] = {}
    for key, value in raw.items():
        try:
            states[key] = InstallState.model_validate(value)
        except ValidationError:
            continue
    return states


def save_state(state: InstallState) -> None:
    path = xdg_state_file()
    states = load_state()
    states[state.target_path] = state
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: value.model_dump() for key, value in sorted(states.items())}
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def make_state(
    target_path: Path,
    release: Release,
    selected: SelectedAsset,
    executable_sha256: str,
) -> InstallState:
    return InstallState(
        target_path=target_key(target_path),
        release_tag=release.tag_name,
        asset_name=selected.asset.name,
        asset_digest=selected.asset.digest,
        executable_sha256=executable_sha256,
    )


def state_status(
    target_path: Path, release: Release, selected: SelectedAsset
) -> StateStatus:
    state = load_state().get(target_key(target_path))
    if state is None:
        return "missing"
    if not target_path.exists():
        return "stale"

    if state.release_tag != release.tag_name:
        return "stale"
    if state.asset_name != selected.asset.name:
        return "stale"
    if state.asset_digest != selected.asset.digest:
        return "stale"
    if sha256_file(target_path) != state.executable_sha256:
        return "stale"
    return "match"


def release_version(tag_name: str) -> str | None:
    match = re.search(r"(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)", tag_name)
    if match is None:
        return None
    return match.group(1)


def installed_version_matches(target_path: Path, release: Release) -> bool:
    version = release_version(release.tag_name)
    if version is None or not target_path.exists():
        return False
    try:
        result = subprocess.run(
            [str(target_path), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return version in result.stdout.strip()


def path_entries() -> list[Path]:
    entries: list[Path] = []
    for raw in os.environ.get("PATH", "").split(os.pathsep):
        if not raw:
            continue
        entries.append(Path(raw).expanduser())
    return entries


def same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.expanduser().absolute() == right.expanduser().absolute()


def path_warning(install_dir: Path, target_path: Path) -> str | None:
    """检查安装目录是否能被当前 shell 解析到。"""
    if not any(same_path(entry, install_dir) for entry in path_entries()):
        return f"{install_dir} 不在 PATH 中；当前 shell 可能无法直接运行 {target_path.name}"

    resolved = shutil.which(target_path.name)
    if resolved is None:
        return None
    resolved_path = Path(resolved)
    if not same_path(resolved_path, target_path):
        return f"PATH 中更靠前的 {target_path.name} 指向 {resolved_path}，不是本次安装的 {target_path}"
    return None


def run_install(spec: InstallSpec) -> InstallResult:
    token = github_token()
    step(f"开始获取 openai/codex release 列表（auth: {token.source}）")
    release_selection = fetch_latest_release(token)
    release = release_selection.release
    step(
        f"获取到 {release_selection.candidates_count} 个可安装 release，"
        f"选中 {release.tag_name}（published_at: {release.published_at or 'unknown'}）"
    )
    target = current_platform_target()
    step(f"当前平台匹配 target: {target.triple}")
    selected = select_codex_asset(release, target)
    install_dir = spec.install_dir or xdg_bin_dir()
    target_path = install_dir / target.executable_name
    step(
        f"选定下载文件: {selected.asset.name} "
        f"({format_size(selected.asset.size)}, {selected.kind})"
    )

    current_state = state_status(target_path, release, selected)
    if current_state == "match":
        step("本地状态记录命中，跳过下载")
        return InstallResult(
            release=release,
            selected=selected,
            install_dir=install_dir,
            target_path=target_path,
            auth_source=token.source,
            path_warning=path_warning(install_dir, target_path),
            status="unchanged",
            downloaded=False,
        )

    if current_state == "stale":
        step("本地状态记录已过期或目标文件被替换，继续下载更新")
    elif installed_version_matches(target_path, release):
        step("目标文件版本已是最新，跳过下载")
        save_state(make_state(target_path, release, selected, sha256_file(target_path)))
        return InstallResult(
            release=release,
            selected=selected,
            install_dir=install_dir,
            target_path=target_path,
            auth_source=token.source,
            path_warning=path_warning(install_dir, target_path),
            status="unchanged",
            downloaded=False,
        )

    step(f"开始下载 {selected.asset.name}，文件体积 {format_size(selected.asset.size)}")
    payload = urlopen_bytes(
        selected.asset.url,
        token,
        description=f"下载 {selected.asset.name}",
    )
    step("解压 release asset")
    executable = extract_executable(payload, selected, target.executable_name)
    step(f"安装到 {target_path}")
    status = install_executable(executable, target_path)
    save_state(make_state(target_path, release, selected, sha256_bytes(executable)))

    return InstallResult(
        release=release,
        selected=selected,
        install_dir=install_dir,
        target_path=target_path,
        auth_source=token.source,
        path_warning=path_warning(install_dir, target_path),
        status=status,
        downloaded=True,
    )


def print_result(result: InstallResult) -> None:
    table = Table(show_header=False, box=None)
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")
    table.add_row("Release", result.release.tag_name)
    table.add_row("Asset", result.selected.asset.name)
    table.add_row("Install dir", str(result.install_dir))
    table.add_row("Target", str(result.target_path))
    table.add_row("Auth", result.auth_source)
    table.add_row("Status", result.status)
    table.add_row("Downloaded", "yes" if result.downloaded else "no")
    console.print(table)
    if result.path_warning:
        console.print(f"[yellow]Warning:[/yellow] {result.path_warning}")


@app.command(help="从 GitHub release 下载并安装最新 Codex CLI 预编译 binary。")
def main(
    install_dir: Annotated[
        Path | None,
        typer.Option(
            "--install-dir",
            help="安装目录；默认使用 $XDG_BIN_HOME，未设置时使用 ~/.local/bin",
        ),
    ] = None,
) -> None:
    try:
        spec = InstallSpec(install_dir=install_dir)
        result = run_install(spec)
    except (RuntimeError, ValidationError) as exc:
        console.print(f"[red]失败：{exc}[/red]")
        raise typer.Exit(code=1)

    print_result(result)


if __name__ == "__main__":
    app()
