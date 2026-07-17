"""Jira Server/Data Center REST API v2 client."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx2
from pydantic import BaseModel, Field, field_validator, model_validator


class JiraApiError(RuntimeError):
    """Raised when Jira returns an unsuccessful response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class JiraConfig(BaseModel):
    """Validated connection settings used by the HTTP client."""

    server: str = "https://jira.shopee.io"
    token: str = Field(min_length=1)
    username: str | None = None
    auth_type: str = "auto"
    timeout_seconds: float = Field(default=30.0, gt=0)
    verify_ssl: bool = True
    dangerously_allow_http: bool = False

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"auto", "bearer", "basic"}:
            raise ValueError("auth_type must be auto, bearer, or basic")
        return normalized

    @model_validator(mode="after")
    def validate_server_transport(self) -> JiraConfig:
        parsed = urlsplit(self.server)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise ValueError("server must use http or https")
        if not parsed.hostname:
            raise ValueError("server must include a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("server must not include userinfo")
        if parsed.query or parsed.fragment:
            raise ValueError("server must not include a query or fragment")
        if scheme == "http" and not self.dangerously_allow_http:
            raise ValueError(
                "HTTP requires dangerously_allow_http=true because credentials "
                "would be sent without transport encryption"
            )
        return self


class JiraApiClient:
    """Thin, predictable wrapper around Jira REST endpoints."""

    def __init__(
        self,
        config: JiraConfig,
        *,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self.client = httpx2.Client(
            base_url=config.server.rstrip("/") + "/",
            timeout=config.timeout_seconds,
            verify=config.verify_ssl,
            headers=self._build_headers(config),
            transport=transport,
        )

    @staticmethod
    def _build_headers(config: JiraConfig) -> dict[str, str]:
        auth_type = config.auth_type
        if auth_type == "auto":
            auth_type = "basic" if config.username else "bearer"

        headers = {"Accept": "application/json"}
        if auth_type == "basic":
            if not config.username:
                raise ValueError("username is required for basic authentication")
            value = base64.b64encode(
                f"{config.username}:{config.token}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {value}"
        else:
            headers["Authorization"] = f"Bearer {config.token}"
        return headers

    @staticmethod
    def _payload(response: httpx2.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    @staticmethod
    def _segment(value: str, name: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError(f"{name} is not a valid URL path segment")
        return value

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: Any | None = None,
        files: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        try:
            response = self.client.request(
                method,
                path,
                params=params,
                json=json_data,
                files=files,
                headers=headers,
            )
        except httpx2.RequestError as exc:
            raise JiraApiError(
                f"{method.upper()} {path} request failed: {type(exc).__name__}"
            ) from None
        payload = self._payload(response)
        if not response.is_success:
            raise JiraApiError(
                f"{method.upper()} {path} failed with status {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )
        return payload

    def raw_get(self, path: str, params: dict[str, str] | None = None) -> Any:
        normalized = path.lstrip("/")
        if (
            "://" in normalized
            or not normalized.startswith("rest/")
            or ".." in normalized.split("/")
            or any(character in normalized for character in "%?#\\")
            or any(
                ord(character) < 32 or ord(character) == 127 for character in normalized
            )
        ):
            raise ValueError("api get path must be a relative path starting with rest/")
        return self.request("GET", normalized, params=params)

    def server_info(self) -> dict[str, Any]:
        return self.request("GET", "rest/api/2/serverInfo")

    def myself(self) -> dict[str, Any]:
        return self.request("GET", "rest/api/2/myself")

    def search_users(self, query: str, *, max_results: int = 50) -> dict[str, Any]:
        return self.request(
            "GET",
            "rest/api/2/user/picker",
            params={"query": query, "maxResults": max_results},
        )

    def list_projects(self) -> list[dict[str, Any]]:
        return self.request("GET", "rest/api/2/project")

    def get_project(self, project_key: str) -> dict[str, Any]:
        project_key = self._segment(project_key, "project_key")
        return self.request("GET", f"rest/api/2/project/{project_key}")

    def list_versions(self, project_key: str) -> list[dict[str, Any]]:
        project_key = self._segment(project_key, "project_key")
        return self.request("GET", f"rest/api/2/project/{project_key}/versions")

    def list_components(self, project_key: str) -> list[dict[str, Any]]:
        project_key = self._segment(project_key, "project_key")
        return self.request("GET", f"rest/api/2/project/{project_key}/components")

    def list_fields(self) -> list[dict[str, Any]]:
        return self.request("GET", "rest/api/2/field")

    def list_issue_types(self) -> list[dict[str, Any]]:
        return self.request("GET", "rest/api/2/issuetype")

    def create_meta(
        self,
        *,
        project_keys: list[str] | None = None,
        issue_type_names: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"expand": "projects.issuetypes.fields"}
        if project_keys:
            params["projectKeys"] = project_keys
        if issue_type_names:
            params["issuetypeNames"] = issue_type_names
        return self.request("GET", "rest/api/2/issue/createmeta", params=params)

    def search_issues(
        self,
        jql: str,
        *,
        start_at: int = 0,
        max_results: int = 50,
        fields: list[str] | None = None,
        expand: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
        }
        if fields:
            params["fields"] = ",".join(fields)
        if expand:
            params["expand"] = ",".join(expand)
        return self.request("GET", "rest/api/2/search", params=params)

    def get_issue(
        self,
        issue_key: str,
        *,
        fields: list[str] | None = None,
        expand: list[str] | None = None,
    ) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = ",".join(fields)
        if expand:
            params["expand"] = ",".join(expand)
        return self.request(
            "GET", f"rest/api/2/issue/{issue_key}", params=params or None
        )

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "rest/api/2/issue", json_data={"fields": fields})

    def edit_issue(self, issue_key: str, fields: dict[str, Any]) -> None:
        issue_key = self._segment(issue_key, "issue_key")
        self.request(
            "PUT", f"rest/api/2/issue/{issue_key}", json_data={"fields": fields}
        )

    def assign_issue(self, issue_key: str, username: str) -> None:
        issue_key = self._segment(issue_key, "issue_key")
        self.request(
            "PUT",
            f"rest/api/2/issue/{issue_key}/assignee",
            json_data={"name": username},
        )

    def delete_issue(self, issue_key: str, *, delete_subtasks: bool = False) -> None:
        issue_key = self._segment(issue_key, "issue_key")
        self.request(
            "DELETE",
            f"rest/api/2/issue/{issue_key}",
            params={"deleteSubtasks": str(delete_subtasks).lower()},
        )

    def list_transitions(self, issue_key: str) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        return self.request(
            "GET",
            f"rest/api/2/issue/{issue_key}/transitions",
            params={"expand": "transitions.fields"},
        )

    def transition_issue(
        self,
        issue_key: str,
        transition: str,
        *,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        transitions = self.list_transitions(issue_key).get("transitions", [])
        matching = [
            item
            for item in transitions
            if str(item.get("id")) == transition
            or str(item.get("name", "")).casefold() == transition.casefold()
        ]
        if len(matching) != 1:
            available = ", ".join(
                f"{item.get('name')} ({item.get('id')})" for item in transitions
            )
            reason = "is ambiguous" if matching else "was not found"
            raise JiraApiError(
                f"Transition {transition!r} {reason}. Available: {available or 'none'}"
            )
        selected = matching[0]
        provided_fields = fields or {}
        required_fields = {
            key
            for key, metadata in (selected.get("fields") or {}).items()
            if metadata.get("required") and not metadata.get("hasDefaultValue")
        }
        missing_fields = sorted(required_fields - provided_fields.keys())
        if missing_fields:
            raise JiraApiError(
                "Transition requires fields: " + ", ".join(missing_fields)
            )
        payload: dict[str, Any] = {"transition": {"id": str(selected["id"])}}
        if provided_fields:
            payload["fields"] = provided_fields
        self.request(
            "POST",
            f"rest/api/2/issue/{issue_key}/transitions",
            json_data=payload,
        )
        return selected

    def list_comments(
        self, issue_key: str, *, start_at: int = 0, max_results: int = 100
    ) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        return self.request(
            "GET",
            f"rest/api/2/issue/{issue_key}/comment",
            params={"startAt": start_at, "maxResults": max_results},
        )

    def add_comment(self, issue_key: str, body: str) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        return self.request(
            "POST",
            f"rest/api/2/issue/{issue_key}/comment",
            json_data={"body": body},
        )

    def edit_comment(
        self, issue_key: str, comment_id: str, body: str
    ) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        comment_id = self._segment(comment_id, "comment_id")
        return self.request(
            "PUT",
            f"rest/api/2/issue/{issue_key}/comment/{comment_id}",
            json_data={"body": body},
        )

    def delete_comment(self, issue_key: str, comment_id: str) -> None:
        issue_key = self._segment(issue_key, "issue_key")
        comment_id = self._segment(comment_id, "comment_id")
        self.request("DELETE", f"rest/api/2/issue/{issue_key}/comment/{comment_id}")

    def list_attachments(self, issue_key: str) -> list[dict[str, Any]]:
        issue = self.get_issue(issue_key, fields=["attachment"])
        return issue.get("fields", {}).get("attachment", [])

    def add_attachment(self, issue_key: str, file_path: Path) -> Any:
        issue_key = self._segment(issue_key, "issue_key")
        with file_path.open("rb") as file_handle:
            return self.request(
                "POST",
                f"rest/api/2/issue/{issue_key}/attachments",
                files={"file": (file_path.name, file_handle)},
                headers={"X-Atlassian-Token": "no-check"},
            )

    def delete_attachment(self, attachment_id: str) -> None:
        attachment_id = self._segment(attachment_id, "attachment_id")
        self.request("DELETE", f"rest/api/2/attachment/{attachment_id}")

    def get_attachment(self, attachment_id: str) -> dict[str, Any]:
        attachment_id = self._segment(attachment_id, "attachment_id")
        return self.request("GET", f"rest/api/2/attachment/{attachment_id}")

    def list_link_types(self) -> dict[str, Any]:
        return self.request("GET", "rest/api/2/issueLinkType")

    def create_issue_link(
        self,
        inward_issue: str,
        outward_issue: str,
        link_type: str,
        *,
        comment: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "type": {"name": link_type},
            "inwardIssue": {"key": inward_issue},
            "outwardIssue": {"key": outward_issue},
        }
        if comment is not None:
            payload["comment"] = {"body": comment}
        self.request("POST", "rest/api/2/issueLink", json_data=payload)

    def get_issue_link(self, link_id: str) -> dict[str, Any]:
        link_id = self._segment(link_id, "link_id")
        return self.request("GET", f"rest/api/2/issueLink/{link_id}")

    def delete_issue_link(self, link_id: str) -> None:
        link_id = self._segment(link_id, "link_id")
        self.request("DELETE", f"rest/api/2/issueLink/{link_id}")

    def list_remote_links(self, issue_key: str) -> list[dict[str, Any]]:
        issue_key = self._segment(issue_key, "issue_key")
        return self.request("GET", f"rest/api/2/issue/{issue_key}/remotelink")

    def _write_remote_link(
        self,
        issue_key: str,
        *,
        url: str,
        title: str,
        global_id: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        object_value: dict[str, Any] = {"url": url, "title": title}
        if summary is not None:
            object_value["summary"] = summary
        payload: dict[str, Any] = {"object": object_value}
        if global_id is not None:
            payload["globalId"] = global_id
        return self.request(
            "POST", f"rest/api/2/issue/{issue_key}/remotelink", json_data=payload
        )

    def add_remote_link(
        self,
        issue_key: str,
        *,
        url: str,
        title: str,
        summary: str | None = None,
    ) -> dict[str, Any]:
        return self._write_remote_link(issue_key, url=url, title=title, summary=summary)

    def upsert_remote_link(
        self,
        issue_key: str,
        *,
        url: str,
        title: str,
        global_id: str,
        summary: str | None = None,
    ) -> dict[str, Any]:
        matches = [
            link
            for link in self.list_remote_links(issue_key)
            if link.get("globalId") == global_id
        ]
        if len(matches) > 1:
            raise JiraApiError(
                f"Multiple remote links use globalId {global_id!r}; refusing to replace"
            )
        if not matches:
            return self._write_remote_link(
                issue_key,
                url=url,
                title=title,
                global_id=global_id,
                summary=summary,
            )
        existing = matches[0]
        payload = {
            key: existing[key]
            for key in ("application", "relationship", "object")
            if key in existing
        }
        payload["globalId"] = global_id
        object_value = dict(payload.get("object") or {})
        object_value.update({"url": url, "title": title})
        if summary is not None:
            object_value["summary"] = summary
        payload["object"] = object_value
        issue_key = self._segment(issue_key, "issue_key")
        return self.request(
            "POST",
            f"rest/api/2/issue/{issue_key}/remotelink",
            json_data=payload,
        )

    def delete_remote_link(self, issue_key: str, link_id: str) -> None:
        issue_key = self._segment(issue_key, "issue_key")
        link_id = self._segment(link_id, "link_id")
        self.request("DELETE", f"rest/api/2/issue/{issue_key}/remotelink/{link_id}")

    def get_watchers(self, issue_key: str) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        return self.request("GET", f"rest/api/2/issue/{issue_key}/watchers")

    def add_watcher(self, issue_key: str, username: str) -> None:
        issue_key = self._segment(issue_key, "issue_key")
        self.request(
            "POST",
            f"rest/api/2/issue/{issue_key}/watchers",
            json_data=username,
        )

    def remove_watcher(self, issue_key: str, username: str) -> None:
        issue_key = self._segment(issue_key, "issue_key")
        self.request(
            "DELETE",
            f"rest/api/2/issue/{issue_key}/watchers",
            params={"username": username},
        )

    def get_votes(self, issue_key: str) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        return self.request("GET", f"rest/api/2/issue/{issue_key}/votes")

    def add_vote(self, issue_key: str) -> None:
        issue_key = self._segment(issue_key, "issue_key")
        self.request("POST", f"rest/api/2/issue/{issue_key}/votes")

    def remove_vote(self, issue_key: str) -> None:
        issue_key = self._segment(issue_key, "issue_key")
        self.request("DELETE", f"rest/api/2/issue/{issue_key}/votes")

    def list_worklogs(self, issue_key: str) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        return self.request("GET", f"rest/api/2/issue/{issue_key}/worklog")

    @staticmethod
    def _worklog_estimate_params(
        adjust_estimate: str,
        *,
        new_estimate: str | None = None,
        manual_value: str | None = None,
        manual_parameter: str | None = None,
    ) -> dict[str, str]:
        allowed = {"auto", "leave", "new"}
        if manual_parameter is not None:
            allowed.add("manual")
        elif adjust_estimate == "manual":
            raise ValueError(
                "adjust_estimate=manual is not supported for this operation"
            )
        if adjust_estimate not in allowed:
            raise ValueError(
                f"adjust_estimate must be one of: {', '.join(sorted(allowed))}"
            )
        if adjust_estimate == "new":
            if not new_estimate:
                raise ValueError("new_estimate is required when adjust_estimate=new")
            if manual_value is not None:
                raise ValueError(
                    f"{manual_parameter} is only valid when adjust_estimate=manual"
                )
        elif new_estimate is not None:
            raise ValueError("new_estimate is only valid when adjust_estimate=new")
        if adjust_estimate == "manual":
            if not manual_value:
                raise ValueError(
                    f"{manual_parameter} is required when adjust_estimate=manual"
                )
        elif manual_value is not None:
            raise ValueError(
                f"{manual_parameter} is only valid when adjust_estimate=manual"
            )
        params = {"adjustEstimate": adjust_estimate}
        if new_estimate is not None:
            params["newEstimate"] = new_estimate
        if manual_value is not None and manual_parameter is not None:
            params[manual_parameter] = manual_value
        return params

    def add_worklog(
        self,
        issue_key: str,
        *,
        time_spent: str,
        comment: str | None = None,
        started: str | None = None,
        adjust_estimate: str = "leave",
        new_estimate: str | None = None,
        reduce_by: str | None = None,
    ) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        payload: dict[str, Any] = {"timeSpent": time_spent}
        if comment is not None:
            payload["comment"] = comment
        if started is not None:
            payload["started"] = started
        return self.request(
            "POST",
            f"rest/api/2/issue/{issue_key}/worklog",
            params=self._worklog_estimate_params(
                adjust_estimate,
                new_estimate=new_estimate,
                manual_value=reduce_by,
                manual_parameter="reduceBy",
            ),
            json_data=payload,
        )

    def edit_worklog(
        self,
        issue_key: str,
        worklog_id: str,
        *,
        time_spent: str | None = None,
        comment: str | None = None,
        started: str | None = None,
        adjust_estimate: str = "leave",
        new_estimate: str | None = None,
    ) -> dict[str, Any]:
        issue_key = self._segment(issue_key, "issue_key")
        worklog_id = self._segment(worklog_id, "worklog_id")
        payload: dict[str, Any] = {}
        if time_spent is not None:
            payload["timeSpent"] = time_spent
        if comment is not None:
            payload["comment"] = comment
        if started is not None:
            payload["started"] = started
        if not payload:
            raise ValueError("At least one worklog change is required")
        return self.request(
            "PUT",
            f"rest/api/2/issue/{issue_key}/worklog/{worklog_id}",
            params=self._worklog_estimate_params(
                adjust_estimate, new_estimate=new_estimate
            ),
            json_data=payload,
        )

    def delete_worklog(
        self,
        issue_key: str,
        worklog_id: str,
        *,
        adjust_estimate: str = "leave",
        new_estimate: str | None = None,
        increase_by: str | None = None,
    ) -> None:
        issue_key = self._segment(issue_key, "issue_key")
        worklog_id = self._segment(worklog_id, "worklog_id")
        self.request(
            "DELETE",
            f"rest/api/2/issue/{issue_key}/worklog/{worklog_id}",
            params=self._worklog_estimate_params(
                adjust_estimate,
                new_estimate=new_estimate,
                manual_value=increase_by,
                manual_parameter="increaseBy",
            ),
        )

    def list_boards(
        self,
        *,
        project_key: str | None = None,
        start_at: int = 0,
        max_results: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"startAt": start_at, "maxResults": max_results}
        if project_key:
            params["projectKeyOrId"] = project_key
        return self.request("GET", "rest/agile/1.0/board", params=params)

    def list_sprints(
        self,
        board_id: str,
        *,
        state: str | None = None,
        start_at: int = 0,
        max_results: int = 50,
    ) -> dict[str, Any]:
        board_id = self._segment(board_id, "board_id")
        params: dict[str, Any] = {"startAt": start_at, "maxResults": max_results}
        if state:
            params["state"] = state
        return self.request(
            "GET", f"rest/agile/1.0/board/{board_id}/sprint", params=params
        )
