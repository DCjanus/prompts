#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "parfive>=2.3.1",
#     "pydantic>=2.13.4",
#     "rich>=15.0.0",
#     "typer>=0.27.0",
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

from parfive import Downloader
from pydantic import BaseModel, Field, ValidationError, field_validator
from rich.console import Console
from rich.table import Table
import typer
import zstandard

GITHUB_HOST = "github.com"
API_BASE = "https://api.github.com"
OWNER = "openai"
REPO = "codex"
API_VERSION = "2026-03-10"
DOWNLOAD_SPLITS = 4

console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=False)

ArchiveKind = Literal["zst", "tar.zst", "tar.gz", "zip", "direct"]
CompletionShell = Literal["bash", "elvish", "fish", "powershell", "zsh"]
CompletionStatus = Literal["installed", "updated", "unchanged", "skipped"]
StateStatus = Literal["match", "missing", "stale"]
VERSION_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])"
    r"v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)"
    r"(?![0-9A-Za-z])"
)


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
    completion_shell: CompletionShell | None = Field(default=None)

    @field_validator("install_dir")
    @classmethod
    def expand_install_dir(cls, value: Path | None) -> Path | None:
        if value is None:
            return value
        return value.expanduser()

    @field_validator("completion_shell", mode="before")
    @classmethod
    def normalize_completion_shell(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.lower()


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
    completion: "CompletionInstallResult"


@dataclass(frozen=True)
class ReleaseSelection:
    release: Release
    candidates_count: int


@dataclass(frozen=True)
class CompletionTarget:
    shell: CompletionShell
    path: Path


@dataclass(frozen=True)
class CompletionInstallResult:
    shell: CompletionShell | None
    path: Path | None
    status: CompletionStatus
    warning: str | None = None


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


def xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".config"


def xdg_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".local" / "share"


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


def request_headers(token: AuthToken) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
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


def download_asset(asset: ReleaseAsset) -> bytes:
    """通过多个 HTTP Range 请求并行下载 release asset。"""
    with tempfile.TemporaryDirectory(prefix="install-codex-cli-") as temp_dir:
        destination_dir = Path(temp_dir)
        downloader = Downloader(
            max_conn=1,
            max_splits=DOWNLOAD_SPLITS,
            progress=console.is_terminal,
            overwrite=True,
        )
        downloader.enqueue_file(
            asset.browser_download_url,
            path=destination_dir,
            filename=asset.name,
            overwrite=True,
        )
        results = downloader.download()
        if results.errors:
            details = "; ".join(
                str(error).replace("\n", " ") for error in results.errors
            )
            raise RuntimeError(f"下载 release asset 失败: {details}")
        if len(results) != 1:
            raise RuntimeError(
                f"下载 release asset 失败: 预期得到 1 个文件，实际得到 {len(results)} 个"
            )

        try:
            return Path(results[0]).read_bytes()
        except OSError as exc:
            raise RuntimeError(f"读取下载的 release asset 失败: {exc}") from exc


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


def write_text_atomic(path: Path, content: str) -> CompletionStatus:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return "unchanged"

    status: CompletionStatus = "updated" if path.exists() else "installed"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as tmp_file:
        tmp_path = Path(tmp_file.name)
        tmp_file.write(content)
    os.replace(tmp_path, path)
    return status


def detect_completion_shell() -> CompletionShell | None:
    shell_path = os.environ.get("SHELL")
    if shell_path:
        shell_name = Path(shell_path).name.lower()
        if shell_name in {"bash", "fish", "zsh", "elvish"}:
            return shell_name
        if shell_name in {"pwsh", "powershell", "powershell.exe", "pwsh.exe"}:
            return "powershell"

    if platform.system().lower() == "windows":
        return "powershell"
    return None


def zsh_fpath_dirs() -> list[Path]:
    zsh = shutil.which("zsh")
    if zsh is None:
        return []
    try:
        result = subprocess.run(
            [zsh, "-lc", "print -r -- $fpath"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    return [Path(raw).expanduser() for raw in result.stdout.split() if raw]


def writable_zsh_completion_dir() -> Path | None:
    home = Path.home()
    for directory in zsh_fpath_dirs():
        try:
            resolved = directory.expanduser().resolve()
        except OSError:
            continue
        if not directory.exists() or not directory.is_dir():
            continue
        if not same_path_or_child(resolved, home):
            continue
        if os.access(directory, os.W_OK):
            return directory
    return None


def same_path_or_child(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.expanduser().resolve())
    except ValueError:
        return False
    except OSError:
        return False
    return True


def completion_target_for_shell(shell: CompletionShell) -> CompletionTarget | None:
    if shell == "fish":
        return CompletionTarget(
            shell, xdg_config_home() / "fish" / "completions" / "codex.fish"
        )
    if shell == "bash":
        return CompletionTarget(
            shell, xdg_data_home() / "bash-completion" / "completions" / "codex.bash"
        )
    if shell == "zsh":
        directory = writable_zsh_completion_dir()
        if directory is None:
            return None
        return CompletionTarget(shell, directory / "_codex")
    if shell == "elvish":
        return CompletionTarget(
            shell, xdg_config_home() / "elvish" / "lib" / "codex-completion.elv"
        )
    if shell == "powershell":
        return None
    raise AssertionError("unreachable")


def install_shell_completion(
    target_path: Path, requested_shell: CompletionShell | None
) -> CompletionInstallResult:
    shell = requested_shell or detect_completion_shell()
    if shell is None:
        return CompletionInstallResult(
            shell=None,
            path=None,
            status="skipped",
            warning="未能从 SHELL 环境变量判断当前 shell，跳过补全安装",
        )

    completion_target = completion_target_for_shell(shell)
    if completion_target is None:
        return CompletionInstallResult(
            shell=shell,
            path=None,
            status="skipped",
            warning=f"当前 shell {shell} 没有可自动写入的用户级补全目录",
        )

    try:
        result = subprocess.run(
            [str(target_path), "completion", shell],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return CompletionInstallResult(
            shell=shell,
            path=completion_target.path,
            status="skipped",
            warning=f"生成 {shell} 补全脚本失败: {exc}",
        )

    status = write_text_atomic(completion_target.path, result.stdout)
    return CompletionInstallResult(
        shell=shell,
        path=completion_target.path,
        status=status,
        warning=None,
    )


def target_key(target_path: Path) -> str:
    try:
        return str(target_path.resolve())
    except OSError:
        return str(target_path.expanduser().absolute())


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verify_asset_digest(payload: bytes, digest: str | None, asset_name: str) -> None:
    if digest is None:
        return

    if ":" in digest:
        algorithm, expected = digest.split(":", 1)
    else:
        algorithm, expected = "sha256", digest
    algorithm = algorithm.lower()
    expected = expected.lower()

    try:
        hasher = hashlib.new(algorithm)
    except ValueError as exc:
        raise RuntimeError(f"不支持的 release asset digest 算法: {algorithm}") from exc

    hasher.update(payload)
    actual = hasher.hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"release asset digest 不匹配: {asset_name} "
            f"expected {digest}, actual {algorithm}:{actual}"
        )


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
    match = VERSION_PATTERN.search(tag_name)
    if match is None:
        return None
    return match.group(1)


def parse_version_token(output: str) -> str | None:
    match = VERSION_PATTERN.search(output)
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
    return parse_version_token(result.stdout.strip()) == version


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


def install_result(
    *,
    release: Release,
    selected: SelectedAsset,
    install_dir: Path,
    target_path: Path,
    auth_source: str,
    status: Literal["installed", "updated", "unchanged"],
    downloaded: bool,
    completion_shell: CompletionShell | None,
) -> InstallResult:
    completion = install_shell_completion(target_path, completion_shell)
    return InstallResult(
        release=release,
        selected=selected,
        install_dir=install_dir,
        target_path=target_path,
        auth_source=auth_source,
        path_warning=path_warning(install_dir, target_path),
        status=status,
        downloaded=downloaded,
        completion=completion,
    )


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
        return install_result(
            release=release,
            selected=selected,
            install_dir=install_dir,
            target_path=target_path,
            auth_source=token.source,
            status="unchanged",
            downloaded=False,
            completion_shell=spec.completion_shell,
        )

    if current_state == "stale":
        step("本地状态记录已过期或目标文件被替换，继续下载更新")
    elif installed_version_matches(target_path, release):
        step("目标文件版本已是最新，跳过下载")
        save_state(make_state(target_path, release, selected, sha256_file(target_path)))
        return install_result(
            release=release,
            selected=selected,
            install_dir=install_dir,
            target_path=target_path,
            auth_source=token.source,
            status="unchanged",
            downloaded=False,
            completion_shell=spec.completion_shell,
        )

    step(f"开始下载 {selected.asset.name}，文件体积 {format_size(selected.asset.size)}")
    payload = download_asset(selected.asset)
    verify_asset_digest(payload, selected.asset.digest, selected.asset.name)
    step("解压 release asset")
    executable = extract_executable(payload, selected, target.executable_name)
    step(f"安装到 {target_path}")
    status = install_executable(executable, target_path)
    save_state(make_state(target_path, release, selected, sha256_bytes(executable)))

    return install_result(
        release=release,
        selected=selected,
        install_dir=install_dir,
        target_path=target_path,
        auth_source=token.source,
        status=status,
        downloaded=True,
        completion_shell=spec.completion_shell,
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
    if result.completion.shell:
        table.add_row("Completion shell", result.completion.shell)
    if result.completion.path:
        table.add_row("Completion path", str(result.completion.path))
    table.add_row("Completion status", result.completion.status)
    console.print(table)
    if result.path_warning:
        console.print(f"[yellow]Warning:[/yellow] {result.path_warning}")
    if result.completion.warning:
        console.print(f"[yellow]Warning:[/yellow] {result.completion.warning}")


@app.command(help="从 GitHub release 下载并安装最新 Codex CLI 预编译 binary。")
def main(
    install_dir: Annotated[
        Path | None,
        typer.Option(
            "--install-dir",
            help="安装目录；默认使用 $XDG_BIN_HOME，未设置时使用 ~/.local/bin",
        ),
    ] = None,
    completion_shell: Annotated[
        str | None,
        typer.Option(
            "--completion-shell",
            help="要安装补全脚本的 shell；默认从 $SHELL 自动探测。可选：bash、elvish、fish、powershell、zsh",
        ),
    ] = None,
) -> None:
    try:
        spec = InstallSpec(install_dir=install_dir, completion_shell=completion_shell)
        result = run_install(spec)
    except (RuntimeError, ValidationError) as exc:
        console.print(f"[red]失败：{exc}[/red]")
        raise typer.Exit(code=1)

    print_result(result)


if __name__ == "__main__":
    app()
