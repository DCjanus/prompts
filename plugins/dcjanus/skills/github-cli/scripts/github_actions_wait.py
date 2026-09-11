#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

"""Low-noise, read-only waiting for GitHub Actions runs, jobs, and PR checks."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

API_VERSION = "2022-11-28"
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_CANCELLED = 3
EXIT_TIMEOUT = 4
EXIT_INTERRUPTED = 5
EXIT_API_ERROR = 6
TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}
SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}
FAILURE_CONCLUSIONS = {
    "error",
    "failure",
    "timed_out",
    "action_required",
    "startup_failure",
    "stale",
}
CANCELLED_CONCLUSIONS = {"cancelled"}


class WaitError(RuntimeError):
    """Base class for stable, user-facing failures."""


class ApiError(WaitError):
    """A non-retryable GitHub API failure."""


class RetryableApiError(ApiError):
    """A temporary GitHub API failure that may be retried."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SignalInterrupt(KeyboardInterrupt):
    """Raised when a termination signal requests a clean stop."""


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str
    hostname: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class Target:
    kind: str
    identifier: int
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class RawResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class UrlTransport:
    """Minimal injectable HTTP transport."""

    def request(self, url: str, headers: dict[str, str]) -> RawResponse:
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=30) as response:
                return RawResponse(
                    response.status, dict(response.headers.items()), response.read()
                )
        except HTTPError as error:
            return RawResponse(error.code, dict(error.headers.items()), error.read())
        except (URLError, TimeoutError, OSError) as error:
            raise RetryableApiError("temporary network error") from error


class FakeableTransport:
    """Deterministic transport used by tests and embedders."""

    def __init__(self, responses: Iterable[RawResponse]) -> None:
        self.responses = iter(responses)
        self.requests: list[tuple[str, dict[str, str]]] = []

    def request(self, url: str, headers: dict[str, str]) -> RawResponse:
        self.requests.append((url, dict(headers)))
        return next(self.responses)


class GitHubApi:
    """Read-only REST client with per-URL conditional request caching."""

    def __init__(
        self,
        repo: RepoRef,
        token: str,
        *,
        transport: Any | None = None,
    ) -> None:
        self.repo = repo
        self.token = token
        self.transport = transport or UrlTransport()
        self.rest_base = (
            "https://api.github.com"
            if repo.hostname == "github.com"
            else f"https://{repo.hostname}/api/v3"
        )
        self.cache: dict[str, tuple[str | None, Any]] = {}

    def get(self, endpoint: str) -> Any:
        url = f"{self.rest_base}/{endpoint.lstrip('/')}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "dcjanus-github-actions-wait",
        }
        cached = self.cache.get(url)
        if cached and cached[0]:
            headers["If-None-Match"] = cached[0]
        response = self.transport.request(url, headers)
        if response.status == 304:
            if cached is None:
                raise RetryableApiError("GitHub API returned 304 without cached data")
            return cached[1]
        if response.status in TRANSIENT_STATUS or is_rate_limited(response):
            raise RetryableApiError(
                f"GitHub API temporarily returned HTTP {response.status}",
                retry_after=parse_retry_after(response.headers),
            )
        if not 200 <= response.status < 300:
            raise ApiError(f"GitHub API returned HTTP {response.status} for {endpoint}")
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiError("GitHub API returned invalid JSON") from error
        etag = header_value(response.headers, "etag")
        self.cache[url] = (etag, payload)
        return payload


def header_value(headers: dict[str, str], name: str) -> str | None:
    return next((value for key, value in headers.items() if key.lower() == name), None)


def parse_retry_after(headers: dict[str, str]) -> float | None:
    value = header_value(headers, "retry-after")
    if value is not None:
        try:
            return max(0.0, float(value))
        except ValueError:
            pass
    reset = header_value(headers, "x-ratelimit-reset")
    if reset is None:
        return None
    try:
        return max(0.0, float(reset) - time.time())
    except ValueError:
        return None


def is_rate_limited(response: RawResponse) -> bool:
    if response.status != 403:
        return False
    return (
        header_value(response.headers, "retry-after") is not None
        or header_value(response.headers, "x-ratelimit-remaining") == "0"
    )


def parse_repo(value: str, hostname: str | None = None) -> RepoRef:
    raw = value.strip()
    selected_host = hostname
    if "://" in raw:
        parsed = urlparse(raw)
        selected_host = selected_host or parsed.hostname
        raw = parsed.path
    raw = raw.removesuffix(".git").strip("/")
    parts = raw.split("/")
    if len(parts) == 3 and hostname is None:
        selected_host, owner, name = parts
    elif len(parts) == 2:
        owner, name = parts
    else:
        raise WaitError("repo must be OWNER/REPO, HOST/OWNER/REPO, or a repository URL")
    if not owner or not name:
        raise WaitError("repository owner and name must not be empty")
    return RepoRef(
        owner, name, selected_host or os.environ.get("GH_HOST") or "github.com"
    )


