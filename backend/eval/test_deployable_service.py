"""可部署服务评估套件 — Conclave 部署就绪性 / 认证 / 会议工作流 / 终态

本套件以黑盒 HTTP 方式评估一个「已部署并运行中」的 Conclave 服务，
界定以下预期内容：

  1. 服务就绪性：后端 /health 返回 ok，前端可访问，API 文档可用
  2. 认证系统：默认凭证 admin/admin123 可登录，JWT 可用，权限正确
  3. 会议核心工作流：创建 / 列表 / 详情 / 进度 / 摘要 / 报告布局 / 控场信号
  4. 辅助端点：角色 / 指标 / 基线 / 偏好 / 验证码
  5. 服务完整性：OpenAPI schema 覆盖核心路径，错误处理正确
  6. 真实会议端到端（opt-in）：六阶段全流程到达 done 终态，产出完整

运行方式：
  # 容器内运行（推荐）
  cd /app && python -m pytest eval/test_deployable_service.py -v --confcutdir=eval

  # 宿主机运行（需服务已启动）
  cd backend && python -m pytest eval/test_deployable_service.py -v --confcutdir=eval

  # 仅基础评估（跳过真实 LLM，适合 CI / 快速验证）
  python -m pytest eval/test_deployable_service.py -v --confcutdir=eval -k "not RealMeeting"

  # 完整评估（含真实 LLM 会议端到端）
  CONCLAVE_EVAL_REAL_LLM=1 python -m pytest eval/test_deployable_service.py -v -s --confcutdir=eval

环境变量：
  CONCLAVE_EVAL_BASE_URL: 后端 URL（默认 http://localhost:8000）
  CONCLAVE_EVAL_FRONTEND_URL: 前端 URL（默认 http://localhost:5173）
  CONCLAVE_ADMIN_USERNAME: 管理员用户名（默认 admin）
  CONCLAVE_ADMIN_PASSWORD: 管理员密码（默认 admin123）
  CONCLAVE_EVAL_REAL_LLM: 设为 1 启用真实 LLM 会议测试
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
import pytest

# ========================================================================
# 配置
# ========================================================================

BASE_URL = os.environ.get("CONCLAVE_EVAL_BASE_URL", "http://localhost:8000")
FRONTEND_URL = os.environ.get("CONCLAVE_EVAL_FRONTEND_URL", "http://localhost:5173")
ADMIN_USERNAME = os.environ.get("CONCLAVE_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("CONCLAVE_ADMIN_PASSWORD", "admin123")
EVAL_REAL_LLM = os.environ.get("CONCLAVE_EVAL_REAL_LLM") == "1"

# 超时常量
HTTP_TIMEOUT = 15.0       # 普通请求超时（秒）
POLL_INTERVAL = 5         # 会议轮询间隔（秒）
MEETING_TIMEOUT = 600     # 会议运行超时（秒）
MAX_RETRIES = 3           # 429 重试次数

# 六阶段枚举
ALL_STAGES = ("clarify", "intra_team", "cross_team", "evidence_check", "arbitrate", "produce")

# 核心端点路径（用于 OpenAPI schema 覆盖检查）
CORE_PATHS = [
    "/health",
    "/auth/login",
    "/auth/me",
    "/meetings",
    "/meetings/{meeting_id}",
    "/meetings/{meeting_id}/run",
    "/meetings/{meeting_id}/progress",
    "/meetings/{meeting_id}/summary",
    "/meetings/{meeting_id}/control",
    "/agent-roles",
]


# ========================================================================
# 服务可达性检查（模块加载时执行，决定是否跳过全部测试）
# ========================================================================


def _service_reachable() -> bool:
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=5, trust_env=False)
        return resp.status_code < 500
    except Exception:
        return False


_SERVICE_REACHABLE = _service_reachable()

pytestmark = pytest.mark.skipif(
    not _SERVICE_REACHABLE,
    reason=f"后端服务不可达: {BASE_URL}（请先 docker compose up -d 启动 Conclave）",
)


# ========================================================================
# HTTP 客户端封装（含 429 重试）
# ========================================================================


class EvalClient:
    """httpx 封装，自动处理 429 限流重试"""

    def __init__(self, timeout: float = HTTP_TIMEOUT):
        self._client = httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, trust_env=False
        )

    async def __aenter__(self) -> "EvalClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_resp = None
        for attempt in range(MAX_RETRIES + 1):
            resp = await self._client.request(method, url, **kwargs)
            if resp.status_code != 429:
                return resp
            last_resp = resp
            retry_after = int(resp.headers.get("Retry-After", "5"))
            await asyncio.sleep(min(retry_after, 30))
        return last_resp  # type: ignore[return-value]

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request("POST", url, **kwargs)


# ========================================================================
# Fixtures
# ========================================================================


@pytest.fixture
async def client() -> EvalClient:
    async with EvalClient() as c:
        yield c


@pytest.fixture
async def auth_token(client: EvalClient) -> str:
    """登录获取 JWT token"""
    resp = await client.post(
        f"{BASE_URL}/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data["access_token"], "登录响应缺少 access_token"
    return data["access_token"]


@pytest.fixture
async def auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


# ========================================================================
# 辅助函数
# ========================================================================


async def _create_meeting(
    client: EvalClient, headers: dict[str, str], topic: str = "评估测试会议"
) -> str:
    """创建会议，返回 meeting_id"""
    resp = await client.post(
        f"{BASE_URL}/meetings",
        json={
            "topic": topic,
            "deliverable_type": "prd_openapi",
            "flow_plan": "full",
            "debate_depth": "standard",
        },
        headers=headers,
    )
    assert resp.status_code == 200, f"创建会议失败: {resp.status_code} {resp.text}"
    return resp.json()["meeting_id"]


async def _create_and_run_meeting_to_done(
    client: EvalClient, headers: dict[str, str], timeout: int = MEETING_TIMEOUT
) -> dict[str, Any]:
    """创建并运行会议到终态，返回完整详情"""
    meeting_id = await _create_meeting(
        client,
        headers,
        topic="设计一个待办事项（Todo）管理的 RESTful API，包含任务创建、完成、删除和列表查询功能",
    )
    # 触发异步运行
    resp = await client.post(f"{BASE_URL}/meetings/{meeting_id}/run", headers=headers)
    assert resp.status_code in (200, 202), f"触发运行失败: {resp.status_code} {resp.text}"

    # 轮询进度
    deadline = time.time() + timeout
    terminal = False
    last_status = "unknown"
    while time.time() < deadline:
        resp = await client.get(
            f"{BASE_URL}/meetings/{meeting_id}/progress", headers=headers
        )
        if resp.status_code == 200:
            progress = resp.json()
            last_status = progress.get("status", "unknown")
            if last_status in ("done", "failed", "aborted"):
                terminal = True
                break
        await asyncio.sleep(POLL_INTERVAL)

    if not terminal:
        raise AssertionError(
            f"会议 {meeting_id} 在 {timeout}s 内未到达终态，最后状态: {last_status}"
        )

    # 获取完整详情
    resp = await client.get(f"{BASE_URL}/meetings/{meeting_id}", headers=headers)
    assert resp.status_code == 200, f"获取详情失败: {resp.status_code} {resp.text}"
    return resp.json()


# ========================================================================
# 第一层：服务就绪性测试（不需要认证）
# ========================================================================


class TestServiceReadiness:
    """评估服务是否已部署并可直接运行

    预期终态：
      - 后端 /health 返回 200，status=ok
      - 依赖（postgresql / redis / qdrant）均 ok
      - API 文档 /docs 和 /openapi.json 可访问
      - 前端页面可访问
      - CORS 正确配置
    """

    @pytest.mark.asyncio
    async def test_backend_health_ok(self, client: EvalClient):
        """后端 /health 返回 200 且 status=ok 或 degraded"""
        resp = await client.get(f"{BASE_URL}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded"), f"健康状态异常: {data['status']}"

    @pytest.mark.asyncio
    async def test_health_dependencies_all_ok(self, client: EvalClient):
        """后端 /health 中 postgresql / redis / qdrant 均为 ok"""
        resp = await client.get(f"{BASE_URL}/health")
        assert resp.status_code == 200
        checks = resp.json().get("checks", {})
        assert "postgresql" in checks, f"缺少 postgresql 健康检查: {checks}"
        assert checks["postgresql"] == "ok", f"PostgreSQL 不可用: {checks['postgresql']}"
        if "redis" in checks:
            assert checks["redis"] == "ok", f"Redis 不可用: {checks['redis']}"
        if "qdrant" in checks:
            assert checks["qdrant"] == "ok", f"Qdrant 不可用: {checks['qdrant']}"

    @pytest.mark.asyncio
    async def test_api_docs_accessible(self, client: EvalClient):
        """GET /docs 返回 200（Swagger UI 可访问）"""
        resp = await client.get(f"{BASE_URL}/docs")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_schema_valid(self, client: EvalClient):
        """GET /openapi.json 返回 200 且含 paths 字段"""
        resp = await client.get(f"{BASE_URL}/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema, "OpenAPI schema 缺少 paths 字段"
        assert len(schema["paths"]) > 0, "OpenAPI schema paths 为空"

    @pytest.mark.asyncio
    async def test_frontend_accessible(self, client: EvalClient):
        """前端页面返回 200"""
        try:
            resp = await client.get(FRONTEND_URL)
        except Exception:
            pytest.skip(f"前端服务不可达: {FRONTEND_URL}")
        assert resp.status_code == 200, f"前端返回非 200: {resp.status_code}"

    @pytest.mark.asyncio
    async def test_cors_headers_present(self, client: EvalClient):
        """CORS 头正确配置（允许前端域名跨域）"""
        resp = await client.get(
            f"{BASE_URL}/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.status_code == 200
        acao = resp.headers.get("access-control-allow-origin")
        assert acao is not None, "响应缺少 access-control-allow-origin 头"


# ========================================================================
# 第二层：认证系统测试
# ========================================================================


class TestAuthSystem:
    """评估认证系统是否完整可用

    预期终态：
      - 默认凭证 admin/admin123 可登录，返回 JWT access_token
      - 登录响应包含 user 对象，role=admin
      - 错误密码被拒绝（401）
      - /auth/me 带正确 JWT 返回用户信息
      - /auth/me 不带 JWT 返回 401
      - 需认证端点不带 token 返回 401
      - /setup/status 返回 needs_setup=false（系统已初始化）
    """

    @pytest.mark.asyncio
    async def test_login_with_default_credentials(self, client: EvalClient):
        """默认凭证 admin/admin123 登录成功，返回 JWT"""
        resp = await client.post(
            f"{BASE_URL}/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"], "登录响应缺少 access_token"
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0
        user = data["user"]
        assert user["username"] == ADMIN_USERNAME
        assert user["role"] == "admin", f"用户角色不是 admin: {user['role']}"

    @pytest.mark.asyncio
    async def test_login_wrong_password_rejected(self, client: EvalClient):
        """错误密码登录返回 401"""
        resp = await client.post(
            f"{BASE_URL}/auth/login",
            json={"username": ADMIN_USERNAME, "password": "wrong_password_123"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_endpoint_with_token(self, client: EvalClient, auth_headers):
        """GET /auth/me 带正确 JWT 返回用户信息（嵌套在 user 字段中）"""
        resp = await client.get(f"{BASE_URL}/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # /auth/me 返回 {"user": {"username": ..., "role": ...}}
        user = data["user"]
        assert user["username"] == ADMIN_USERNAME
        assert user["role"] == "admin"

    @pytest.mark.asyncio
    async def test_me_endpoint_without_token_rejected(self, client: EvalClient):
        """GET /auth/me 不带 JWT 返回 401"""
        resp = await client.get(f"{BASE_URL}/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_endpoint_requires_auth(self, client: EvalClient):
        """需要认证的端点（POST /meetings）不带 token 返回 401"""
        resp = await client.post(
            f"{BASE_URL}/meetings",
            json={"topic": "测试会议"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_setup_status_initialized(self, client: EvalClient):
        """GET /setup/status 返回 needs_setup=false（系统已初始化）"""
        resp = await client.get(f"{BASE_URL}/setup/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "needs_setup" in data, f"响应缺少 needs_setup 字段: {data}"
        assert data["needs_setup"] is False, f"系统未初始化: {data}"


# ========================================================================
# 第三层：会议核心工作流测试（需要认证）
# ========================================================================


class TestMeetingWorkflow:
    """评估会议核心工作流完整性

    预期终态：
      - POST /meetings 创建成功，返回 mtg- 前缀 ID，stage=clarify，status=running
      - GET /meetings 返回列表，含 meetings / total / running_count
      - GET /meetings/{id} 返回完整详情（含 claims / conflicts / messages / llm_trace 等字段）
      - GET /meetings/{id}/progress 返回进度（status / stage / counts）
      - GET /meetings/{id}/summary 返回摘要
      - GET /meetings/{id}/report-layout 返回布局 spec
      - POST /meetings/{id}/control 支持 pause / resume / abort
      - 无效会议 ID 返回 404
    """

    @pytest.mark.asyncio
    async def test_create_meeting(self, client: EvalClient, auth_headers):
        """POST /meetings 创建会议成功，初始 stage=clarify status=running"""
        resp = await client.post(
            f"{BASE_URL}/meetings",
            json={
                "topic": "部署评估-创建会议测试",
                "deliverable_type": "prd_openapi",
                "flow_plan": "full",
                "debate_depth": "standard",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["meeting_id"].startswith("mtg-"), f"meeting_id 格式异常: {data['meeting_id']}"
        assert data["stage"] == "clarify", f"初始阶段异常: {data['stage']}"
        assert data["status"] == "running", f"初始状态异常: {data['status']}"

    @pytest.mark.asyncio
    async def test_list_meetings(self, client: EvalClient, auth_headers):
        """GET /meetings 返回会议列表"""
        await _create_meeting(client, auth_headers, topic="部署评估-列表测试")
        resp = await client.get(f"{BASE_URL}/meetings", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "meetings" in data
        assert isinstance(data["meetings"], list)
        assert data["total"] >= 1, "会议列表为空"
        assert "running_count" in data, "响应缺少 running_count 字段"

    @pytest.mark.asyncio
    async def test_get_meeting_detail(self, client: EvalClient, auth_headers):
        """GET /meetings/{id} 返回完整详情（含所有关键字段）"""
        meeting_id = await _create_meeting(client, auth_headers, topic="部署评估-详情测试")
        resp = await client.get(f"{BASE_URL}/meetings/{meeting_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["meeting_id"] == meeting_id
        assert data["topic"] == "部署评估-详情测试"
        for field in ("stage", "status", "claims", "conflicts", "messages", "llm_trace"):
            assert field in data, f"会议详情缺少 {field} 字段"

    @pytest.mark.asyncio
    async def test_get_meeting_progress(self, client: EvalClient, auth_headers):
        """GET /meetings/{id}/progress 返回进度信息"""
        meeting_id = await _create_meeting(client, auth_headers, topic="部署评估-进度测试")
        resp = await client.get(f"{BASE_URL}/meetings/{meeting_id}/progress", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["meeting_id"] == meeting_id
        assert "status" in data
        assert "stage" in data
        assert "message_count" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_get_meeting_summary(self, client: EvalClient, auth_headers):
        """GET /meetings/{id}/summary 返回摘要"""
        meeting_id = await _create_meeting(client, auth_headers, topic="部署评估-摘要测试")
        resp = await client.get(
            f"{BASE_URL}/meetings/{meeting_id}/summary", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["meeting_id"] == meeting_id
        assert "topic" in data
        assert "status" in data

    @pytest.mark.asyncio
    async def test_get_report_layout(self, client: EvalClient, auth_headers):
        """GET /meetings/{id}/report-layout 返回布局 spec（含 sections）"""
        meeting_id = await _create_meeting(client, auth_headers, topic="部署评估-报告布局测试")
        resp = await client.get(
            f"{BASE_URL}/meetings/{meeting_id}/report-layout", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "sections" in data, "报告布局缺少 sections 字段"
        assert len(data["sections"]) > 0, "报告布局 sections 为空"

    @pytest.mark.asyncio
    async def test_control_signals(self, client: EvalClient, auth_headers):
        """POST /meetings/{id}/control 支持 pause / resume / abort"""
        meeting_id = await _create_meeting(client, auth_headers, topic="部署评估-控场信号测试")

        # pause
        resp = await client.post(
            f"{BASE_URL}/meetings/{meeting_id}/control",
            json={"signal": "pause", "payload": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"pause 失败: {resp.status_code} {resp.text}"
        assert resp.json()["status"] == "paused"

        # resume
        resp = await client.post(
            f"{BASE_URL}/meetings/{meeting_id}/control",
            json={"signal": "resume", "payload": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"resume 失败: {resp.status_code} {resp.text}"
        assert resp.json()["status"] == "running"

        # abort
        resp = await client.post(
            f"{BASE_URL}/meetings/{meeting_id}/control",
            json={"signal": "abort", "payload": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"abort 失败: {resp.status_code} {resp.text}"
        assert resp.json()["status"] == "aborted"

    @pytest.mark.asyncio
    async def test_invalid_meeting_id_returns_404(self, client: EvalClient, auth_headers):
        """无效会议 ID 返回 404"""
        resp = await client.get(f"{BASE_URL}/meetings/invalid-id-xxx", headers=auth_headers)
        assert resp.status_code == 404


# ========================================================================
# 第四层：辅助端点测试
# ========================================================================


class TestAuxiliaryEndpoints:
    """评估辅助端点可用性

    预期终态：
      - /agent-roles 返回角色列表（>= 2 个角色）
      - /metrics 返回指标 dict
      - /regression/baselines 返回基线列表
      - /preferences/ 返回偏好 dict
      - /api/captcha/status 返回验证码值守状态
    """

    @pytest.mark.asyncio
    async def test_list_agent_roles(self, client: EvalClient, auth_headers):
        """GET /agent-roles 返回角色列表，至少有 2 个角色"""
        resp = await client.get(f"{BASE_URL}/agent-roles", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "roles" in data
        assert len(data["roles"]) >= 2, f"角色数量不足: {len(data['roles'])}"

    @pytest.mark.asyncio
    async def test_get_metrics(self, client: EvalClient, auth_headers):
        """GET /metrics 返回指标"""
        resp = await client.get(f"{BASE_URL}/metrics", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    @pytest.mark.asyncio
    async def test_regression_baselines(self, client: EvalClient, auth_headers):
        """GET /regression/baselines 返回基线列表"""
        resp = await client.get(f"{BASE_URL}/regression/baselines", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_preferences(self, client: EvalClient, auth_headers):
        """GET /preferences/ 返回偏好"""
        resp = await client.get(f"{BASE_URL}/preferences/", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    @pytest.mark.asyncio
    async def test_captcha_status(self, client: EvalClient):
        """GET /api/captcha/status 返回验证码值守状态"""
        resp = await client.get(f"{BASE_URL}/api/captcha/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "guard_mode" in data, f"响应缺少 guard_mode 字段: {data}"


# ========================================================================
# 第五层：服务完整性测试
# ========================================================================


class TestServiceCompleteness:
    """评估服务完整性：核心 API 路径覆盖、默认凭证可发现性

    预期终态：
      - OpenAPI schema 包含所有核心端点路径
      - 默认凭证 admin/admin123 可用（服务文档化）
      - 服务运行 URL 可直接访问
    """

    @pytest.mark.asyncio
    async def test_core_paths_in_openapi(self, client: EvalClient):
        """OpenAPI schema 包含所有核心端点路径"""
        resp = await client.get(f"{BASE_URL}/openapi.json")
        assert resp.status_code == 200
        paths = set(resp.json().get("paths", {}).keys())
        missing = [p for p in CORE_PATHS if p not in paths]
        assert not missing, f"OpenAPI schema 缺少核心路径: {missing}"

    @pytest.mark.asyncio
    async def test_default_credentials_work(self, client: EvalClient):
        """默认凭证 admin/admin123 可登录（服务提供可用默认账号）"""
        resp = await client.post(
            f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200, "默认凭证 admin/admin123 无法登录"
        data = resp.json()
        assert data["access_token"], "默认凭证登录未返回 token"
        assert data["user"]["role"] == "admin", "默认账号角色不是 admin"

    @pytest.mark.asyncio
    async def test_service_url_directly_accessible(self, client: EvalClient):
        """服务 URL 可直接访问（http://localhost:8000/health 返回 200）"""
        resp = await client.get(f"{BASE_URL}/health")
        assert resp.status_code == 200
        assert resp.json()["status"] in ("ok", "degraded")

    @pytest.mark.asyncio
    async def test_meeting_run_endpoint_exists(self, client: EvalClient, auth_headers):
        """POST /meetings/{id}/run 端点存在且可调用"""
        meeting_id = await _create_meeting(client, auth_headers, topic="run 端点测试")
        resp = await client.post(f"{BASE_URL}/meetings/{meeting_id}/run", headers=auth_headers)
        assert resp.status_code in (200, 202), f"run 端点异常: {resp.status_code} {resp.text}"


