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


@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_mr_preserves_body(monkeypatch, tmp_path, action, dry_run):
    source = tmp_path / "body.md"
    original = "Technical\n\n---\n\nUser-authored footer\n"
    source.write_text(original)
    writes = []
    actual = {
        "iid": 1,
        "project_id": 2,
        "title": "Fix",
        "description": original,
        "web_url": "https://gitlab.example/p/-/merge_requests/1",
    }

    def api(**kwargs):
        assert kwargs["endpoint"] in {
            "projects/2/merge_requests",
            "projects/2/merge_requests/1",
        }
        if kwargs["method"] != "GET":
            writes.append(kwargs["payload"])
            actual.update(kwargs["payload"])
        return actual.copy()

    monkeypatch.setattr(gitlab_cli, "run_glab_api", api)
    command = ["mr", action]
    if action == "create":
        command += ["--target-branch", "main", "--source-branch", "fix"]
    else:
        command += ["1"]
    command += [
        "--title",
        "Fix",
        "--project",
        "2",
        "--cwd",
        str(tmp_path),
        "--description-file",
        str(source),
        "--assignee-id",
        "7",
        "--json",
    ]
    if dry_run:
        command += ["--dry-run"]
    result = CliRunner().invoke(gitlab_cli.app, command)
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    if dry_run:
        assert output["payload"]["description"] == original
        assert writes == []
    else:
        assert output["description"] == original
        assert len(writes) == 1
        assert writes[0]["description"] == original
        assert writes[0]["assignee_ids"] == [7]
    assert source.read_text() == original


def test_mr_metadata_update_leaves_description_untouched(monkeypatch, tmp_path):
    writes = []
    actual = {"iid": 1, "project_id": 2, "title": "Old", "description": "Existing body"}

    def api(**kwargs):
        if kwargs["method"] == "PUT":
            writes.append(kwargs["payload"])
            actual.update(kwargs["payload"])
        return actual.copy()

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
            "--title",
            "New",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert writes == [{"title": "New"}]
    assert json.loads(result.stdout)["description"] == "Existing body"


@pytest.mark.parametrize("read_error", [True, False])
def test_mr_verification_failure_preserves_link(monkeypatch, tmp_path, read_error):
    response = {
        "project_id": 2,
        "iid": 1,
        "web_url": "https://gitlab.example/p/-/merge_requests/1",
    }

    def api(**kwargs):
        if read_error:
            raise RuntimeError("read failed")
        return {"description": "Unexpected"}

    monkeypatch.setattr(gitlab_cli, "run_glab_api", api)
    with pytest.raises(
        RuntimeError, match="MR 已写入，请勿重复创建：https://gitlab.example"
    ):
        gitlab_cli.verify_mr(
            response,
            payload={"description": "Expected"},
            cwd=tmp_path,
            hostname="gitlab.example",
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