def resolve_token(hostname: str) -> str:
    if token := os.environ.get("GH_TOKEN", "").strip():
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", hostname],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise WaitError("no GitHub token found and gh is not installed") from error
    if result.returncode != 0 or not result.stdout.strip():
        raise WaitError(f"no GitHub authentication available for {hostname}")
    return result.stdout.strip()


def conclusion_state(status: str | None, conclusion: str | None) -> str:
    if status != "completed" and conclusion is None:
        return "pending"
    if conclusion in SUCCESS_CONCLUSIONS:
        return "success"
    if conclusion in CANCELLED_CONCLUSIONS:
        return "cancelled"
    if conclusion in FAILURE_CONCLUSIONS:
        return "failure"
    return "pending"


def selected_items(
    items: Sequence[dict[str, Any]], names: tuple[str, ...]
) -> list[dict[str, Any]]:
    if not names:
        return list(items)
    return [
        item
        for item in items
        if any(
            fnmatch.fnmatchcase(str(item.get("name", "")), pattern) for pattern in names
        )
    ]


def aggregate_items(
    items: Sequence[dict[str, Any]], *, fail_fast: bool = False
) -> tuple[str, list[dict[str, str]]]:
    normalized = [
        {
            "name": str(item.get("name", "")),
            "state": conclusion_state(item.get("status"), item.get("conclusion")),
        }
        for item in items
    ]
    states = {item["state"] for item in normalized}
    if not normalized:
        return "pending", normalized
    if fail_fast and "failure" in states:
        return "failure", normalized
    if fail_fast and "cancelled" in states:
        return "cancelled", normalized
    if "pending" in states:
        return "pending", normalized
    if "failure" in states:
        return "failure", normalized
    if "cancelled" in states:
        return "cancelled", normalized
    return "success", normalized


def repo_endpoint(api: Any, suffix: str) -> str:
    return f"repos/{api.repo.full_name}/{suffix}"


def collection(api: Any, endpoint: str, key: str) -> list[dict[str, Any]]:
    payload = api.get(endpoint)
    items = list(payload.get(key, []))
    total = int(payload.get("total_count", len(items)))
    page = 2
    while len(items) < total:
        separator = "&" if "?" in endpoint else "?"
        payload = api.get(f"{endpoint}{separator}page={page}")
        page_items = payload.get(key, [])
        if not page_items:
            break
        items.extend(page_items)
        page += 1
    return items


def snapshot(api: Any, target: Target, *, fail_fast: bool) -> dict[str, Any]:
    if target.kind == "run" and not target.names:
        item = api.get(repo_endpoint(api, f"actions/runs/{target.identifier}"))
        status = item.get("status")
        conclusion = item.get("conclusion")
        return {
            "state": conclusion_state(status, conclusion),
            "status": status,
            "conclusion": conclusion,
            "name": item.get("name"),
            "url": item.get("html_url"),
        }
    if target.kind == "job":
        item = api.get(repo_endpoint(api, f"actions/jobs/{target.identifier}"))
        status = item.get("status")
        conclusion = item.get("conclusion")
        return {
            "state": conclusion_state(status, conclusion),
            "status": status,
            "conclusion": conclusion,
            "name": item.get("name"),
            "url": item.get("html_url"),
        }
    if target.kind == "run":
        items = collection(
            api,
            repo_endpoint(api, f"actions/runs/{target.identifier}/jobs?per_page=100"),
            "jobs",
        )
        items = selected_items(items, target.names)
        state, normalized = aggregate_items(items)
        return {
            "state": state,
            "status": "completed" if state != "pending" else "in_progress",
            "items": normalized,
        }
    pull = api.get(repo_endpoint(api, f"pulls/{target.identifier}"))
    sha = pull["head"]["sha"]
    checks = collection(
        api,
        repo_endpoint(api, f"commits/{sha}/check-runs?per_page=100"),
        "check_runs",
    )
    statuses = api.get(repo_endpoint(api, f"commits/{sha}/status"))
    items = list(checks)
    items.extend(
        {
            "name": item.get("context", ""),
            "status": "completed" if item.get("state") != "pending" else "in_progress",
            "conclusion": item.get("state"),
        }
        for item in statuses.get("statuses", [])
    )
    items = selected_items(items, target.names)
    state, normalized = aggregate_items(items, fail_fast=fail_fast)
    return {
        "state": state,
        "status": "completed" if state != "pending" else "in_progress",
        "items": normalized,
        "sha": sha,
    }