# ========================================================================
# 第六层：真实会议端到端测试（需要真实 LLM，opt-in）
# ========================================================================


@pytest.mark.real_llm
@pytest.mark.skipif(not EVAL_REAL_LLM, reason="需要 CONCLAVE_EVAL_REAL_LLM=1")
class TestRealMeetingE2E:
    """评估真实 LLM 会议的完整性和终态

    预期终态：
      - 会议到达 done 终态，stage=produce
      - 产出 claims（intra_team 成功）
      - 检出 conflicts（cross_team 成功）
      - 产出 decisions（arbitrate 成功）
      - 产出 artifact：prd + openapi（produce 成功）
      - LLM trace 无降级（fallback=0, invalid=0）
      - 六阶段全部完成
      - 生成 key_questions（clarify 成功）
      - 生成 clarified_topic
      - 生成 messages（>= 5 条）
      - team_config 有效（>= 2 个角色）
    """

    @pytest.mark.asyncio
    async def test_full_meeting_reaches_done(self, client: EvalClient, auth_headers):
        """完整会议到达 done 终态，stage=produce"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        assert detail["status"] == "done", f"会议未到达 done 终态: {detail['status']}"
        assert detail["stage"] == "produce", f"会议未到达 produce 阶段: {detail['stage']}"

    @pytest.mark.asyncio
    async def test_meeting_produces_claims(self, client: EvalClient, auth_headers):
        """会议产出 claims（intra_team 阶段成功）"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        claims = detail.get("claims", [])
        assert len(claims) > 0, "会议未产出任何 claims"

    @pytest.mark.asyncio
    async def test_meeting_produces_conflicts(self, client: EvalClient, auth_headers):
        """会议检出 conflicts（cross_team 阶段成功）"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        conflicts = detail.get("conflicts", [])
        assert len(conflicts) >= 1, f"会议未检出冲突，conflicts={conflicts}"

    @pytest.mark.asyncio
    async def test_meeting_produces_decisions(self, client: EvalClient, auth_headers):
        """会议产出 decisions（arbitrate 阶段成功）"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        decision_record = detail.get("decision_record", {})
        decisions = (
            decision_record.get("decisions", []) if isinstance(decision_record, dict) else []
        )
        assert len(decisions) > 0, f"会议未产出决策，decision_record={decision_record}"

    @pytest.mark.asyncio
    async def test_meeting_produces_artifact(self, client: EvalClient, auth_headers):
        """会议产出 artifact：prd + openapi（produce 阶段成功）"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        artifact = detail.get("artifact", {})
        assert artifact, "会议未产出 artifact"
        prd = artifact.get("prd", {})
        assert prd, "artifact 缺少 prd"
        assert prd.get("title"), "prd 缺少 title"
        assert prd.get("goal"), "prd 缺少 goal"
        assert prd.get("scope"), "prd 缺少 scope"
        assert artifact.get("openapi"), "artifact 缺少 openapi"
        api_endpoints = prd.get("api_endpoints", [])
        assert len(api_endpoints) >= 2, f"prd.api_endpoints 不足 2 个: {api_endpoints}"

    @pytest.mark.asyncio
    async def test_meeting_llm_trace_clean(self, client: EvalClient, auth_headers):
        """会议 LLM trace 无降级（fallback=0, invalid=0）"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        llm_trace = detail.get("llm_trace", {})
        fallback = llm_trace.get("fallback_calls", 0)
        invalid = llm_trace.get("invalid_calls", 0)
        assert fallback == 0, f"LLM trace 存在 fallback 降级: {fallback} 次"
        assert invalid == 0, f"LLM trace 存在 invalid 调用: {invalid} 次"

    @pytest.mark.asyncio
    async def test_meeting_all_stages_completed(self, client: EvalClient, auth_headers):
        """会议所有六阶段完成（confidence_flags + stage_stats 覆盖全部阶段）"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        confidence_flags = detail.get("confidence_flags", {})
        llm_trace = detail.get("llm_trace", {})
        stage_stats = llm_trace.get("stage_stats", {})
        for stage in ALL_STAGES:
            assert stage in confidence_flags, f"confidence_flags 缺少阶段: {stage}"
            assert stage in stage_stats, f"llm_trace.stage_stats 缺少阶段: {stage}"

    @pytest.mark.asyncio
    async def test_meeting_key_questions_generated(self, client: EvalClient, auth_headers):
        """会议生成 key_questions（clarify 阶段成功，>= 2 个）"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        key_questions = detail.get("key_questions", [])
        assert len(key_questions) >= 2, f"key_questions 不足 2 个: {key_questions}"

    @pytest.mark.asyncio
    async def test_meeting_clarified_topic(self, client: EvalClient, auth_headers):
        """会议生成 clarified_topic（非空，长度 > 10）"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        clarified_topic = detail.get("clarified_topic", "")
        assert clarified_topic, "clarified_topic 为空"
        assert len(clarified_topic) > 10, f"clarified_topic 过短: {clarified_topic}"

    @pytest.mark.asyncio
    async def test_meeting_messages_generated(self, client: EvalClient, auth_headers):
        """会议生成 messages（>= 5 条）"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        messages = detail.get("messages", [])
        assert len(messages) >= 5, f"messages 不足 5 条: {len(messages)}"

    @pytest.mark.asyncio
    async def test_meeting_team_config_valid(self, client: EvalClient, auth_headers):
        """会议 team_config 有效（>= 2 个角色，每个含 role 字段）"""
        detail = await _create_and_run_meeting_to_done(client, auth_headers)
        team_config = detail.get("team_config", [])
        assert len(team_config) >= 2, f"team_config 不足 2 个角色: {team_config}"
        for cfg in team_config:
            assert "role" in cfg, f"team_config 条目缺少 role 字段: {cfg}"
