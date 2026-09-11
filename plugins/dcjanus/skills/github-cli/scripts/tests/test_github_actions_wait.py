from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "github_actions_wait.py"
SPEC = importlib.util.spec_from_file_location("github_actions_wait", SCRIPT_PATH)
assert SPEC is not None
github_actions_wait = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = github_actions_wait
SPEC.loader.exec_module(github_actions_wait)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeApi:
    def __init__(self, responses: list[object]) -> None:
        self.repo = github_actions_wait.RepoRef("acme", "widgets", "github.com")
        self.responses = iter(responses)
        self.calls: list[str] = []

    def get(self, endpoint: str) -> object:
        self.calls.append(endpoint)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def run_wait(
    responses: list[object],
    *,
    target: github_actions_wait.Target | None = None,
    timeout: float = 30,
    output_format: str = "ndjson",
    fail_fast: bool = False,
) -> tuple[int, list[dict[str, object]], FakeApi]:
    stream = io.StringIO()
    clock = FakeClock()
    api = FakeApi(responses)
    emitter = github_actions_wait.Emitter(output_format, stream, wall_time=lambda: 0)
    code = github_actions_wait.wait_for_target(
        api,
        target or github_actions_wait.Target("run", 123),
        interval=1,
        timeout=timeout,
        fail_fast=fail_fast,
        emitter=emitter,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    return code, events, api


def test_run_queued_to_in_progress_to_success() -> None:
    code, events, _ = run_wait(
        [
            {"id": 123, "status": "queued", "conclusion": None},
            {"id": 123, "status": "in_progress", "conclusion": None},
            {"id": 123, "status": "completed", "conclusion": "success"},
        ]
    )

    assert code == github_actions_wait.EXIT_SUCCESS
    assert [event["state"] for event in events] == [
        "pending",
        "pending",
        "success",
    ]
    assert [event["status"] for event in events] == [
        "queued",
        "in_progress",
        "completed",
    ]


@pytest.mark.parametrize(
    ("conclusion", "expected"),
    [("failure", 1), ("cancelled", 3)],
)
def test_run_terminal_exit_codes(conclusion: str, expected: int) -> None:
    code, events, _ = run_wait(
        [{"id": 123, "status": "completed", "conclusion": conclusion}]
    )

    assert code == expected
    assert events[-1]["state"] == conclusion


def test_timeout_has_stable_exit_code() -> None:
    code, events, _ = run_wait(
        [{"id": 123, "status": "queued", "conclusion": None}] * 4,
        timeout=2,
    )

    assert code == github_actions_wait.EXIT_TIMEOUT
    assert events[-1]["event"] == "timeout"


def test_unchanged_state_is_not_repeated() -> None:
    code, events, _ = run_wait(
        [
            {"id": 123, "status": "queued", "conclusion": None},
            {"id": 123, "status": "queued", "conclusion": None},
            {"id": 123, "status": "completed", "conclusion": "success"},
        ]
    )

    assert code == 0
    assert [event["event"] for event in events] == ["state", "state"]


def test_run_job_name_filter_and_pr_check_filter() -> None:
    jobs = {
        "jobs": [
            {"id": 1, "name": "lint", "status": "completed", "conclusion": "success"},
            {
                "id": 2,
                "name": "test-linux",
                "status": "completed",
                "conclusion": "success",
            },
        ]
    }
    code, events, api = run_wait(
        [jobs], target=github_actions_wait.Target("run", 123, names=("test-*",))
    )
    assert code == 0
    assert events[-1]["items"] == [{"name": "test-linux", "state": "success"}]
    assert api.calls == ["repos/acme/widgets/actions/runs/123/jobs?per_page=100"]

    pull = {"head": {"sha": "abc"}}
    checks = {
        "check_runs": [
            {"id": 3, "name": "lint", "status": "completed", "conclusion": "failure"},
            {
                "id": 4,
                "name": "test-linux",
                "status": "completed",
                "conclusion": "success",
            },
        ]
    }
    statuses = {"statuses": []}
    code, events, _ = run_wait(
        [pull, checks, statuses],
        target=github_actions_wait.Target("pr", 9, names=("test-*",)),
    )
    assert code == 0
    assert events[-1]["items"] == [{"name": "test-linux", "state": "success"}]


def test_pr_fail_fast_stops_on_first_failure() -> None:
    pull = {"head": {"sha": "abc"}}
    checks = {
        "check_runs": [
            {"id": 1, "name": "lint", "status": "completed", "conclusion": "failure"},
            {"id": 2, "name": "test", "status": "in_progress", "conclusion": None},
        ]
    }
    code, events, _ = run_wait(
        [pull, checks, {"statuses": []}],
        target=github_actions_wait.Target("pr", 9),
        fail_fast=True,
    )

    assert code == github_actions_wait.EXIT_FAILURE
    assert events[-1]["state"] == "failure"


def test_temporary_api_error_is_retried_without_duplicate_noise() -> None:
    error = github_actions_wait.RetryableApiError("temporary", retry_after=2)
    code, events, _ = run_wait(
        [
            error,
            github_actions_wait.RetryableApiError("temporary", retry_after=2),
            {"id": 123, "status": "completed", "conclusion": "success"},
        ]
    )

    assert code == 0
    assert [event["event"] for event in events] == ["retry", "state"]
    assert events[0]["retry_after"] == 2


def test_etag_304_reuses_cached_json() -> None:
    transport = github_actions_wait.FakeableTransport(
        [
            github_actions_wait.RawResponse(
                200, {"ETag": '"v1"'}, b'{"status":"queued"}'
            ),
            github_actions_wait.RawResponse(304, {}, b""),
        ]
    )
    api = github_actions_wait.GitHubApi(
        github_actions_wait.RepoRef("acme", "widgets", "github.com"),
        "secret-token",
        transport=transport,
    )

    assert api.get("example") == {"status": "queued"}
    assert api.get("example") == {"status": "queued"}
    assert transport.requests[1][1]["If-None-Match"] == '"v1"'


def test_rate_limit_response_exposes_retry_after_without_body() -> None:
    transport = github_actions_wait.FakeableTransport(
        [
            github_actions_wait.RawResponse(
                429,
                {"Retry-After": "7"},
                b'{"message":"secret response detail"}',
            )
        ]
    )
    api = github_actions_wait.GitHubApi(
        github_actions_wait.RepoRef("acme", "widgets", "github.com"),
        "token",
        transport=transport,
    )

    with pytest.raises(github_actions_wait.RetryableApiError) as error:
        api.get("example")
    assert error.value.retry_after == 7
    assert "secret response detail" not in str(error.value)


def test_primary_rate_limit_403_is_retryable() -> None:
    transport = github_actions_wait.FakeableTransport(
        [
            github_actions_wait.RawResponse(
                403,
                {"X-RateLimit-Remaining": "0", "Retry-After": "11"},
                b"{}",
            )
        ]
    )
    api = github_actions_wait.GitHubApi(
        github_actions_wait.RepoRef("acme", "widgets", "github.com"),
        "token",
        transport=transport,
    )

    with pytest.raises(github_actions_wait.RetryableApiError) as error:
        api.get("example")
    assert error.value.retry_after == 11


def test_token_is_redacted_from_api_errors_and_ndjson() -> None:
    token = "super-secret-token"
    transport = github_actions_wait.FakeableTransport(
        [github_actions_wait.RawResponse(401, {}, token.encode())] * 2
    )
    api = github_actions_wait.GitHubApi(
        github_actions_wait.RepoRef("acme", "widgets", "github.com"),
        token,
        transport=transport,
    )
    with pytest.raises(github_actions_wait.ApiError) as error:
        api.get("example")
    assert token not in str(error.value)

    stream = io.StringIO()
    emitter = github_actions_wait.Emitter("ndjson", stream, wall_time=lambda: 0)
    assert (
        github_actions_wait.run_guarded(lambda: api.get("example"), emitter)
        == github_actions_wait.EXIT_API_ERROR
    )
    assert token not in stream.getvalue()


def test_keyboard_interrupt_returns_interrupted_exit_code() -> None:
    stream = io.StringIO()
    emitter = github_actions_wait.Emitter("ndjson", stream, wall_time=lambda: 0)
    code = github_actions_wait.run_guarded(
        lambda: (_ for _ in ()).throw(KeyboardInterrupt()), emitter
    )
    assert code == github_actions_wait.EXIT_INTERRUPTED
    assert json.loads(stream.getvalue())["event"] == "interrupted"


def test_enterprise_api_base_and_host_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_HOST", "github.example.com")
    repo = github_actions_wait.parse_repo("acme/widgets")
    api = github_actions_wait.GitHubApi(repo, "token", transport=FakeApi([]))

    assert repo.hostname == "github.example.com"
    assert api.rest_base == "https://github.example.com/api/v3"


def test_explicit_repository_url_takes_priority_over_gh_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_HOST", "wrong.example.com")

    repo = github_actions_wait.parse_repo("https://github.example.com/acme/widgets")

    assert repo.hostname == "github.example.com"


def test_gh_token_takes_priority_over_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")

    assert github_actions_wait.resolve_token("github.com") == "gh-token"


def test_github_token_is_used_when_gh_token_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")

    assert github_actions_wait.resolve_token("github.com") == "github-token"
