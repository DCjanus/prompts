"""Confluence REST API 客户端封装。"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

DEFAULT_TIMEOUT_SECONDS = 30.0


class ConfluenceApiError(RuntimeError):
    """Confluence API 错误。"""

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


class ConfluenceConfig(BaseModel):
    """Confluence 连接配置。"""

    base_url: str = Field(description="Confluence 基础地址。")
    token: str = Field(description="API Token 或 PAT。")
    username: str | None = Field(default=None, description="登录用户名或邮箱。")
    timeout_seconds: float = Field(
        default=DEFAULT_TIMEOUT_SECONDS,
        gt=0,
        description="请求超时时间（秒）。",
    )
    cloud: bool | None = Field(default=None, description="是否使用 Cloud 模式。")
    verify_ssl: bool = Field(default=True, description="是否校验证书。")


class ConfluenceApiClient:
    """Confluence REST API 薄封装。"""

    def __init__(self, config: ConfluenceConfig) -> None:
        self.config = config
        self.client = httpx.Client(
            base_url=config.base_url.rstrip("/") + "/",
            timeout=config.timeout_seconds,
            verify=config.verify_ssl,
            headers=self._build_headers(config),
        )

    @staticmethod
    def _build_headers(config: ConfluenceConfig) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if config.username:
            raw = f"{config.username}:{config.token}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('utf-8')}"
        else:
            headers["Authorization"] = f"Bearer {config.token}"
        return headers

    @staticmethod
    def _raise_for_error(response: httpx.Response, context: str) -> None:
        if response.is_success:
            return
        payload: Any
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        raise ConfluenceApiError(
            f"{context} failed with status {response.status_code}",
            status_code=response.status_code,
            payload=payload,
        )

    @staticmethod
    def _encode_body(body: str, representation: str) -> dict[str, Any]:
        return {representation: {"value": body, "representation": representation}}

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self.client.get(path, params=params)
        self._raise_for_error(response, f"GET {path}")
        return response.json()

    def _post(
        self,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        files: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = self.client.post(path, json=json_data, files=files, headers=headers)
        self._raise_for_error(response, f"POST {path}")
        return response.json()

    def _put(
        self,
        path: str,
        *,
        json_data: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = self.client.put(path, json=json_data, params=params)
        self._raise_for_error(response, f"PUT {path}")
        return response.json()

    def list_spaces(self, start: int = 0, limit: int = 25, expand: str | None = None) -> Any:
        params: dict[str, Any] = {"start": start, "limit": limit}
        if expand:
            params["expand"] = expand
        return self._get("rest/api/space", params=params)

    def get_space(self, space_key: str, expand: str | None = None) -> Any:
        params = {"expand": expand} if expand else None
        return self._get(f"rest/api/space/{space_key}", params=params)

    def get_page(self, page_id: str, expand: str | None = None) -> Any:
        params = {"expand": expand} if expand else None
        return self._get(f"rest/api/content/{page_id}", params=params)

    def get_page_by_title(
        self,
        space_key: str,
        title: str,
        expand: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {"spaceKey": space_key, "title": title}
        if expand:
            params["expand"] = expand
        return self._get("rest/api/content", params=params)

    def get_page_children(
        self,
        page_id: str,
        start: int = 0,
        limit: int = 25,
        expand: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {"start": start, "limit": limit}
        if expand:
            params["expand"] = expand
        return self._get(f"rest/api/content/{page_id}/child/page", params=params)

    def get_page_attachments(
        self,
        page_id: str,
        start: int = 0,
        limit: int = 25,
        expand: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {"start": start, "limit": limit}
        if expand:
            params["expand"] = expand
        return self._get(f"rest/api/content/{page_id}/child/attachment", params=params)

    def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        parent_id: str | None = None,
        representation: str = "storage",
    ) -> Any:
        data: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": self._encode_body(body, representation),
        }
        if parent_id:
            data["ancestors"] = [{"type": "page", "id": parent_id}]
        return self._post("rest/api/content", json_data=data)

    def update_page(
        self,
        page_id: str,
        title: str,
        body: str,
        parent_id: str | None = None,
        representation: str = "storage",
        always_update: bool = False,
    ) -> Any:
        current = self.get_page(page_id, expand="version")
        version = current.get("version", {}).get("number")
        if not isinstance(version, int):
            raise ConfluenceApiError(f"Failed to resolve current page version for {page_id}")

        data: dict[str, Any] = {
            "id": page_id,
            "type": "page",
            "title": title,
            "version": {"number": version + 1},
            "body": self._encode_body(body, representation),
        }
        if parent_id:
            data["ancestors"] = [{"type": "page", "id": parent_id}]
        if always_update:
            data["version"]["minorEdit"] = False
        return self._put(f"rest/api/content/{page_id}", json_data=data, params={"status": "current"})

    def attach_file(
        self,
        page_id: str,
        file_path: str,
        title: str | None = None,
        comment: str | None = None,
    ) -> Any:
        path = Path(file_path)
        if not path.exists():
            raise ConfluenceApiError(f"Attachment file not found: {file_path}")
        filename = title or path.name
        existing_attachment_id = self._find_attachment_id(page_id, filename)
        with path.open("rb") as file_obj:
            files = {
                "file": (filename, file_obj, "application/octet-stream"),
                "minorEdit": (None, "true"),
            }
            if comment:
                files["comment"] = (None, comment)
            target_path = (
                f"rest/api/content/{page_id}/child/attachment/{existing_attachment_id}/data"
                if existing_attachment_id
                else f"rest/api/content/{page_id}/child/attachment"
            )
            return self._post(
                target_path,
                files=files,
                headers={"X-Atlassian-Token": "no-check"},
            )

    def search_cql(
        self,
        cql: str,
        start: int = 0,
        limit: int = 25,
        expand: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {"cql": cql, "start": start, "limit": limit}
        if expand:
            params["expand"] = expand
        return self._get("rest/api/search", params=params)

    def _find_attachment_id(self, page_id: str, filename: str) -> str | None:
        payload = self.get_page_attachments(page_id, start=0, limit=200)
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            return None
        for item in results:
            if not isinstance(item, dict):
                continue
            if str(item.get("title", "")) == filename:
                attachment_id = item.get("id")
                if attachment_id is not None:
                    return str(attachment_id)
        return None
