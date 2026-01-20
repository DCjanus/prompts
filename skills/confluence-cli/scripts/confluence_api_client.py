#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "atlassian-python-api>=4.0.7",
#     "pydantic>=2.12.5",
# ]
# ///
"""Confluence API 客户端封装。"""

from __future__ import annotations

from typing import Any

from atlassian import Confluence
from pydantic import BaseModel, Field

DEFAULT_TIMEOUT_SECONDS = 30.0


class ConfluenceApiError(RuntimeError):
    """Confluence API 错误。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """初始化 API 错误。"""
        super().__init__(message)
        self.status_code = status_code


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
    """Confluence API 客户端封装。"""

    def __init__(self, config: ConfluenceConfig) -> None:
        """初始化 Confluence API 客户端。"""
        self.config = config
        kwargs: dict[str, Any] = {
            "url": config.base_url,
            "timeout": config.timeout_seconds,
            "verify_ssl": config.verify_ssl,
        }
        if config.cloud is not None:
            kwargs["cloud"] = config.cloud
        if config.username:
            kwargs["username"] = config.username
            kwargs["password"] = config.token
        else:
            kwargs["token"] = config.token
        self.client = Confluence(**kwargs)

    def list_spaces(self, start: int = 0, limit: int = 25, expand: str | None = None) -> Any:
        """列出空间列表。"""
        return self.client.get_all_spaces(start=start, limit=limit, expand=expand)

    def get_space(self, space_key: str, expand: str | None = None) -> Any:
        """获取空间详情。"""
        return self.client.get_space(space_key, expand=expand)

    def get_page(self, page_id: str, expand: str | None = None) -> Any:
        """按页面 ID 获取页面。"""
        return self.client.get_page_by_id(page_id, expand=expand)

    def get_page_by_title(
        self,
        space_key: str,
        title: str,
        expand: str | None = None,
    ) -> Any:
        """按标题获取页面。"""
        return self.client.get_page_by_title(space_key, title, expand=expand)

    def get_page_children(
        self,
        page_id: str,
        start: int = 0,
        limit: int = 25,
        expand: str | None = None,
    ) -> Any:
        """获取子页面列表。"""
        return self.client.get_page_child_by_type(
            page_id,
            type="page",
            start=start,
            limit=limit,
            expand=expand,
        )

    def get_page_attachments(
        self,
        page_id: str,
        start: int = 0,
        limit: int = 25,
        expand: str | None = None,
    ) -> Any:
        """获取页面附件列表。"""
        params: dict[str, Any] = {"start": start, "limit": limit}
        if expand:
            params["expand"] = expand
        return self.client.get(
            f"rest/api/content/{page_id}/child/attachment",
            params=params,
        )

    def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        parent_id: str | None = None,
        representation: str = "storage",
    ) -> Any:
        """创建页面。"""
        return self.client.create_page(
            space=space_key,
            title=title,
            body=body,
            parent_id=parent_id,
            representation=representation,
        )

    def update_page(
        self,
        page_id: str,
        title: str,
        body: str,
        parent_id: str | None = None,
        representation: str = "storage",
    ) -> Any:
        """更新页面。"""
        return self.client.update_page(
            page_id=page_id,
            title=title,
            body=body,
            parent_id=parent_id,
            representation=representation,
        )

    def attach_file(
        self,
        page_id: str,
        file_path: str,
        title: str | None = None,
        comment: str | None = None,
    ) -> Any:
        """上传附件到页面。"""
        return self.client.attach_file(
            filename=file_path,
            page_id=page_id,
            title=title,
            comment=comment,
        )

    def search_cql(
        self,
        cql: str,
        start: int = 0,
        limit: int = 25,
        expand: str | None = None,
    ) -> Any:
        """执行 CQL 搜索。"""
        return self.client.cql(cql, start=start, limit=limit, expand=expand)
