from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "gitlab_cli.py"
SPEC = importlib.util.spec_from_file_location("gitlab_cli", SCRIPT_PATH)
assert SPEC is not None
gitlab_cli = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gitlab_cli)


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
