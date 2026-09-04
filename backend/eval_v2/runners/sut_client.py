"""SUT (System Under Test) HTTP client.

Handles authentication, meeting creation, polling, audit fetching, and error classification.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from eval_v2.models.enums import FailureClass


class SUTError(Exception):
    """SUT 调用错误基类。"""

    def __init__(self, message: str, failure_class: FailureClass, http_status: int | None = None):
        super().__init__(message)
        self.failure_class = failure_class
        self.http_status = http_status


class SUTClient:
    """HTTP 客户端封装，用于与 Conclave SUT 交互。"""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        auth_token: str | None = None,
        dev_token: str | None = None,
        admin_username: str = "admin",
        admin_password: str = "admin",  # noqa: S107 本地 dev SUT 兜底值，可被 eval 配置 target.admin_password 覆盖
        timeout: float = 30.0,
        poll_interval: float = 3.0,
        max_poll_attempts: int = 200,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.dev_token = dev_token
        self.admin_username = admin_username
        self.admin_password = admin_password
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_poll_attempts = max_poll_attempts
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> SUTClient:
        self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("SUTClient must be used as async context manager")
        return self._client

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        elif self.dev_token:
            headers["x-dev-token"] = self.dev_token
        return headers

    def _classify_http_error(self, status_code: int, detail: str) -> FailureClass:
        """根据 HTTP 状态码分类错误。"""
        if status_code in (401, 403):
            return FailureClass.INFRASTRUCTURE
        if status_code == 402:
            # Payment Required - 通常是 Embedding/外部服务额度耗尽
            return FailureClass.INFRASTRUCTURE
        if status_code >= 500:
            return FailureClass.INFRASTRUCTURE
        if status_code == 404:
            return FailureClass.TEST_BUG
        if status_code in (400, 409, 422):
            # 400/409/422 可能是测试用例配置问题
            return FailureClass.TEST_BUG
        return FailureClass.INFRASTRUCTURE

    async def health_check(self) -> bool:
        """检查 SUT 服务是否可达。"""
        client = self._get_client()
        try:
            resp = await client.get(f"{self.base_url}/meetings", headers=self._headers())
            return resp.status_code < 500
        except (httpx.ConnectError, httpx.TimeoutException, ConnectionError):
            return False

    async def login(self) -> str | None:
        """登录获取 JWT token。优先使用环境变量中的 dev_token。"""
        # 1. 已有 token 直接返回
        if self.auth_token:
            return self.auth_token
        if self.dev_token:
            return None  # dev_token 通过 header 传递，不需要 login

        # 2. 尝试从环境变量获取 dev_token
        env_dev_token = os.environ.get("CONCLAVE_DEV_TOKEN", "")
        if env_dev_token:
            self.dev_token = env_dev_token
            return None

        # 3. 如果配置了用户名密码，尝试登录
        if self.admin_username and self.admin_password:
            client = self._get_client()
            try:
                resp = await client.post(
                    f"{self.base_url}/auth/login",
                    json={"username": self.admin_username, "password": self.admin_password},
                    timeout=15.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self.auth_token = data.get("access_token")
                    return self.auth_token
                else:
                    raise SUTError(
                        f"Login failed: HTTP {resp.status_code}: {resp.text[:200]}",
                        FailureClass.INFRASTRUCTURE,
                        resp.status_code,
                    )
            except httpx.TimeoutException as e:
                raise SUTError(
                    f"Login timeout: {e}",
                    FailureClass.INFRASTRUCTURE,
                ) from e
            except httpx.ConnectError as e:
                raise SUTError(
                    f"Cannot connect to SUT at {self.base_url}: {e}",
                    FailureClass.INFRASTRUCTURE,
                ) from e

        return None

    async def create_meeting(
        self,
        topic: str,
        deliverable_type: str = "prd_openapi",
        flow_plan: str = "standard",
        workflow_template: str = "standard",
        debate_depth: str = "standard",
        dynamic_routing: bool = False,
    ) -> str:
        """创建会议，返回 meeting_id。"""
        client = self._get_client()
        payload: dict[str, Any] = {
            "topic": topic,
            "deliverable_type": deliverable_type,
            "flow_plan": flow_plan,
            "debate_depth": debate_depth,
        }
        # workflow_template 和 dynamic_routing 可能不是所有版本都支持
        if workflow_template != "standard":
            payload["workflow_template"] = workflow_template
        if dynamic_routing:
            payload["dynamic_routing"] = True

        try:
            resp = await client.post(
                f"{self.base_url}/meetings",
                json=payload,
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                detail = resp.text[:300]
                fc = self._classify_http_error(resp.status_code, detail)
                raise SUTError(
                    f"Create meeting failed: HTTP {resp.status_code}: {detail}",
                    fc,
                    resp.status_code,
                )
            data = resp.json()
            meeting_id = data.get("meeting_id")
            if not meeting_id:
                raise SUTError(
                    f"Create meeting returned no meeting_id: {data}",
                    FailureClass.TEST_BUG,
                )
            return meeting_id
        except httpx.TimeoutException as e:
            raise SUTError(
                f"Create meeting timeout: {e}",
                FailureClass.INFRASTRUCTURE,
            ) from e
        except httpx.ConnectError as e:
            raise SUTError(
                f"Cannot connect to SUT: {e}",
                FailureClass.INFRASTRUCTURE,
            ) from e

    async def start_meeting(self, meeting_id: str) -> dict[str, Any]:
        """启动会议。"""
        client = self._get_client()
        try:
            resp = await client.post(
                f"{self.base_url}/meetings/{meeting_id}/run",
                headers=self._headers(),
            )
            # 202 = started, 200 = already done
            if resp.status_code not in (200, 202):
                detail = resp.text[:300]
                fc = self._classify_http_error(resp.status_code, detail)
                raise SUTError(
                    f"Start meeting failed: HTTP {resp.status_code}: {detail}",
                    fc,
                    resp.status_code,
                )
            return resp.json()
        except httpx.TimeoutException as e:
            raise SUTError(
                f"Start meeting timeout: {e}",
                FailureClass.INFRASTRUCTURE,
            ) from e

    async def poll_progress(self, meeting_id: str, timeout: float | None = None) -> dict[str, Any]:
        """轮询会议进度直到终态。返回最后一次 progress 响应。"""
        client = self._get_client()
        timeout = timeout or (self.max_poll_attempts * self.poll_interval)
        deadline = time.monotonic() + timeout
        terminal_states = {"done", "failed", "aborted"}
        last_progress: dict[str, Any] = {}

        attempts = 0
        while time.monotonic() < deadline and attempts < self.max_poll_attempts:
            attempts += 1
            try:
                resp = await client.get(
                    f"{self.base_url}/meetings/{meeting_id}/progress",
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    progress = resp.json()
                    last_progress = progress
                    status = progress.get("status", "")
                    if status in terminal_states:
                        return progress
                elif resp.status_code == 404:
                    raise SUTError(
                        f"Meeting {meeting_id} not found during polling",
                        FailureClass.TEST_BUG,
                        404,
                    )
                elif resp.status_code >= 500:
                    # 5xx 可能是临时错误，继续轮询
                    pass
            except httpx.TimeoutException:
                pass
            except httpx.ConnectError as e:
                raise SUTError(
                    f"Connection lost during polling: {e}",
                    FailureClass.INFRASTRUCTURE,
                ) from e

            await asyncio.sleep(self.poll_interval)

        # 超时
        raise SUTError(
            f"Meeting {meeting_id} did not reach terminal state within {timeout}s. "
            f"Last status: {last_progress.get('status', 'unknown')}, "
            f"stage: {last_progress.get('stage', 'unknown')}",
            FailureClass.INFRASTRUCTURE,
        )

    async def fetch_meeting(self, meeting_id: str) -> dict[str, Any]:
        """获取会议完整详情。"""
        client = self._get_client()
        try:
            resp = await client.get(
                f"{self.base_url}/meetings/{meeting_id}",
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                return {}
            return resp.json()
        except (httpx.TimeoutException, httpx.ConnectError):
            return {}

    async def fetch_audit(self, meeting_id: str) -> dict[str, Any]:
        """获取完整审计数据。best-effort，失败返回空 dict。"""
        client = self._get_client()
        try:
            resp = await client.get(
                f"{self.base_url}/meetings/{meeting_id}/audit",
                headers=self._headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            return {}
        except (httpx.TimeoutException, httpx.ConnectError):
            return {}

    async def get_prompt_snapshot(self) -> dict[str, Any]:
        """获取 prompt 版本快照（ADR-015 Phase 1）。

        best-effort：旧版 SUT 无该端点或请求失败时返回 {}，不中断评估流程。
        """
        client = self._get_client()
        try:
            resp = await client.get(
                f"{self.base_url}/system/prompts/snapshot",
                headers=self._headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, dict) else {}
            return {}
        except (httpx.TimeoutException, httpx.ConnectError):
            return {}

    async def upload_document(self, meeting_id: str, filename: str, content: str) -> bool:
        """上传参考文档（best-effort）。"""
        client = self._get_client()
        try:
            files = {"file": (filename, content.encode("utf-8"), "text/plain")}
            # 移除 Content-Type 让 httpx 自动设置 multipart boundary
            headers = {}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"
            elif self.dev_token:
                headers["x-dev-token"] = self.dev_token
            resp = await client.post(
                f"{self.base_url}/meetings/{meeting_id}/documents",
                files=files,
                headers=headers,
            )
            return resp.status_code < 400
        except (httpx.TimeoutException, httpx.ConnectError):
            return False
