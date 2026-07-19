# 测试全局配置 + 公共夹具
# 必须在导入 app 之前设置环境变量
import os

# CONCLAVE_TEST_REAL_LLM=1 时加载 .env 使用真实 LLM；默认走 StubLLM
# 用法：CONCLAVE_TEST_REAL_LLM=1 python -m pytest -m real_llm
if os.environ.get("CONCLAVE_TEST_REAL_LLM") != "1":
    os.environ.setdefault("CONCLAVE_LLM_API_KEY", "")
    os.environ.setdefault("CONCLAVE_EMBED_API_KEY", "")
    os.environ.setdefault("CONCLAVE_RERANK_API_KEY", "")
# 真实 LLM 模式下不设置空值，让 config.py 的 _load_dotenv() 从 .env 加载真实 key

# 测试使用 PostgreSQL；Docker 内由 compose 注入 DATABASE_URL，本地开发默认连 5433
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://conclave:conclave_dev@localhost:5433/conclave_test",
)


def _ensure_test_database() -> None:
    """在导入 app 前确保测试数据库存在（连到默认 postgres 库创建）。"""
    import psycopg2
    from psycopg2.sql import Identifier, SQL
    from urllib.parse import urlparse

    raw_url = os.environ.get("DATABASE_URL", "")
    # asyncpg 风格的 URL 需要转换成 psycopg2 可识别的形式
    pg_url = raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(pg_url)
    dbname = parsed.path.lstrip("/") or "conclave_test"
    # 连接到默认 postgres 数据库进行管理
    admin_parts = parsed._replace(path="/postgres")
    admin_url = admin_parts.geturl()
    try:
        conn = psycopg2.connect(admin_url)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if not cur.fetchone():
            cur.execute(SQL("CREATE DATABASE {}").format(Identifier(dbname)))
        cur.close()
        conn.close()
    except Exception:
        # 无权限或数据库已存在时忽略，让应用启动逻辑自行处理
        pass


_ensure_test_database()

# 迭代二：测试时禁用记忆提取，避免历史画像干扰断言
os.environ.setdefault("CONCLAVE_MEMORY_DISABLED", "1")

# 测试时降低日志级别为 WARNING，减少输出噪声
os.environ.setdefault("CONCLAVE_LOG_LEVEL", "WARNING")

# 测试用固定 API token，避免依赖 .dev_token 文件生成，同时让中间件进入可预测模式
os.environ.setdefault("CONCLAVE_API_TOKEN", "test-token-for-ci")
# 测试中关闭总速率限制与失败封禁，避免高频 fixture 初始化触发 429/封禁
os.environ.setdefault("CONCLAVE_RATE_LIMIT_PER_MIN", "100000")
os.environ.setdefault("CONCLAVE_RATE_LIMIT_FAIL_PER_MIN", "100000")

# 测试模式标记
os.environ.setdefault("CONCLAVE_TEST_MODE", "1")

# [测试审查修复] 中间件和 WS 认证要求 APP_ENV=test AND CONCLAVE_TEST_DISABLE_AUTH=1 双重条件
# 之前只设置了 CONCLAVE_TEST_DISABLE_AUTH，导致测试模式认证绕过未生效
os.environ.setdefault("APP_ENV", "test")
# 测试模式关闭认证，避免每个 client fixture 都需携带 token
os.environ.setdefault("CONCLAVE_TEST_DISABLE_AUTH", "1")

# 测试模式下关闭非必要的后台任务与外部依赖，减少资源泄漏与启动耗时
os.environ.setdefault("CONCLAVE_DISABLE_SANDBOX_WARMUP", "1")
os.environ.setdefault("CONCLAVE_DISABLE_PRICING_LOADER", "1")
os.environ.setdefault("CONCLAVE_DISABLE_KEY_LOADER", "1")
os.environ.setdefault("CONCLAVE_DISABLE_METRICS", "1")


import asyncio
import pytest
from fastapi.testclient import TestClient