class Emitter:
    def __init__(
        self,
        output_format: str,
        stream: TextIO,
        *,
        wall_time: Callable[[], float] = time.time,
    ) -> None:
        self.output_format = output_format
        self.stream = stream
        self.wall_time = wall_time

    def emit(self, event: str, target: Target, **fields: Any) -> None:
        payload = {
            "event": event,
            "time": datetime.fromtimestamp(self.wall_time(), UTC).isoformat(),
            "target": target.kind,
            "id": target.identifier,
            **fields,
        }
        if self.output_format == "ndjson":
            print(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                file=self.stream,
                flush=True,
            )
            return
        detail = fields.get("state") or fields.get("message") or ""
        status = fields.get("status")
        if status and status != detail:
            detail = f"{detail} ({status})"
        print(
            f"[{payload['time']}] {target.kind} {target.identifier}: {event} {detail}".rstrip(),
            file=self.stream,
            flush=True,
        )


def terminal_exit(state: str) -> int | None:
    return {
        "success": EXIT_SUCCESS,
        "failure": EXIT_FAILURE,
        "cancelled": EXIT_CANCELLED,
    }.get(state)


def wait_for_target(
    api: Any,
    target: Target,
    *,
    interval: float,
    timeout: float,
    fail_fast: bool,
    emitter: Emitter,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    started = monotonic()
    previous: str | None = None
    previous_error: str | None = None
    while True:
        if monotonic() - started >= timeout:
            emitter.emit("timeout", target, state="timeout")
            return EXIT_TIMEOUT
        try:
            current = snapshot(api, target, fail_fast=fail_fast)
            signature = json.dumps(current, sort_keys=True, separators=(",", ":"))
            if signature != previous:
                emitter.emit("state", target, **current)
                previous = signature
            previous_error = None
            if (code := terminal_exit(current["state"])) is not None:
                return code
            delay = interval
        except RetryableApiError as error:
            signature = str(error)
            if signature != previous_error:
                emitter.emit(
                    "retry",
                    target,
                    message=signature,
                    retry_after=error.retry_after,
                )
                previous_error = signature
            delay = error.retry_after if error.retry_after is not None else interval
        remaining = timeout - (monotonic() - started)
        sleep(min(delay, max(0.0, remaining)))


def run_guarded(
    operation: Callable[[], int], emitter: Emitter, target: Target | None = None
) -> int:
    selected = target or Target("unknown", 0)
    try:
        return operation()
    except KeyboardInterrupt:
        emitter.emit("interrupted", selected, state="interrupted")
        return EXIT_INTERRUPTED
    except (ApiError, WaitError) as error:
        emitter.emit("error", selected, message=str(error), state="error")
        return EXIT_API_ERROR


def install_signal_handlers() -> None:
    def interrupt(signum: int, frame: Any) -> None:
        del signum, frame
        raise SignalInterrupt

    signal.signal(signal.SIGTERM, interrupt)


def parse_duration(value: str) -> float:
    multipliers = {"s": 1, "m": 60, "h": 3600}
    suffix = value[-1:].lower()
    number = value[:-1] if suffix in multipliers else value
    try:
        seconds = float(number) * multipliers.get(suffix, 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "duration must be seconds or use s, m, h"
        ) from error
    if seconds <= 0:
        raise argparse.ArgumentTypeError("duration must be greater than zero")
    return seconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="OWNER/REPO or HOST/OWNER/REPO")
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("--run", type=int, metavar="ID")
    targets.add_argument("--job", type=int, metavar="ID")
    targets.add_argument("--pr", type=int, metavar="NUMBER")
    parser.add_argument("--job-name", action="append", default=[], metavar="GLOB")
    parser.add_argument("--check", action="append", default=[], metavar="GLOB")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--interval", type=parse_duration, default=30.0)
    parser.add_argument("--timeout", type=parse_duration, default=1800.0)
    parser.add_argument("--format", choices=("human", "ndjson"), default="human")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    install_signal_handlers()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.job_name and args.run is None:
        parser.error("--job-name requires --run")
    if args.check and args.pr is None:
        parser.error("--check requires --pr")
    if args.fail_fast and args.pr is None:
        parser.error("--fail-fast requires --pr")
    repo = parse_repo(args.repo)
    if args.run is not None:
        target = Target("run", args.run, tuple(args.job_name))
    elif args.job is not None:
        target = Target("job", args.job)
    else:
        target = Target("pr", args.pr, tuple(args.check))
    emitter = Emitter(args.format, sys.stdout)

    def operation() -> int:
        api = GitHubApi(repo, resolve_token(repo.hostname))
        return wait_for_target(
            api,
            target,
            interval=args.interval,
            timeout=args.timeout,
            fail_fast=args.fail_fast,
            emitter=emitter,
        )

    return run_guarded(operation, emitter, target)


if __name__ == "__main__":
    raise SystemExit(main())
