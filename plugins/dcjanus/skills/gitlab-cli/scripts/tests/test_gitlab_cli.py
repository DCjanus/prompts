from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "gitlab_cli.py"
SPEC = importlib.util.spec_from_file_location("gitlab_cli", SCRIPT_PATH)
assert SPEC is not None
gitlab_cli = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gitlab_cli)


@pytest.mark.parametrize(
    "level,assigned,reason",
    [
        (40, False, "actor-is-maintainer"),
        (50, False, "actor-is-maintainer"),
        (30, True, "actor-is-assignee"),
        (30, False, "external-contribution"),
        (None, False, "identity-unknown"),
    ],
)
def test_notice_roles_and_assignment(monkeypatch, tmp_path, level, assigned, reason):
    def api(**kwargs):
        assert kwargs["method"] == "GET"
        assert kwargs["hostname"] == "gitlab.example"
        if kwargs["endpoint"] == "user":
            return {"id": 7}
        assert kwargs["endpoint"] == "projects/group%2Frepo/members/all/7"
        if level is None:
            raise RuntimeError("403")
        return {"access_level": level}

    monkeypatch.setattr(gitlab_cli, "run_glab_api", api)
    body, actual = gitlab_cli.prepare_notice(
        "Technical",
        project="group/repo",
        cwd=tmp_path,
        hostname="gitlab.example",
        actor_id=None,
        assignee_ids=[7] if assigned else [],
        notice_mode="auto",
        notice_language="zh",
    )
    assert actual == reason
    assert (gitlab_cli.CHINESE in body) == (
        reason in {"identity-unknown", "external-contribution"}
    )


