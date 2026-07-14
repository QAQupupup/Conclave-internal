# 成本可观测性：统一追踪 LLM 调用和工具调用的成本
#
# 设计原则（Claude 交叉评审共识）：
# - 单一 trace_id 在会议开始时生成，贯穿每次调用
# - 扁平日志 schema：{trace_id, node, tool_name, cost, tokens, latency_ms}
# - 四个层级（meeting / node / tool / call）都是对同一张表的 GROUP BY
# - 与现有 CallTrace/LLMCallRecord 互补：CallTrace 记录 LLM 调用详情，
#   CostTracker 记录所有调用（LLM + 工具）的统一成本视图
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.context import get_request_id, get_meeting_id, get_runner_session_id


@dataclass
class CostRecord:
    """单次调用的成本记录（扁平 schema）

    四个聚合层级都是对此记录的 GROUP BY：
    - meeting 级：GROUP BY trace_id
    - node 级：GROUP BY trace_id, node
    - tool 级：GROUP BY trace_id, tool_name
    - call 级：每条记录即一次调用
    """
    trace_id: str = ""           # = runner_session_id，贯穿整个会议运行
    meeting_id: str = ""
    request_id: str = ""
    agent_role: str = ""         # 发起调用的 Agent 角色
    node: str = ""               # pipeline 阶段名（clarify / intra_team / ...）
    tool_name: str = ""          # "llm" | "web_search" | "browser.goto" | "browser.click" | ...
    cost_usd: float = 0.0        # 估算成本（美元）
    input_tokens: int = 0        # 输入 tokens（仅 LLM 有值）
    output_tokens: int = 0       # 输出 tokens（仅 LLM 有值）
    total_tokens: int = 0        # 总 tokens
    latency_ms: int = 0          # 调用延迟
    timestamp: str = ""
    status: str = "ok"           # "ok" | "error" | "fallback"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_log_dict(self) -> dict[str, Any]:
        """转换为 LogBus 兼容的 flat dict"""
        return {
            "trace_id": self.trace_id,
            "meeting_id": self.meeting_id,
            "request_id": self.request_id,
            "agent_role": self.agent_role,
            "node": self.node,
            "tool_name": self.tool_name,
            "cost_usd": round(self.cost_usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "status": self.status,
            **self.extra,
        }


# ---------- LLM 成本估算表（每百万 tokens 美元） ----------
# 来源：各模型官方定价页，定期更新
_LLM_PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    # DeepSeek
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    # Qwen 全系已排除：不支持 response_format: json_object，与 Conclave 不兼容
    # 默认（未知模型）
    "_default": {"input": 1.00, "output": 3.00},
}


def estimate_llm_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """根据模型和 tokens 估算 LLM 调用成本（美元）

    定价表以"每百万 tokens 美元"为单位。
    优先使用 llm_providers.MODEL_PRICING（覆盖SiliconFlow全模型），
    回退到本地 _LLM_PRICING 表。
    """
    # 优先使用 llm_providers 的完整定价表（人民币），换算为美元
    try:
        from app.llm_providers import get_model_pricing
        p = get_model_pricing(model)
        if p and p.get("input") is not None:
            input_price_per_m = p["input"]
            output_price_per_m = p["output"]
            currency = p.get("currency", "CNY")
            rate = 1.0 / 7.2 if currency == "CNY" else 1.0  # RMB→USD近似汇率
            cost = (input_tokens / 1_000_000) * input_price_per_m * rate + \
                   (output_tokens / 1_000_000) * output_price_per_m * rate
            return round(cost, 6)
    except Exception:
        pass
    # 回退：本地美元定价表
    pricing = _LLM_PRICING.get(model, _LLM_PRICING["_default"])
    cost = (input_tokens / 1_000_000) * pricing["input"] + \
           (output_tokens / 1_000_000) * pricing["output"]
    return round(cost, 6)


# ---------- CostTracker ----------