from app.events import bus
from app.main import create_app
from app.orchestrator import runner as runner_mod
from app.routers import meetings as meetings_mod


# 每个测试前清空事件表并重置序列，保证事件 seq 从 0 开始
@pytest.fixture(autouse=True)
def _reset_event_bus():
    try:
        import psycopg2
        raw_url = os.environ.get("DATABASE_URL", "")
        # asyncpg 风格的 URL 需要转换成 psycopg2 可识别的形式
        pg_url = raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        conn = psycopg2.connect(pg_url)
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("TRUNCATE TABLE events RESTART IDENTITY CASCADE")
            cur.close()
        finally:
            conn.close()
    except Exception:
        pass
    bus._history.clear()
    bus._subs.clear()
    yield


# ---------- pytest 标记注册 ----------


def pytest_configure(config):
    config.addinivalue_line("markers", "real_llm: 需要真实 LLM API key 的集成测试")


# ---------- 公共 fixture：TestClient ----------


@pytest.fixture(scope="function")
def client():
    """FastAPI 测试客户端（带 lifespan 初始化，函数级隔离）"""
    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------- 公共 fixture：状态重置（autouse） ----------


@pytest.fixture(autouse=True)
def _reset_state():
    """每个测试前后清理进程级状态（runner / event bus / vector store / 数据库连接池）

    确保测试间无状态泄漏：
    - runner_mod._states：会议运行态
    - meetings_mod._running_tasks：异步后台任务
    - bus._subs / bus._history：事件订阅和历史
    - store_mod._stores：RAG 向量库
    - memory_store：三层记忆
    - 异步/同步数据库连接池
    """
    import asyncio
    import contextlib
    from app.db.engine import dispose_async_engine
    runner_mod._states.clear()
    meetings_mod._running_tasks.clear()
    meetings_mod._run_locks.clear()
    bus._subs.clear()
    bus._history.clear()
    # 清理 RAG 向量库
    from app.rag import store as store_mod
    store_mod._stores.clear()
    # 清理角色单例缓存（确保 get_agent 每次测试新建）
    from app.agents import roles as roles_mod
    roles_mod._agents.clear()
    # 清理 Agent 计算单例（确保 get_compute 每次测试重建，避免 mock/配置泄漏）
    from app.agents.compute import reset_compute
    reset_compute()
    # 清理三层记忆（内存 + PG 表）
    # 注意：必须先 dispose 旧 engine，避免旧 engine 绑定到已关闭的事件循环导致 "different loop" 错误
    from app.memory.store import memory_store
    with contextlib.suppress(Exception):
        dispose_async_engine()
    with contextlib.suppress(Exception):
        asyncio.run(memory_store.clear())
    # asyncio.run 内创建的 engine 绑定到已关闭的临时循环，必须再次 dispose
    with contextlib.suppress(Exception):
        dispose_async_engine()
    # 重置 memory_store 的 _initialized 标志，让 lifespan 中的 init() 重新初始化
    memory_store._initialized = False
    # 清理浏览器/Playwright 单例（避免 Lock 绑定到旧循环）
    with contextlib.suppress(Exception):
        from app.tools import playwright_search as pw_mod
        pw_mod._instance = None
    with contextlib.suppress(Exception):
        from app.tools import browser_tool as bt_mod
        bt_mod._pool_instance = None
        bt_mod._tool_instance = None
    # 清理 network_security 的 httpx 客户端（绑定到旧循环）
    with contextlib.suppress(Exception):
        from app import network_security as ns_mod
        ns_mod._async_client = None
    # 清理 captcha_guard 单例
    with contextlib.suppress(Exception):
        from app.tools import captcha_guard as cg_mod
        cg_mod._guard_instance = None
    # 清理 ws 模块的事件日志
    with contextlib.suppress(Exception):
        from app.routers import ws as ws_mod
        ws_mod._ws_event_log.clear()
    # 清理 pricing_fetcher 动态缓存
    with contextlib.suppress(Exception):
        from app import pricing_fetcher as pf_mod
        pf_mod._dynamic_pricing.clear()
        pf_mod._last_fetch_time = 0
        pf_mod._fetch_started = False
    # 清理 sandbox 服务状态
    with contextlib.suppress(Exception):
        from app import sandbox as sb_mod
        sb_mod._allocated_ports.clear()
        sb_mod._running_services.clear()
        sb_mod._docker_available = None
        sb_mod._resolved_image = None
        sb_mod._resolved_named_images.clear()
    # 清理 web_search 单例（避免 Playwright 实例跨测试泄漏）
    with contextlib.suppress(Exception):
        from app import tools as tools_mod
        tools_mod._instance = None
    yield
    runner_mod._states.clear()
    meetings_mod._running_tasks.clear()
    meetings_mod._run_locks.clear()
    bus._subs.clear()
    bus._history.clear()
    store_mod._stores.clear()
    roles_mod._agents.clear()
    # 关闭 RealLLM 的 httpx 连接池（如有），防止事件循环挂起
    try:
        import inspect
        from app.agents.compute import _compute
        if _compute is not None and hasattr(_compute, "aclose"):
            loop = asyncio.new_event_loop()
            try:
                if inspect.iscoroutinefunction(_compute.aclose):
                    loop.run_until_complete(_compute.aclose())
            finally:
                loop.close()
    except Exception:
        pass
    reset_compute()
    # 释放异步引擎，避免跨测试连接泄漏
    with contextlib.suppress(Exception):
        dispose_async_engine()