def test_mr_create_dry_run(monkeypatch, tmp_path):
    source = tmp_path / "body.md"
    source.write_text("Technical")

    def api(**kwargs):
        assert kwargs["method"] == "GET"
        return {"access_level": 30}

    monkeypatch.setattr(gitlab_cli, "run_glab_api", api)
    result = CliRunner().invoke(
        gitlab_cli.app,
        [
            "mr",
            "create",
            "--title",
            "Fix",
            "--target-branch",
            "main",
            "--source-branch",
            "fix",
            "--project",
            "1",
            "--cwd",
            str(tmp_path),
            "--description-file",
            str(source),
            "--actor-id",
            "7",
            "--assignee-id",
            "7",
            "--notice-language",
            "zh",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    preview = json.loads(result.stdout)
    assert preview["payload"]["description"] == "Technical\n"
    assert preview["notice_reason"] == "actor-is-assignee"
    assert source.read_text() == "Technical"


def test_mr_post_write_reconciles_assignee(monkeypatch, tmp_path):
    writes = []
    actual = {
        "iid": 1,
        "project_id": 2,
        "target_project_id": 2,
        "description": "Technical\n\n" + gitlab_cli.CHINESE,
        "assignees": [{"id": 7}],
        "web_url": "https://gitlab.example/p/-/merge_requests/1",
    }

    def api(**kwargs):
        if kwargs["endpoint"].endswith("members/all/7"):
            return {"access_level": 30}
        if kwargs["method"] == "PUT":
            writes.append(kwargs["payload"])
            actual.update(kwargs["payload"])
        return actual.copy()

    monkeypatch.setattr(gitlab_cli, "run_glab_api", api)
    result = gitlab_cli.finish_mr_notice(
        actual,
        project="2",
        cwd=tmp_path,
        hostname="gitlab.example",
        actor_id=7,
        notice_mode="auto",
        notice_language="zh",
    )
    assert result["description"] == "Technical\n"
    assert writes == [{"description": "Technical\n"}]


def test_mr_update_dry_run_uses_target_and_existing_assignees(monkeypatch, tmp_path):
    source = tmp_path / "body.md"
    source.write_text("Technical\n\n" + gitlab_cli.CHINESE)

    def api(**kwargs):
        assert kwargs["method"] == "GET"
        if kwargs["endpoint"] == "projects/2/merge_requests/1":
            return {
                "target_project_id": 2,
                "description": source.read_text(),
                "assignees": [{"id": 7}],
                "reviewers": [{"id": 9}],
            }
        assert kwargs["endpoint"] == "projects/2/members/all/7"
        return {"access_level": 30}

    monkeypatch.setattr(gitlab_cli, "run_glab_api", api)
    result = CliRunner().invoke(
        gitlab_cli.app,
        [
            "mr",
            "update",
            "1",
            "--project",
            "2",
            "--cwd",
            str(tmp_path),
            "--description-file",
            str(source),
            "--actor-id",
            "7",
            "--notice-language",
            "zh",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["payload"]["description"] == "Technical\n"


def test_mr_verification_failure_preserves_link(monkeypatch, tmp_path):
    response = {
        "project_id": 2,
        "iid": 1,
        "web_url": "https://gitlab.example/p/-/merge_requests/1",
    }

    def api(**kwargs):
        raise RuntimeError("read failed")

    monkeypatch.setattr(gitlab_cli, "run_glab_api", api)
    with pytest.raises(
        RuntimeError, match="MR 已写入，请勿重复创建：https://gitlab.example"
    ):
        gitlab_cli.finish_mr_notice(
            response,
            project="2",
            cwd=tmp_path,
            hostname="gitlab.example",
            actor_id=7,
            notice_mode="auto",
            notice_language="zh",
        )


def test_parse_merge_request_ref() -> None:
    assert gitlab_cli.parse_merge_request_ref("refs/merge-requests/9/head") == 9
    assert gitlab_cli.parse_merge_request_ref("refs/merge-requests/9/merge") == 9
    assert gitlab_cli.parse_merge_request_ref("refs/heads/main") is None


def test_ci_lint_resolves_merge_request_ref_to_source_branch(
    monkeypatch, tmp_path: Path
) -> None:
    ci_file = tmp_path / ".gitlab-ci.yml"
    ci_file.write_text("test:\n  script: echo ok\n", encoding="utf-8")
    lint_payloads: list[dict[str, object] | None] = []

    def fake_run_glab_api(
        *,
        endpoint: str,
        method: str,
        payload: dict[str, object] | None,
        cwd: Path,
        hostname: str | None,
    ) -> dict[str, object]:
        assert cwd == tmp_path
        assert hostname is None

        if endpoint == "projects/122477/merge_requests/9":
            assert method == "GET"
            assert payload is None
            return {"source_branch": "chore/sync-knots-api-master"}
        if endpoint == "projects/122477/ci/lint":
            assert method == "POST"
            lint_payloads.append(payload)
            return {"valid": True, "errors": [], "warnings": []}
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(gitlab_cli, "run_glab_api", fake_run_glab_api)

    gitlab_cli.ci_lint(
        path=ci_file,
        cwd=tmp_path,
        project="122477",
        hostname=None,
        dry_run=True,
        include_jobs=False,
        ref="refs/merge-requests/9/head",
        source_branch=None,
        show_merged_yaml=False,
        as_json=True,
    )

    assert lint_payloads == [
        {
            "content": "test:\n  script: echo ok\n",
            "dry_run": True,
            "include_jobs": False,
            "ref": "chore/sync-knots-api-master",
        }
    ]


def test_ci_lint_uses_explicit_source_branch_for_merge_request_ref(
    monkeypatch, tmp_path: Path
) -> None:
    ci_file = tmp_path / ".gitlab-ci.yml"
    ci_file.write_text("test:\n  script: echo ok\n", encoding="utf-8")
    lint_payloads: list[dict[str, object] | None] = []

    def fake_run_glab_api(
        *,
        endpoint: str,
        method: str,
        payload: dict[str, object] | None,
        cwd: Path,
        hostname: str | None,
    ) -> dict[str, object]:
        assert method == "POST"
        assert cwd == tmp_path
        assert hostname is None

        if endpoint == "projects/122477/ci/lint":
            lint_payloads.append(payload)
            return {"valid": True, "errors": [], "warnings": []}
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(gitlab_cli, "run_glab_api", fake_run_glab_api)

    gitlab_cli.ci_lint(
        path=ci_file,
        cwd=tmp_path,
        project="122477",
        hostname=None,
        dry_run=True,
        include_jobs=False,
        ref="refs/merge-requests/9/head",
        source_branch="chore/sync-knots-api-master",
        show_merged_yaml=False,
        as_json=True,
    )

    assert lint_payloads == [
        {
            "content": "test:\n  script: echo ok\n",
            "dry_run": True,
            "include_jobs": False,
            "ref": "chore/sync-knots-api-master",
        }
    ]
