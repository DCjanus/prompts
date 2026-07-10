from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "github_issue.py"
SPEC = importlib.util.spec_from_file_location("github_issue", SCRIPT_PATH)
assert SPEC is not None
github_issue = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = github_issue
SPEC.loader.exec_module(github_issue)


def test_parse_repo_supports_common_forms() -> None:
    assert github_issue.parse_repo("openai/codex").model_dump() == {
        "owner": "openai",
        "name": "codex",
        "hostname": "github.com",
    }
    assert github_issue.parse_repo(
        "https://github.example.com/acme/widgets.git"
    ).model_dump() == {
        "owner": "acme",
        "name": "widgets",
        "hostname": "github.example.com",
    }
    assert github_issue.parse_repo("github.example.com/acme/widgets").model_dump() == {
        "owner": "acme",
        "name": "widgets",
        "hostname": "github.example.com",
    }


def test_parse_yaml_issue_form_preserves_metadata() -> None:
    spec = github_issue.parse_template(
        "bug.yml",
        """
name: Bug report
description: Report a bug
title: "[Bug] "
labels: [bug, triage]
assignees: octocat
projects: [acme/1]
type: Bug
body:
  - type: input
    id: version
    attributes:
      label: Version
    validations:
      required: true
  - type: checkboxes
    id: terms
    attributes:
      label: Terms
      options:
        - label: I searched for duplicates
          required: true
""",
    )

    assert spec.kind == "issue-form"
    assert spec.submit_identifier == "Bug report"
    assert spec.labels == ["bug", "triage"]
    assert spec.assignees == ["octocat"]
    assert spec.projects == ["acme/1"]
    assert spec.issue_type == "Bug"
    assert spec.required_fields == ["Version"]
    assert spec.required_checkboxes == ["I searched for duplicates"]


def test_validate_template_body_enforces_required_answers_and_checkboxes() -> None:
    template = github_issue.TemplateSpec(
        filename="bug.yml",
        kind="issue-form",
        name="Bug report",
        required_fields=["Version"],
        required_checkboxes=["I searched for duplicates"],
        submit_identifier="Bug report",
    )

    with pytest.raises(github_issue.GitHubIssueError, match="missing answers"):
        github_issue.validate_template_body(template, "### Version\n\n_No response_\n")

    github_issue.validate_template_body(
        template,
        "### Version\n\n0.1.0\n\n- [x] I searched for duplicates\n",
    )


def test_parse_markdown_template_uses_frontmatter_name_for_submit() -> None:
    spec = github_issue.parse_template(
        "bug.md",
        """---
name: Bug report
about: Report a bug
title: "[Bug] "
labels: bug, triage
assignees: octocat
---

Describe the bug.
""",
    )

    assert spec.kind == "markdown"
    assert spec.submit_identifier == "Bug report"
    assert spec.labels == ["bug", "triage"]
    assert spec.assignees == ["octocat"]


def test_plain_metadata_requires_triage_permission() -> None:
    with pytest.raises(github_issue.GitHubIssueError, match="cannot set labels"):
        github_issue.ensure_plain_metadata_permission("READ", ["bug"], [])

    github_issue.ensure_plain_metadata_permission("TRIAGE", ["bug"], [])


def test_environment_token_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "from-environment")

    def unexpected_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("gh should not be called")

    monkeypatch.setattr(github_issue.subprocess, "run", unexpected_run)

    assert github_issue.resolve_token("github.com") == "from-environment"


def test_template_creation_passes_issue_template_identifier() -> None:
    class FakeApi:
        variables: dict[str, object] | None = None

        def graphql(
            self, query: str, variables: dict[str, object]
        ) -> dict[str, object]:
            assert "issueTemplate: $issueTemplate" in query
            self.variables = variables
            return {
                "createIssue": {
                    "issue": {"number": 42, "url": "https://example.test/issues/42"}
                }
            }

    api = FakeApi()
    template = github_issue.TemplateSpec(
        filename="bug.yml",
        kind="issue-form",
        name="Bug report",
        submit_identifier="Bug report",
    )

    result = github_issue.create_template_issue(
        api,
        repo_id="R_123",
        title="A bug",
        body="Details",
        template=template,
    )

    assert result["number"] == 42
    assert api.variables == {
        "repositoryId": "R_123",
        "title": "A bug",
        "body": "Details",
        "issueTemplate": "Bug report",
    }


def test_verify_issue_reports_missing_template_metadata() -> None:
    result = github_issue.verify_issue(
        repo=github_issue.RepoRef(owner="acme", name="widgets"),
        template=github_issue.TemplateSpec(
            filename="bug.yml",
            kind="issue-form",
            name="Bug report",
            labels=["bug", "triage"],
            assignees=["octocat"],
            submit_identifier="Bug report",
        ),
        issue={
            "html_url": "https://github.com/acme/widgets/issues/1",
            "labels": [{"name": "bug"}],
            "assignees": [],
        },
        expected_labels=["bug", "triage"],
        expected_assignees=["octocat"],
    )

    assert result.ok is False
    assert result.missing_labels == ["triage"]
    assert result.missing_assignees == ["octocat"]
