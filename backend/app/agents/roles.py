# §3.1 角色定义 + Agent 工厂
# 注意：Agent 类的 clarify/intra_speak/cross_team/evidence_check/arbitrate/produce 六个方法
# 已被 compute.py 的 build_xxx_prompt + get_compute().think() 取代（主流程不再调用 Agent 方法）。
# 此处保留 Agent 类作为"角色 + LLM"的薄壳，仅为向后兼容测试 fixture 而存在。
# 设计模式：Facade —— 旧的 Agent 接口保留，实际计算委托 compute.py。
from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents import llm as llm_mod
from app.agents.llm import LLMClient

# 统一单一数据源：re-export app.models.Role（7 角色）
# 消除历史上 agents/roles.Role（3 角色）与 models.Role（7 角色）不一致的漂移
from app.models import Role

if TYPE_CHECKING:
    pass


class Agent:
    """角色 Agent 壳：持有 role + LLM 引用。

    历史职责（已迁移到 compute.py）：
    - clarify / intra_speak / cross_team / evidence_check / arbitrate / produce
    - 这些方法曾是 Agent 的实例方法，现已由 compute.build_xxx_prompt + Compute.think() 取代。
    - 保留此类仅为向后兼容（conftest.py 的 mock_llm fixture 仍 patch get_agent）。
    """

    def __init__(self, role: Role, llm: LLMClient | None = None):
        self.role = role
        self.llm = llm or llm_mod.get_llm()


# 角色单例缓存（role → Agent）
_agents: dict[Role, Agent] = {}


def get_agent(role: Role) -> Agent:
    """获取角色 Agent（单例缓存）"""
    if role not in _agents:
        _agents[role] = Agent(role=role)
    return _agents[role]


# 工厂函数：便捷构造各角色 Agent
def moderator() -> Agent:
    return get_agent(Role.MODERATOR)


def product_architect() -> Agent:
    return get_agent(Role.PRODUCT_ARCHITECT)


def engineer() -> Agent:
    return get_agent(Role.ENGINEER)
