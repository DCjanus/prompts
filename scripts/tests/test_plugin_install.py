"""在隔离配置中验证 Git marketplace 安装及同版本更新契约。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("codex") is None, reason="需要 Codex CLI；CI 会安装")
def test_git_marketplace_installs_complete_plugin_and_updates_same_version(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    catalog_path = Path(".agents/plugins/marketplace.json")
    (source / catalog_path).parent.mkdir(parents=True)
    shutil.copy2(REPOSITORY_ROOT / catalog_path, source / catalog_path)
    catalog = json.loads((source / catalog_path).read_text())
    entry = catalog["plugins"][0]
    plugin_relative = Path(entry["source"]["path"])
    shutil.copytree(
        REPOSITORY_ROOT / plugin_relative,
        source / plugin_relative,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv"),
    )
    config_home = tmp_path / "codex-home"
    config_home.mkdir()
    # 用本地 Git 仓库模拟远端，不访问 GitHub 或使用用户的 Codex 配置。
    environment = dict(os.environ)
    environment.update(
        CODEX_HOME=str(config_home),
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0=f"url.{source.as_uri()}.insteadOf",
        GIT_CONFIG_VALUE_0="https://example.invalid/plugin-install-test.git",
    )

    def run(*command):
        result = subprocess.run(
            command,
            cwd=tmp_path,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    def commit():
        run("git", "-C", str(source), "add", ".")
        run(
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Plugin test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "Update plugin fixture",
        )

    run("git", "-C", str(source), "init", "-b", "master")
    commit()
    run(
        "codex",
        "plugin",
        "marketplace",
        "add",
        "https://example.invalid/plugin-install-test.git",
        "--ref",
        "master",
        "--json",
    )
    installed = json.loads(
        run("codex", "plugin", "add", f"{entry['name']}@{catalog['name']}", "--json")
    )
    cache = Path(installed["installedPath"])
    packaged_skills = source / plugin_relative / "skills"
    expected = {
        path.relative_to(packaged_skills) for path in packaged_skills.rglob("SKILL.md")
    }
    assert expected
    assert {
        path.relative_to(cache / "skills")
        for path in (cache / "skills").rglob("SKILL.md")
    } == expected
    for relative in expected:
        assert (cache / "skills" / relative).read_bytes() == (
            packaged_skills / relative
        ).read_bytes()
    assert (cache / "licenses/grill-me/LICENSE").is_file()
    assert (cache / "licenses/domain-modeling/LICENSE").is_file()
    run(
        "uv",
        "run",
        "--script",
        str(cache / "skills/uv-cli-creator/scripts/init_cli.py"),
        "--help",
    )

    # 仅修改内容、不变更 manifest 版本，仍须更新已安装副本。
    changed = Path("uv-cli-creator/SKILL.md")
    with (packaged_skills / changed).open("a") as stream:
        stream.write("\nPlugin update integration marker.\n")
    commit()
    upgraded = json.loads(
        run("codex", "plugin", "marketplace", "upgrade", catalog["name"], "--json")
    )
    assert not upgraded["errors"]
    assert upgraded["upgradedRoots"]
    assert (cache / "skills" / changed).read_bytes() == (
        packaged_skills / changed
    ).read_bytes()
