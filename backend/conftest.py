# 测试全局配置 + 公共夹具
# 必须在导入 app 之前设置环境变量
import os
import tempfile

# 测试强制走 stub 模式，不调真实 API
os.environ.setdefault("CONCLAVE_LLM_API_KEY", "")
os.environ.setdefault("CONCLAVE_EMBED_API_KEY", "")
os.environ.setdefault("CONCLAVE_RERANK_API_KEY", "")

# SQLite 路径指向临时目录，避免污染工作目录
os.environ.setdefault(
    "CONCLAVE_DB_PATH", os.path.join(tempfile.gettempdir(), "conclave_test.db")
)

# 迭代二：测试时禁用记忆提取，避免历史画像干扰断言
os.environ.setdefault("CONCLAVE_MEMORY_DISABLED", "1")

# 测试时降低日志级别为 WARNING，减少输出噪声
os.environ.setdefault("CONCLAVE_LOG_LEVEL", "WARNING")

import asyncio
import pytest
from fastapi.testclient import TestClient

from app.events import bus
from app.main import create_app
from app.orchestrator import runner as runner_mod
from app.routers import meetings as meetings_mod


# ---------- 公共 fixture：TestClient ----------

@pytest.fixture()
def client():
    """FastAPI 测试客户端（带 lifespan 初始化）"""
    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------- 公共 fixture：状态重置（autouse） ----------

@pytest.fixture(autouse=True)
def _reset_state():
    """每个测试前后清理进程级状态（runner / event bus / vector store）

    确保测试间无状态泄漏：
    - runner_mod._states：会议运行态
    - meetings_mod._running_tasks：异步后台任务
    - bus._subs / bus._history：事件订阅和历史
    - store_mod._stores：RAG 向量库
    - memory_store：三层记忆
    """
    runner_mod._states.clear()
    meetings_mod._running_tasks.clear()
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
    yield
    runner_mod._states.clear()
    meetings_mod._running_tasks.clear()
    bus._subs.clear()
    bus._history.clear()
    store_mod._stores.clear()
    roles_mod._agents.clear()
    reset_compute()


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

    async def complete(self, prompt: str, schema_hint: str = "") -> dict:
        self.call_log.append((prompt, schema_hint))
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
