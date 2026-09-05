"""在隔离配置中验证 Git marketplace 安装及同版本更新契约。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


async def list_skills_from_app_server(cwd, environment, *, expected_update=None):
    """读取实际技能目录，不创建任务或调用模型。"""
    process = await asyncio.create_subprocess_exec(
        "codex",
        "app-server",
        cwd=cwd,
        env=environment,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def request(identifier, method, params):
        message = {"id": identifier, "method": method, "params": params}
        process.stdin.write((json.dumps(message) + "\n").encode())
        await process.stdin.drain()

        async def response():
            while line := await process.stdout.readline():
                payload = json.loads(line)
                if payload.get("id") == identifier:
                    assert "error" not in payload, payload
                    return payload["result"]
            raise AssertionError("app-server 在返回结果前退出")

        return await asyncio.wait_for(response(), timeout=30)

    try:
        await request(
            1, "initialize", {"clientInfo": {"name": "plugin-test", "version": "1"}}
        )
        process.stdin.write(b'{"method":"initialized"}\n')
        await process.stdin.drain()
        if expected_update is not None:
            path, content = expected_update

            async def wait_for_update():
                while not path.exists() or path.read_bytes() != content:
                    await asyncio.sleep(0.05)

            await asyncio.wait_for(wait_for_update(), timeout=30)
        return await request(
            2, "skills/list", {"cwds": [str(cwd)], "forceReload": True}
        )
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()


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
    git_config = tmp_path / "gitconfig"
    environment.update(
        CODEX_HOME=str(config_home),
        GIT_CONFIG_GLOBAL=str(git_config),
        GIT_CONFIG_NOSYSTEM="1",
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

    # 自动刷新会移除命令级 GIT_CONFIG_COUNT；使用隔离的全局配置模拟 Git 远端。
    run(
        "git",
        "config",
        "--file",
        str(git_config),
        f"url.{source.as_uri()}.insteadOf",
        "https://example.invalid/plugin-install-test.git",
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
    listing = asyncio.run(list_skills_from_app_server(tmp_path, environment))
    discovered = [
        skill
        for item in listing["data"]
        for skill in item["skills"]
        if Path(skill["path"]).is_relative_to(cache)
    ]
    names = {skill["name"] for skill in discovered}
    assert names == {f"{entry['name']}:{path.parent.name}" for path in expected}
    assert len(discovered) == len(names)
    for skill in discovered:
        assert skill["enabled"]
        prompt = (skill.get("interface") or {}).get("defaultPrompt") or ""
        for mentioned in re.findall(r"\$([\w:-]+)", prompt):
            assert mentioned in names, (
                f"{skill['name']} 默认提示词引用未注册技能：{mentioned}"
            )
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
    # 再产生一个同版本提交，仅启动 app-server，验证日常自动刷新路径。
    with (packaged_skills / changed).open("a") as stream:
        stream.write("\nApp-server startup update marker.\n")
    commit()
    asyncio.run(
        list_skills_from_app_server(
            tmp_path,
            environment,
            expected_update=(
                cache / "skills" / changed,
                (packaged_skills / changed).read_bytes(),
            ),
        )
    )