class CostTracker:
    """成本追踪器：记录所有调用的成本，汇总并 emit 到 LogBus

    使用方式：
        tracker = get_cost_tracker()
        tracker.record_llm(node="evidence_check", model="deepseek-chat",
                          input_tokens=1200, output_tokens=800, latency_ms=2300)
        tracker.record_tool(node="evidence_check", tool_name="web_search",
                          latency_ms=5000)
        summary = tracker.summary()

    设计说明：
    - 全局单例，用于运维面板聚合统计
    - 记录数有上限（MAX_RECORDS），超过自动裁剪最旧记录，防止内存泄漏
    - summary() 支持按 meeting_id 过滤
    """
    MAX_RECORDS: int = 10000  # 最多保留 1 万条记录（约覆盖数十次会议）

    def __init__(self) -> None:
        self._records: list[CostRecord] = []
        self._lock = asyncio.Lock()

    def _get_trace_id(self) -> str:
        """获取当前上下文的 trace_id（复用 runner_session_id）"""
        return get_runner_session_id()

    def record_llm(
        self,
        node: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        status: str = "ok",
        extra: dict[str, Any] | None = None,
        agent_role: str = "",
    ) -> CostRecord:
        """记录一次 LLM 调用成本"""
        from app.context import get_agent_role
        cost = estimate_llm_cost(model, input_tokens, output_tokens)
        record = CostRecord(
            trace_id=self._get_trace_id(),
            meeting_id=get_meeting_id(),
            request_id=get_request_id(),
            agent_role=agent_role or get_agent_role(),
            node=node,
            tool_name="llm",
            cost_usd=cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=status,
            extra={"model": model, **(extra or {})},
        )
        self._records.append(record)
        # 裁剪超过上限的旧记录（防止内存泄漏）
        if len(self._records) > self.MAX_RECORDS:
            # 移除最旧的记录
            excess = len(self._records) - self.MAX_RECORDS
            del self._records[:excess]
        self._emit(record)
        return record

    def record_tool(
        self,
        node: str,
        tool_name: str,
        latency_ms: int,
        cost_usd: float = 0.0,
        status: str = "ok",
        extra: dict[str, Any] | None = None,
    ) -> CostRecord:
        """记录一次工具调用成本（web_search / browser 操作等）"""
        record = CostRecord(
            trace_id=self._get_trace_id(),
            meeting_id=get_meeting_id(),
            request_id=get_request_id(),
            node=node,
            tool_name=tool_name,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=status,
            extra=extra or {},
        )
        self._records.append(record)
        # 裁剪超过上限的旧记录
        if len(self._records) > self.MAX_RECORDS:
            excess = len(self._records) - self.MAX_RECORDS
            del self._records[:excess]
        self._emit(record)
        return record

    def _emit(self, record: CostRecord) -> None:
        """将成本记录 emit 到 LogBus（旁路，不影响主流程）"""
        try:
            from app.observability.log_bus import log_bus
            log_bus.emit(
                "INFO",
                f"cost: {record.tool_name} ({record.node})",
                logger="app.observability.cost_tracker",
                extra=record.to_log_dict(),
            )
        except Exception:
            pass

        # 异步持久化到数据库（best-effort，不阻塞主流程）
        try:
            self._enqueue_db_flush(record)
        except Exception:
            pass

    def _enqueue_db_flush(self, record: CostRecord) -> None:
        """将记录加入异步刷盘队列，后台批量写入数据库"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_flush_record_to_db(record))
        except RuntimeError:
            pass  # 无事件循环时跳过

    def summary(self) -> dict[str, Any]:
        """返回成本汇总（按 node / tool 聚合）"""
        total_cost = sum(r.cost_usd for r in self._records)
        total_tokens = sum(r.total_tokens for r in self._records)
        total_llm_tokens = sum(r.total_tokens for r in self._records if r.tool_name == "llm")
        total_calls = len(self._records)
        llm_calls = sum(1 for r in self._records if r.tool_name == "llm")
        tool_calls = total_calls - llm_calls
        errors = sum(1 for r in self._records if r.status == "error")

        # 按 node 聚合
        by_node: dict[str, dict[str, Any]] = {}
        for r in self._records:
            n = by_node.setdefault(r.node, {"calls": 0, "cost_usd": 0.0, "tokens": 0, "latency_ms": 0})
            n["calls"] += 1
            n["cost_usd"] += r.cost_usd
            n["tokens"] += r.total_tokens
            n["latency_ms"] += r.latency_ms

        # 按 tool 聚合
        by_tool: dict[str, dict[str, Any]] = {}
        for r in self._records:
            t = by_tool.setdefault(r.tool_name, {"calls": 0, "cost_usd": 0.0, "tokens": 0, "latency_ms": 0})
            t["calls"] += 1
            t["cost_usd"] += r.cost_usd
            t["tokens"] += r.total_tokens
            t["latency_ms"] += r.latency_ms

        return {
            "trace_id": self._get_trace_id(),
            "total_calls": total_calls,
            "llm_calls": llm_calls,
            "tool_calls": tool_calls,
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
            "total_llm_tokens": total_llm_tokens,
            "error_count": errors,
            "by_node": by_node,
            "by_tool": by_tool,
        }

    def clear(self) -> None:
        """清空记录（新会议运行前调用）"""
        self._records.clear()


# ---------- 进程级单例 ----------
_cost_tracker: CostTracker | None = None


def get_cost_tracker() -> CostTracker:
    """获取全局 CostTracker 单例"""
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker()
    return _cost_tracker


def reset_cost_tracker() -> None:
    """重置 CostTracker（测试用）"""
    global _cost_tracker
    if _cost_tracker is not None:
        _cost_tracker.clear()
    _cost_tracker = None


# ---------- 异步数据库刷盘 ----------

async def _flush_record_to_db(record: CostRecord) -> None:
    """将单条成本记录异步写入数据库（best-effort，失败不重试）"""
    try:
        from datetime import datetime, timezone
        from app.db.engine import async_session_factory
        from app.db.models import CostRecordModel

        async with async_session_factory() as session:
            # 解析 provider/model 从 extra
            model = record.extra.get("model", "") if record.extra else ""
            provider = record.extra.get("provider", "") if record.extra else ""

            db_record = CostRecordModel(
                meeting_id=record.meeting_id or None,
                stage=record.node,
                node="llm" if record.tool_name == "llm" else "tool",
                role=record.agent_role,
                provider=provider,
                model=model,
                tool_name=record.tool_name,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                cost_usd=record.cost_usd,
                latency_ms=record.latency_ms,
                status=record.status,
                error="",
                created_at=datetime.fromisoformat(record.timestamp) if record.timestamp else datetime.now(timezone.utc),
            )
            session.add(db_record)
            await session.commit()
    except Exception as exc:
        import logging
        logging.getLogger("observability.cost_tracker").warning(
            f"成本记录写入数据库失败: {exc}",
            extra={"error": str(exc), "record": record.model_dump(mode="json") if hasattr(record, "model_dump") else str(record)},
        )
        # 成本持久化失败不影响主流程