# ---------- 公共 fixture：同步运行会议到完成 ----------


def run_to_done(meeting_id: str):
    """同步运行会议到完成（供非 fixture 测试函数使用）

    处理暂停态恢复，直接调 Runner.run 完成六阶段。
    """
    state = runner_mod.get_state(meeting_id)
    assert state is not None, f"会议 {meeting_id} 不存在"
    if state.status.value == "paused":
        state.status = runner_mod.MeetingStatus.RUNNING
        state.paused_snapshot = None
    runner = runner_mod.Runner()
    state = asyncio.run(runner.run(state))
    runner_mod.set_state(state)
    return state


@pytest.fixture()
def run_meeting():
    """返回一个可调用的会议运行函数"""
    return run_to_done


# ---------- 公共 fixture：Mock LLM（用于测试 RealLLM 逻辑） ----------


class MockLLM:
    """可控 Mock LLM：按预设返回值模拟 RealLLM 行为

    用法：
        def test_xxx(mock_llm):
            mock_llm.set_response("clarify", {"clarified_topic": "测试", ...})
            # 此时 get_llm() 返回 mock_llm
    """

    def __init__(self):
        self._responses: dict[str, dict] = {}
        self.call_log: list[tuple[str, str]] = []  # (prompt, schema_hint)

    def set_response(self, schema_hint: str, response: dict):
        """设置某阶段的返回值"""
        self._responses[schema_hint] = response

    async def complete(
        self,
        prompt: str,
        schema_hint: str = "",
        model_override: str = "",
        agent_role: str = "",
    ) -> dict:
        self.call_log.append((prompt, schema_hint, model_override, agent_role))
        if schema_hint in self._responses:
            return self._responses[schema_hint]
        return {"result": "mock"}


@pytest.fixture()
def mock_llm(monkeypatch):
    """替换全局 LLM 工厂为 MockLLM"""
    mock = MockLLM()
    # monkeypatch get_llm 返回 mock
    from app.agents import llm as llm_mod
    monkeypatch.setattr(llm_mod, "get_llm", lambda: mock)
    # 同时替换 roles.py 中已创建的 Agent 的 llm
    from app.agents import roles as roles_mod
    original_get_agent = roles_mod.get_agent

    def patched_get_agent(role):
        agent = original_get_agent(role)
        agent.llm = mock
        return agent

    monkeypatch.setattr(roles_mod, "get_agent", patched_get_agent)
    # 清空缓存让 patched 生效
    roles_mod._agents.clear()
    return mock
