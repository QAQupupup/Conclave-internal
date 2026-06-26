# 角色实例化：把角色与 Prompt 模板、LLM 绑定
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.llm import LLMClient, get_llm
from app.agents.prompts import (
    ARBITRATE,
    ARCHITECT_INTRA,
    CROSS_TEAM,
    EVIDENCE_CHECK,
    ENGINEER_INTRA,
    MODERATOR_CLARIFY,
    PRODUCE,
    render,
)
from app.models import Role


@dataclass
class Agent:
    """单个智能体：角色 + LLM"""
    role: Role
    llm: LLMClient = field(default_factory=get_llm)

    async def clarify(self, topic: str, doc_summaries: list[str]) -> dict[str, Any]:
        """主持人澄清议题"""
        prompt = render(
            MODERATOR_CLARIFY,
            topic=topic,
            doc_summaries="; ".join(doc_summaries) if doc_summaries else "无",
        )
        return await self.llm.complete(prompt, schema_hint="clarify")

    async def intra_speak(
        self, clarified_topic: str, stance: str
    ) -> dict[str, Any]:
        """队内发言：按角色选择模板"""
        if self.role == Role.ENGINEER:
            template = ENGINEER_INTRA
        else:
            template = ARCHITECT_INTRA
        prompt = render(template, clarified_topic=clarified_topic, stance=stance)
        return await self.llm.complete(prompt, schema_hint="intra_team")

    async def cross_team(self, team_conclusions: list[dict[str, Any]]) -> dict[str, Any]:
        """跨队辩论：找出冲突"""
        prompt = render(CROSS_TEAM, team_conclusions=str(team_conclusions))
        return await self.llm.complete(prompt, schema_hint="cross_team")

    async def evidence_check(
        self, conflict: dict[str, Any], evidence_chunks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """证据对照"""
        prompt = render(
            EVIDENCE_CHECK,
            conflict=str(conflict),
            evidence_chunks=str(evidence_chunks),
        )
        return await self.llm.complete(prompt, schema_hint="evidence_check")

    async def arbitrate(self, evidence_set: list[dict[str, Any]]) -> dict[str, Any]:
        """仲裁裁决"""
        prompt = render(ARBITRATE, evidence_set=str(evidence_set))
        return await self.llm.complete(prompt, schema_hint="arbitrate")

    async def produce(self, decision_record: dict[str, Any]) -> dict[str, Any]:
        """产出 PRD + OpenAPI"""
        prompt = render(PRODUCE, decision_record=str(decision_record))
        return await self.llm.complete(prompt, schema_hint="produce")


# 角色单例缓存
_agents: dict[Role, Agent] = {}


def get_agent(role: Role) -> Agent:
    """获取角色实例（单例）"""
    if role not in _agents:
        _agents[role] = Agent(role=role)
    return _agents[role]


def moderator() -> Agent:
    """主持人（兼仲裁者）"""
    return get_agent(Role.MODERATOR)


def product_architect() -> Agent:
    """产品架构师"""
    return get_agent(Role.PRODUCT_ARCHITECT)


def engineer() -> Agent:
    """工程师"""
    return get_agent(Role.ENGINEER)
