# Produce stage node + helpers: _compress_decisions_to_brief, _synthesize_evidence_for_produce, _detect_network_level, _scan_artifacts
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.compute import get_compute, build_produce_prompt, ThinkRequest
from app.agents.trace import set_current_trace
from app.events import bus, make_event
from app.models import MeetingState, MeetingStatus, Role, Stage

from ._helpers import _record_drift, _run_with_consistency, _resolve_model_for_call, _emit_agent_spoke


def _current_src_loc(depth: int = 1) -> dict[str, Any]:
    """返回当前代码位置（文件路径 + 行号），用于审计日志和降级事件"""
    import inspect
    frame = inspect.currentframe()
    if frame is None:
        return {"file": "unknown", "line": 0}
    # depth=1 表示调用 _current_src_loc 的上一层
    for _ in range(depth):
        if frame.f_back is None:
            break
        frame = frame.f_back
    return {"file": frame.f_code.co_filename, "line": frame.f_lineno}


async def _emit_progress(state: MeetingState, step: str, message: str, percent: int = 0) -> None:
    """发送 produce 阶段进度事件到前端"""
    try:
        await bus.publish(
            make_event(
                "produce.progress",
                state.meeting_id,
                {
                    "meeting_id": state.meeting_id,
                    "step": step,
                    "message": message,
                    "percent": percent,
                },
            )
        )
    except Exception:
        pass  # 进度事件失败不影响主流程


async def _emit_degradation_event(
    state: MeetingState,
    reason: str,
    empty_fields: list[str],
    result: dict[str, Any],
    confidence_before: str,
    confidence_after: str,
    call_record: dict[str, Any] | None = None,
) -> None:
    """发布 produce 阶段降级/完整性事件，供审计和重跑分析

    payload 包含：
    - 触发代码位置（file / line）
    - 触发条件（condition / empty_fields）
    - 程序逻辑（logic）
    - 当前状态（stage / deliverable_type / confidence）
    - 最近一次 LLM 调用的关键摘要（model / prompt_length / raw_response_length）
    """
    loc = _current_src_loc(depth=2)
    # 从 trace 中取出最近一次 produce 调用作为上下文
    last_call: dict[str, Any] | None = None
    if state.llm_trace and state.llm_trace.calls:
        for c in reversed(state.llm_trace.calls):
            if c.stage == "produce":
                last_call = {
                    "call_id": c.call_id,
                    "model": c.model,
                    "provider_id": c.provider_id,
                    "temperature": c.temperature,
                    "seed": c.seed,
                    "attempt": c.attempt,
                    "latency_ms": c.latency_ms,
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "total_tokens": c.total_tokens,
                    "validation_status": c.validation_status,
                    "consistency_status": c.consistency_status,
                    "prompt_length": len(c.prompt),
                    "raw_response_length": len(c.raw_response),
                    "parsed_result_keys": list(c.parsed_result.keys()) if c.parsed_result else [],
                }
                break

    payload = {
        "meeting_id": state.meeting_id,
        "stage": state.stage.value if state.stage else "produce",
        "deliverable_type": state.deliverable_type,
        "reason": reason,
        "empty_fields": empty_fields,
        "confidence_before": confidence_before,
        "confidence_after": confidence_after,
        "result_top_keys": list(result.keys()) if isinstance(result, dict) else [],
        "src_loc": loc,
        "condition": f"deliverable_type={state.deliverable_type} 且 {empty_fields} 为空",
        "logic": "produce 节点内容完整性校验：关键字段为空时阻止部署/沙箱执行，并将 confidence 从 high 降级为 low",
        "state": {
            "status": state.status.value if state.status else None,
            "stage": state.stage.value if state.stage else None,
            "confidence_flags": dict(state.confidence_flags) if state.confidence_flags else {},
            "message_count": len(state.messages),
            "claim_count": len(state.claims),
            "conflict_count": len(state.conflicts),
            "evidence_count": sum(len(es.get("assessments", [])) for es in state.evidence_set),
        },
        "last_call": last_call,
        "call_record": call_record,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await bus.publish(make_event("produce.degradation", state.meeting_id, payload))
    except Exception:
        pass


def _detect_network_level(code: str) -> str:
    """根据代码内容自动判断需要的沙箱网络级别

    L1(无网络)：默认，纯计算代码
    L2(限网)：包含 pip install，需要安装依赖
    L3(全联网)：包含 requests/urllib/httpx/http(s)://，需要访问外部 API

    判断逻辑：
    1. 有 pip install → L2（需要 pypi）
    2. 有 HTTP 库 import 或 URL → L3（需要联网）
    3. 其他 → L1（纯计算）
    """
    code_lower = code.lower()

    # L3: 外部 HTTP 请求
    http_indicators = [
        "import requests", "from requests",
        "import urllib", "from urllib",
        "import httpx", "from httpx",
        "import aiohttp", "from aiohttp",
        "http://", "https://",
        "urlopen", "requests.get", "requests.post",
    ]
    for indicator in http_indicators:
        if indicator in code_lower:
            return "L3"

    # L2: pip install
    if "pip install" in code_lower or "subprocess" in code_lower and "pip" in code_lower:
        return "L2"

    # L1: 默认纯计算
    return "L1"


def _scan_artifacts(ws_root: Path, meeting_id: str) -> list[dict[str, Any]]:
    """扫描沙箱工作区，收集产出的文件作为附件。

    ws_root 可以是 workspace 根目录（自动找 meeting_id 子目录），
    也可以已经是 meeting_id 子目录（不再重复拼接）。
    支持代码文件、文档、图片等常见产出类型。
    返回附件元数据列表，文件本体保留在 workspace 中通过 API 下载。
    """
    attachments: list[dict[str, Any]] = []
    # 支持的文件扩展名（含代码文件）
    supported_exts = {
        # 代码
        ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".vue", ".java", ".go", ".rs",
        ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".bat", ".ps1", ".sql",
        # 文档/数据
        ".md", ".txt", ".json", ".csv", ".log", ".pdf", ".doc", ".docx",
        # 图片
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    }
    # 无扩展名但重要的文件
    supported_noext = {"Dockerfile", "Makefile", "README", "LICENSE", ".env", ".gitignore"}

    # 智能判断扫描目录：如果 ws_root 末尾已经是 meeting_id，直接扫描
    if ws_root.name == meeting_id and ws_root.exists() and ws_root.is_dir():
        scan_dir = ws_root
    else:
        # 否则优先找 meeting_id 子目录，不存在则扫 ws_root 本身
        meeting_dir = ws_root / meeting_id
        scan_dir = meeting_dir if meeting_dir.exists() and meeting_dir.is_dir() else ws_root

    if not scan_dir.exists():
        return attachments

    for f in sorted(scan_dir.iterdir()):
        if not f.is_file():
            continue
        # 匹配扩展名或无扩展名的知名文件
        is_supported = (
            f.suffix.lower() in supported_exts
            or f.name in supported_noext
            or (not f.suffix and f.name.startswith("Dockerfile"))
        )
        if not is_supported:
            continue
        try:
            stat = f.stat()
        except OSError:
            continue
        # 附件"path"字段是相对于 workspace 根的路径（便于 API 下载）
        # 找到 workspace 根（即包含 meeting_id 作为其子目录的那个目录）
        if ws_root.name == meeting_id:
            rel_path = f"{meeting_id}/{f.name}"
        elif (ws_root / meeting_id).exists():
            rel_path = f"{meeting_id}/{f.name}"
        else:
            rel_path = f.name
        attachments.append({
            "filename": f.name,
            "path": rel_path,
            "size": stat.st_size,
            "ext": f.suffix.lower().lstrip(".") if f.suffix else "",
            "meeting_id": meeting_id,
        })
    return attachments


def _compress_decisions_to_brief(
    decision_record: dict,
    claims: list[dict],
    conflicts: list[dict],
    evidence_set: list[dict],
) -> dict[str, Any]:
    """将松散的仲裁结果压缩为紧凑的 action brief。

    纯确定性提取（不调 LLM），确保低延迟零额外成本。
    产出结构:
    - core_decisions: 最重要的 3-5 项决策（一行一条）
    - evidence_backing: 支撑核心决策的证据方向
    - rejected_alternatives: 被否决的方向及原因
    - action_items: 从决策推导的具体行动项
    """
    decisions = decision_record.get("decisions", [])
    adopted = decision_record.get("adopted_claims", [])

    # 核心决策：取前 5 条（LLM 已按重要性排序）
    core_decisions = []
    for d in decisions[:5]:
        if isinstance(d, dict):
            text = d.get("summary", d.get("verdict", str(d)))
        else:
            text = str(d)
        if text:
            core_decisions.append(text[:120])

    # 证据方向统计
    support_counts = {"supports": 0, "refutes": 0, "neutral": 0}
    for es in evidence_set:
        for a in es.get("assessments", []):
            direction = a.get("supports", "neutral")
            if direction in support_counts:
                support_counts[direction] += 1
    evidence_backing = (
        f"{support_counts['supports']} 条证据支持, "
        f"{support_counts['refutes']} 条反驳, "
        f"{support_counts['neutral']} 条中性"
    ) if evidence_set else "无证据数据"

    # 被否决的方向：从 conflicts 中找出未被采纳的
    rejected = []
    adopted_ids = set()
    for a in adopted:
        if isinstance(a, dict):
            adopted_ids.add(a.get("id", a.get("claim_id", "")))
        elif isinstance(a, str):
            adopted_ids.add(a)
    for c in conflicts[:5]:
        c_id = c.get("id", "")
        # 如果冲突的某一方未被采纳，记录为 rejected
        for side in c.get("sides", []):
            if isinstance(side, dict) and side.get("claim_id", "") not in adopted_ids:
                reason = side.get("rejection_reason", "证据不足或与共识冲突")
                rejected.append(f"{side.get('text', '?')[:80]} — {reason[:60]}")

    # 行动项：从 adopted_claims 提取可执行的下一步
    action_items = []
    for a in adopted[:5]:
        if isinstance(a, dict):
            next_step = a.get("next_step", a.get("action", ""))
            if next_step:
                action_items.append(next_step[:100])
            else:
                text = a.get("text", a.get("claim", ""))
                if text:
                    action_items.append(f"落实: {text[:80]}")

    return {
        "core_decisions": core_decisions,
        "evidence_backing": evidence_backing,
        "rejected_alternatives": rejected[:3],
        "action_items": action_items,
    }


def _synthesize_evidence_for_produce(state: MeetingState) -> dict[str, Any]:
    """将 evidence_set + decision_record 综合为结构化数据规格，
    供代码生成类 deliverable (code_analysis / data_science) 使用。

    返回空 dict 表示无可用证据（非代码类产出不受影响）。
    """
    if not state.evidence_set:
        return {}

    evidence_sources: list[str] = []
    evidence_quotes: list[dict] = []
    for es in state.evidence_set:
        for a in es.get("assessments", []):
            source = a.get("source", "")
            quote = a.get("quote", "")
            if source and source not in evidence_sources:
                evidence_sources.append(source)
            if quote:
                evidence_quotes.append({
                    "quote": quote[:200],
                    "source": source,
                    "supports": a.get("supports", "neutral"),
                    "conflict_id": es.get("conflict_id", ""),
                })

    decisions = (state.decision_record or {}).get("decisions", [])
    adopted = (state.decision_record or {}).get("adopted_claims", [])

    return {
        "available_data_sources": evidence_sources[:10],
        "evidence_count": len(evidence_quotes),
        "evidence_samples": evidence_quotes[:15],
        "decisions_count": len(decisions),
        "adopted_claims_count": len(adopted),
    }


async def produce_node(state: MeetingState) -> MeetingState:
    """Produce 阶段：根据 deliverable_type 切换模板，生成对应交付物

    [AUDIT-FIX P0-2] 修复：部署失败时确保 artifact 仍被保存（不返回 null）。
    节点级异常兜底由 Runner.run() 的 try/except 统一处理（P0-4）。
    """
    # 设置 trace 上下文
    set_current_trace(state.llm_trace)
    compute = get_compute()
    from app.observability.log_bus import log_bus as _lb
    # 根据产出类型选择模板
    from app.agents.prompts import get_produce_template
    template = get_produce_template(state.deliverable_type)

    # 发送进度：开始生成
    await _emit_progress(state, "llm_generate", "正在调用大模型生成产出内容，这可能需要几分钟...", 10)

    # [DATA-BRIDGE] 综合证据数据，供代码生成类产出使用
    evidence_summary = _synthesize_evidence_for_produce(state)
    if evidence_summary:
        _lb.info(
            f"produce: 证据桥接激活 — {evidence_summary['evidence_count']} 条证据, "
            f"{len(evidence_summary['available_data_sources'])} 个数据来源",
            logger="orchestrator.nodes.produce",
        )

    # 带一致性自检的 LLM 调用
    async def call_fn(anchor: str) -> dict[str, Any]:
        req = build_produce_prompt(
            state.decision_record or {},
            anchor=anchor,
            template=template,
            deliverable_type=state.deliverable_type,
            evidence_summary=evidence_summary or None,
        )
        req.model = _resolve_model_for_call(state, Role.MODERATOR.value, "produce")
        resp = await compute.think(req)
        if not resp.success:
            _lb.warning(
                f"produce: compute.think 返回失败 — {resp.error}",
                logger="orchestrator.nodes.produce",
                extra={
                    "deliverable_type": state.deliverable_type,
                    "error": resp.error,
                    "latency_ms": resp.latency_ms,
                    "stage": "produce",
                },
            )
        return resp.result

    result, confidence = await _run_with_consistency(state, "produce", call_fn)

    # 内容完整性校验：检查关键字段是否为空
    # 一致性检查只验证结果不与已锁定结论矛盾，不验证内容是否为空
    _empty_fields = []
    if state.deliverable_type == "deployable_service":
        _ds = result.get("deployable_service") or {}
        if not _ds.get("app_code"):
            _empty_fields.append("deployable_service.app_code")
    elif state.deliverable_type in ("code_analysis", "data_science"):
        _cd = result.get("code_analysis") or {}
        if not _cd.get("code"):
            _empty_fields.append("code_analysis.code")
    elif state.deliverable_type == "tested_system":
        _ts = result.get("tested_system") or {}
        if not _ts.get("main_code") and not _ts.get("test_code"):
            _empty_fields.append("tested_system.main_code/test_code")
    elif state.deliverable_type == "prd_openapi":
        if not result.get("prd") and not result.get("openapi"):
            _empty_fields.append("prd/openapi")
    if _empty_fields:
        _confidence_before = confidence
        loc = _current_src_loc(depth=1)
        _lb.warning(
            f"produce: LLM 返回内容不完整 — 空字段: {_empty_fields} "
            f"(触发位置: {loc['file']}:{loc['line']})",
            logger="orchestrator.nodes.produce",
            extra={
                "deliverable_type": state.deliverable_type,
                "empty_fields": _empty_fields,
                "src_file": loc["file"],
                "src_line": loc["line"],
                "condition": f"deliverable_type={state.deliverable_type} 且 {_empty_fields} 为空",
                "logic": "produce 节点内容完整性校验：关键字段为空时阻止部署/沙箱执行，并将 confidence 从 high 降级为 low",
                "current_state": {
                    "status": state.status.value if state.status else None,
                    "stage": state.stage.value if state.stage else None,
                    "confidence_flags": dict(state.confidence_flags) if state.confidence_flags else {},
                },
            },
        )
        if confidence == "high":
            confidence = "low"
            state.confidence_flags["produce"] = "low"
        await _emit_degradation_event(
            state=state,
            reason="produce_critical_field_empty",
            empty_fields=_empty_fields,
            result=result,
            confidence_before=_confidence_before,
            confidence_after=confidence,
        )

    _lb.info("produce: LLM 调用+一致性检查完成", logger="orchestrator.nodes.produce",
             extra={"confidence": confidence, "deliverable_type": state.deliverable_type,
                    "has_prd": bool(result.get("prd")), "openapi_len": len(result.get("openapi", ""))})

    # 发送进度：LLM生成完成，开始后续处理
    await _emit_progress(state, "llm_done", "大模型生成完成，正在处理产出内容...", 40)

    # 构建 artifact
    prd = result.get("prd", {})
    openapi = result.get("openapi", "")
    state.artifact = {
        "meeting_id": state.meeting_id,
        "deliverable_type": state.deliverable_type,
        "prd": prd,
        "openapi": openapi,
    }

    # 记录产出阶段的Agent发言
    if state.deliverable_type == "prd_openapi":
        prd_title = prd.get("title", "未命名产品")
        api_count = len(prd.get("api_endpoints", []))
        summary = (
            f"产出完成：{prd_title}\n"
            f"产品目标：{prd.get('goal', 'N/A')[:200]}\n"
            f"OpenAPI 规范：{len(openapi)} 字符"
            + (f"，包含 {api_count} 个 API 端点" if api_count else "")
        )
        await _emit_agent_spoke(state, Role.PRODUCT_ARCHITECT, Stage.PRODUCE, summary)
        if openapi:
            await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                    f"已生成 OpenAPI 规范（{len(openapi)} 字符），包含完整的接口定义和数据模型。")
    elif state.deliverable_type in ("code_analysis", "data_science"):
        code_data = result.get("code_analysis", {})
        code_len = len(code_data.get("code", ""))
        if code_len == 0:
            await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                    "代码生成失败：LLM 返回的代码为空，跳过沙箱执行。产出物可能不完整，建议重试。")
        else:
            await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                    f"代码生成完成：{code_len} 字符，准备沙箱执行验证...")
    elif state.deliverable_type == "tested_system":
        ts_data = result.get("tested_system", {})
        main_len = len(ts_data.get("main_code", ""))
        test_len = len(ts_data.get("test_code", ""))
        if main_len == 0 and test_len == 0:
            await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                    "代码生成失败：LLM 返回的主代码和测试代码均为空，跳过测试执行。产出物可能不完整，建议重试。")
        else:
            await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                    f"系统代码和测试已生成：主代码 {main_len} 字符，测试代码 {test_len} 字符，准备运行测试...")
    elif state.deliverable_type == "deployable_service":
        ds_data = result.get("deployable_service", {})
        app_len = len(ds_data.get("app_code", ""))
        if app_len == 0:
            await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                    "代码生成失败：LLM 返回的应用代码为空，跳过代码审查和部署。产出物可能不完整，建议重试。")
        else:
            await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                    f"可部署服务代码已生成：应用代码 {app_len} 字符，开始代码审查和Docker部署...")
    elif state.deliverable_type == "design_doc":
        dd = result.get("design_doc", {})
        await _emit_agent_spoke(state, Role.PRODUCT_ARCHITECT, Stage.PRODUCE,
                                f"设计文档已生成：{dd.get('title', '未命名')}")
    elif state.deliverable_type == "comprehensive":
        await _emit_agent_spoke(state, Role.MODERATOR, Stage.PRODUCE, "综合产出已生成。")
    elif state.deliverable_type == "research_report":
        await _emit_agent_spoke(state, Role.PRODUCT_ARCHITECT, Stage.PRODUCE, "研究报告已生成。")
    elif state.deliverable_type == "business_report":
        await _emit_agent_spoke(state, Role.MODERATOR, Stage.PRODUCE, "商业分析报告已生成。")
    else:
        await _emit_agent_spoke(state, Role.MODERATOR, Stage.PRODUCE,
                                f"产出物生成完成（类型：{state.deliverable_type}）。")

    # 代码执行类产出：调用沙箱执行代码
    if state.deliverable_type in ("code_analysis", "data_science"):
        code_data = result.get("code_analysis") or {}
        code = code_data.get("code", "")
        if code:
            from app.sandbox import run_python, SANDBOX_IMAGE_DATASCIENCE
            from app.orchestrator.refine_loop import refine_python_code, _summarize_task
            ws_env = os.environ.get("CONCLAVE_WORKSPACE_DIR", "")
            # [CON-24 修复] 用 config.settings.workspace_root 作为持久化工作区根
            from app.config import settings
            ws_root = Path(settings.workspace_root) / state.meeting_id
            ws_root.mkdir(parents=True, exist_ok=True)
            try:
                # code_analysis 模板更可能需要数据分析库，使用数据科学镜像
                # 根据代码内容判断网络级别
                net_level = _detect_network_level(code)
                async def _run(code, level=net_level):
                    r = await run_python(code, ws_root, timeout=30,
                                         image=SANDBOX_IMAGE_DATASCIENCE,
                                         network_level=level)
                    return r.to_dict()
                task_summary = _summarize_task("code_analysis", result)
                refined = await refine_python_code(
                    code, task_summary, _run, max_rounds=5,
                    meeting_id=state.meeting_id, stage="produce",
                    detected_level=net_level,
                )
                # 网络授权获批后用新级别重试
                if refined.get("need_retry_with_level"):
                    new_level = refined["need_retry_with_level"]
                    _lb.info(f"produce: 网络授权获批 level={new_level}，重新执行代码",
                             logger="orchestrator.nodes.produce")
                    async def _run_approved(code):
                        r = await run_python(code, ws_root, timeout=30,
                                             image=SANDBOX_IMAGE_DATASCIENCE,
                                             network_level=new_level)
                        return r.to_dict()
                    refined = await refine_python_code(
                        refined["code"], task_summary, _run_approved, max_rounds=3,
                        meeting_id=state.meeting_id, stage="produce",
                        detected_level=new_level,
                    )
                code_data["code"] = refined["code"]
                state.artifact["code_analysis"] = code_data
                state.artifact["execution"] = refined["execution"]
                state.artifact["refine_info"] = {
                    "rounds_used": refined["rounds_used"],
                    "success": refined["success"],
                }
                if refined.get("net_auth"):
                    state.artifact["net_auth"] = refined["net_auth"]
                # 记录代码执行结果消息
                exec_result = refined.get("execution", {})
                if exec_result.get("exit_code") == 0:
                    out_preview = (exec_result.get("stdout", "") or "")[:300]
                    await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                            f"代码执行成功。输出预览：\n{out_preview}")
                else:
                    err_preview = (exec_result.get("stderr", "") or exec_result.get("error", ""))[:300]
                    await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                            f"代码执行遇到问题：{err_preview}")
            except Exception as e:
                state.artifact["code_analysis"] = code_data
                state.artifact["execution"] = {"error": str(e), "exit_code": -1}
                await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                        f"代码执行异常：{str(e)[:200]}")
        else:
            state.artifact["code_analysis"] = code_data

    elif state.deliverable_type == "tested_system":
        ts_data = result.get("tested_system") or {}
        main_code = ts_data.get("main_code", "")
        test_code = ts_data.get("test_code", "")
        if test_code:
            from app.sandbox import run_command, SANDBOX_IMAGE_DATASCIENCE
            from app.orchestrator.refine_loop import refine_python_code, _summarize_task
            # [CON-24 修复] 用持久化工作区
            from app.config import settings
            ws_root = Path(settings.workspace_root) / state.meeting_id
            ws_root.mkdir(parents=True, exist_ok=True)
            ws_root.mkdir(parents=True, exist_ok=True)
            try:
                # 把代码写入工作区
                test_file = ws_root / "test_generated.py"
                test_file.write_text(test_code, encoding="utf-8")
                main_file = ws_root / "main_generated.py"
                if main_code:
                    main_file.write_text(main_code, encoding="utf-8")
                # tested_system 模板更可能需要数据分析库，使用数据科学镜像
                net_level = _detect_network_level(test_code)
                async def _run_tests(code, level=net_level):
                    test_file.write_text(code, encoding="utf-8")
                    r = await run_command(
                        "python -m pytest test_generated.py -v",
                        ws_root, timeout=30, image=SANDBOX_IMAGE_DATASCIENCE,
                        network_level=level,
                    )
                    return r.to_dict()
                task_summary = _summarize_task("tested_system", result)
                refined = await refine_python_code(
                    test_code, task_summary, _run_tests, max_rounds=5,
                    meeting_id=state.meeting_id, stage="produce",
                    detected_level=net_level,
                )
                # 网络授权获批后用新级别重试
                if refined.get("need_retry_with_level"):
                    new_level = refined["need_retry_with_level"]
                    _lb.info(f"produce: 网络授权获批 level={new_level}，重新执行测试",
                             logger="orchestrator.nodes.produce")
                    async def _run_tests_approved(code):
                        test_file.write_text(code, encoding="utf-8")
                        r = await run_command(
                            "python -m pytest test_generated.py -v",
                            ws_root, timeout=30, image=SANDBOX_IMAGE_DATASCIENCE,
                            network_level=new_level,
                        )
                        return r.to_dict()
                    refined = await refine_python_code(
                        refined["code"], task_summary, _run_tests_approved, max_rounds=3,
                        meeting_id=state.meeting_id, stage="produce",
                        detected_level=new_level,
                    )
                ts_data["test_code"] = refined["code"]
                state.artifact["tested_system"] = ts_data
                state.artifact["execution"] = refined["execution"]
                state.artifact["refine_info"] = {
                    "rounds_used": refined["rounds_used"],
                    "success": refined["success"],
                }
                if refined.get("net_auth"):
                    state.artifact["net_auth"] = refined["net_auth"]
                # 记录测试执行结果消息
                test_result = refined.get("execution", {})
                if refined.get("success") and test_result.get("exit_code") == 0:
                    out_preview = (test_result.get("stdout", "") or "")[:300]
                    await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                            f"测试全部通过（{refined.get('rounds_used', 1)}轮修复）。结果预览：\n{out_preview}")
                else:
                    err_preview = (test_result.get("stderr", "") or test_result.get("error", ""))[:300]
                    await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                            f"测试执行完成，但存在问题：{err_preview}")
            except Exception as e:
                state.artifact["tested_system"] = ts_data
                state.artifact["execution"] = {"error": str(e), "exit_code": -1}
                await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                        f"测试执行异常：{str(e)[:200]}")
        else:
            state.artifact["tested_system"] = ts_data

    elif state.deliverable_type == "deployable_service":
        ds_data = result.get("deployable_service") or {}
        app_code = ds_data.get("app_code", "")
        requirements_txt = ds_data.get("requirements_txt", "")
        dockerfile_content = ds_data.get("dockerfile", "")
        docker_compose_content = ds_data.get("docker_compose", "")
        readme_content = ds_data.get("readme", "")
        credentials = ds_data.get("credentials") or {}
        service_port = ds_data.get("port", 8000)
        frontend_files = ds_data.get("frontend_files") or {}
        if app_code:
            from app.config import settings
            ws_root = Path(settings.workspace_root) / state.meeting_id
            ws_root.mkdir(parents=True, exist_ok=True)

            # === 代码 Review + BugFix 循环 ===
            # [AUDIT-FIX P0-3] 修复：增加连续修复失败计数器，超过阈值提前退出循环
            review_rounds = 0
            max_review_rounds = 3
            max_consecutive_fix_failures = 3  # 连续修复失败上限
            consecutive_fix_failures = 0
            review_passed = False
            review_summary = ""
            code_files = {
                "app.py": app_code,
                "requirements.txt": requirements_txt,
                "Dockerfile": dockerfile_content,
                "docker-compose.yml": docker_compose_content,
            }

            await _emit_progress(state, "code_review", "正在进行代码审查和修复...", 50)

            for review_rounds in range(1, max_review_rounds + 1):
                _lb.info(f"produce: 代码审查第{review_rounds}轮", logger="orchestrator.nodes.produce")
                # 调用LLM做代码审查
                from app.agents.prompts import CODE_REVIEW_PROMPT, CODE_FIX_PROMPT
                from app.agents.bug_patterns import format_bug_patterns_for_prompt
                bug_patterns = format_bug_patterns_for_prompt()

                review_prompt = CODE_REVIEW_PROMPT.format(
                    bug_patterns=bug_patterns,
                    app_code=code_files["app.py"],
                    requirements_txt=code_files["requirements.txt"],
                    dockerfile=code_files["Dockerfile"],
                    docker_compose=code_files["docker-compose.yml"],
                )
                review_req = ThinkRequest(
                    agent_role=Role.ENGINEER.value,
                    stage="review",
                    prompt=review_prompt,
                    schema_hint="code_review",
                    model=_resolve_model_for_call(state, Role.ENGINEER.value, "review"),
                )
                # 为review阶段注入Skills（deliverable_quality, code_conventions等）
                try:
                    from app.agents.skills import format_skills_for_prompt
                    skills_text = format_skills_for_prompt(stage="review", deliverable_type="deployable_service", role=Role.ENGINEER.value)
                    if skills_text:
                        review_req.prompt = review_req.prompt + "\n\n" + skills_text
                except Exception:
                    pass
                review_resp = await compute.think(review_req)
                review_result = review_resp.result if hasattr(review_resp, 'result') else {}
                if isinstance(review_result, dict):
                    issues = review_result.get("issues", [])
                    review_summary = review_result.get("summary", "")
                    critical_high = [i for i in issues if i.get("severity") in ("critical", "high")]
                    # [AUDIT-FIX P2] 审查一致性：综合 passed 字段和 critical/high 问题判断
                    # 避免 LLM 输出 passed=true 但 issues 中含 critical 的矛盾
                    passed_from_llm = review_result.get("passed", False)
                    if not critical_high:
                        # [AUDIT-FIX P2] 无 critical/high 问题即通过，并记录 LLM passed 字段是否一致
                        review_passed = True
                        if not passed_from_llm:
                            _lb.warning("produce: 审查 passed=false 但无 critical/high 问题，按问题判定为通过",
                                        logger="orchestrator.nodes.produce")
                        _lb.info(f"produce: 代码审查通过（第{review_rounds}轮，{len(issues)}个低/中级别问题）",
                                 logger="orchestrator.nodes.produce")
                        # 记录审查通过消息
                        await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                                f"代码审查第{review_rounds}轮通过（{len(issues)}个低/中级别问题，不影响部署）")
                        break

                    # 有critical/high问题，修复
                    _lb.info(f"produce: 发现{len(critical_high)}个严重问题，开始修复",
                             logger="orchestrator.nodes.produce",
                             extra={"issues": [i.get("description", "")[:100] for i in critical_high]})
                    for issue in critical_high:
                        file_to_fix = issue.get("file", "app.py")
                        file_key_map = {"app.py": "app.py", "requirements.txt": "requirements.txt",
                                        "Dockerfile": "Dockerfile", "docker-compose.yml": "docker-compose.yml"}
                        fkey = file_key_map.get(file_to_fix, "app.py")
                        original = code_files[fkey]
                        issues_text = f"- [{issue.get('severity','high')}] {issue.get('description','')}\n  修复建议: {issue.get('fix','')}"
                        fix_prompt = CODE_FIX_PROMPT.format(
                            original_code=original,
                            issues_text=issues_text,
                            bug_patterns=bug_patterns,
                            file_to_fix=fkey,
                        )
                        fix_req = ThinkRequest(
                            agent_role=Role.ENGINEER.value,
                            stage="bugfix",
                            prompt=fix_prompt,
                            schema_hint="bugfix",  # [AUDIT-FIX P1-2] 修复：补全 schema_hint 确保 trace 记录正确 stage
                            model=_resolve_model_for_call(state, Role.ENGINEER.value, "bugfix"),
                        )
                        # 为bugfix阶段注入Skills（code_conventions等）
                        try:
                            from app.agents.skills import format_skills_for_prompt
                            skills_text = format_skills_for_prompt(stage="bugfix", deliverable_type="deployable_service", role=Role.ENGINEER.value)
                            if skills_text:
                                fix_req.prompt = fix_req.prompt + "\n\n" + skills_text
                        except Exception:
                            pass
                        fix_resp = await compute.think(fix_req)
                        # 正确解析LLM返回的JSON：可能是 {"fixed_code": "..."} 格式，也可能直接是代码字符串
                        fixed_code = ""
                        if isinstance(fix_resp.result, dict):
                            fixed_code = str(fix_resp.result.get("fixed_code", "") or fix_resp.result.get("code", "") or "")
                            # 如果dict中没有fixed_code字段，尝试取第一个字符串值
                            if not fixed_code:
                                for v in fix_resp.result.values():
                                    if isinstance(v, str) and len(v) > 20:
                                        fixed_code = v
                                        break
                        elif isinstance(fix_resp.result, str):
                            fixed_code = fix_resp.result
                        else:
                            fixed_code = str(fix_resp.result)
                        # 清理可能的markdown代码块标记
                        fixed_code = fixed_code.strip()
                        if fixed_code.startswith("```"):
                            lines = fixed_code.split("\n")
                            # 去掉第一行```language和最后一行```
                            lines = lines[1:]
                            while lines and lines[-1].strip().startswith("```"):
                                lines = lines[:-1]
                            fixed_code = "\n".join(lines)
                        # [AUDIT-FIX P0-1] 修复：用 ast.parse 校验 Python 代码有效性，
                        # 替代原来粗暴的 startswith("{") 检查（会误拒以 "{" 开头的合法代码）
                        # [AUDIT-FIX P0-3] 修复：增加连续失败计数，超过阈值时退出循环
                        _fix_ok = False
                        if not fixed_code:
                            _lb.warning(f"produce: 修复 {fkey} 返回空代码，保留原版本",
                                        logger="orchestrator.nodes.produce")
                        elif fkey.endswith(".py"):
                            import ast as _ast
                            try:
                                _ast.parse(fixed_code)
                                code_files[fkey] = fixed_code
                                _fix_ok = True
                            except SyntaxError as _se:
                                _lb.warning(f"produce: 修复 {fkey} 代码有语法错误 ({_se})，保留原版本",
                                            logger="orchestrator.nodes.produce")
                        else:
                            # 非 .py 文件（requirements.txt, Dockerfile 等）：非空即接受
                            code_files[fkey] = fixed_code
                            _fix_ok = True
                        # P0-3: 连续失败计数
                        if _fix_ok:
                            consecutive_fix_failures = 0
                        else:
                            consecutive_fix_failures += 1
                            if consecutive_fix_failures >= max_consecutive_fix_failures:
                                _lb.warning(
                                    f"produce: 连续 {consecutive_fix_failures} 次修复失败，"
                                    f"跳过剩余问题并在本轮终止审查循环",
                                    logger="orchestrator.nodes.produce")
                                review_passed = False
                                break
                else:
                    review_passed = True  # 审查返回非JSON，跳过
                    break

            # 更新代码
            app_code = code_files["app.py"]
            requirements_txt = code_files["requirements.txt"]
            dockerfile_content = code_files["Dockerfile"]
            docker_compose_content = code_files["docker-compose.yml"]

            # 写入所有部署文件到工作区
            (ws_root / "app.py").write_text(app_code, encoding="utf-8")
            if requirements_txt:
                (ws_root / "requirements.txt").write_text(requirements_txt, encoding="utf-8")
            if dockerfile_content:
                (ws_root / "Dockerfile").write_text(dockerfile_content, encoding="utf-8")
            if docker_compose_content:
                (ws_root / "docker-compose.yml").write_text(docker_compose_content, encoding="utf-8")
            # 写入前端文件
            if frontend_files:
                frontend_dir = ws_root / "frontend"
                frontend_dir.mkdir(parents=True, exist_ok=True)
                for fname, fcontent in frontend_files.items():
                    if not isinstance(fcontent, str):
                        continue
                    # 安全路径：仅允许 index.html / style.css 等简单文件名
                    safe_name = Path(fname).name
                    if safe_name in ("index.html", "style.css", "app.js"):
                        (frontend_dir / safe_name).write_text(fcontent, encoding="utf-8")
                _lb.info(
                    f"produce: 已写入 {len(frontend_files)} 个前端文件到 frontend/",
                    logger="orchestrator.nodes.produce",
                    extra={"meeting_id": state.meeting_id, "files": list(frontend_files.keys())},
                )
            # 写入 README
            if readme_content:
                (ws_root / "README.md").write_text(readme_content, encoding="utf-8")
            else:
                default_readme = f"""# {ds_data.get('title', 'Deployable Service')}

{ds_data.get('description', '')}

## 快速开始
```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port {service_port}
```
服务端口: {service_port}
"""
                (ws_root / "README.md").write_text(default_readme, encoding="utf-8")

            # 更新ds_data中的代码为修复后的版本
            ds_data["app_code"] = app_code
            ds_data["requirements_txt"] = requirements_txt
            ds_data["dockerfile"] = dockerfile_content
            ds_data["docker_compose"] = docker_compose_content
            ds_data["frontend_files"] = frontend_files
            state.artifact["deployable_service"] = ds_data
            state.artifact["deployment_dir"] = str(ws_root)
            state.artifact["review"] = {
                "rounds": review_rounds,
                "passed": review_passed,
                "summary": review_summary,
            }

            # === 沙箱自动部署 ===
            deployment_info = {}
            try:
                from app.sandbox import deploy_service
                _lb.info("produce: 开始沙箱部署服务...", logger="orchestrator.nodes.produce")
                await _emit_progress(state, "deploying", "正在Docker沙箱中部署服务，这可能需要1-2分钟...", 75)

                # 确保有/health端点 - 如果app_code中没有，自动注入
                if "/health" not in app_code and '"/health"' not in app_code and "'/health'" not in app_code:
                    health_code = """

@app.get("/health")
def health():
    return {"status": "ok"}
"""
                    # 注入到 if __name__ == "__main__" 之前
                    if 'if __name__' in app_code:
                        app_code = app_code.replace('if __name__', health_code + '\nif __name__')
                        (ws_root / "app.py").write_text(app_code, encoding="utf-8")

                deploy_result = await deploy_service(
                    meeting_id=state.meeting_id,
                    workspace_root=settings.workspace_root,
                    container_port=service_port,
                    health_path="/health",
                    wait_seconds=300,
                    credentials=credentials if credentials else None,
                    env_vars={"SECRET_KEY": "dev-conclave-secret-change-me"},
                )
                deployment_info = deploy_result.to_dict()
                _lb.info(
                    f"produce: 服务部署{'成功' if deploy_result.ok else '失败'}",
                    logger="orchestrator.nodes.produce",
                    extra={"access_url": deploy_result.access_url, "ok": deploy_result.ok},
                )

                # 发布服务部署事件
                await bus.publish(make_event(
                    "service.deployed" if deploy_result.ok else "service.deploy_failed",
                    state.meeting_id,
                    deployment_info,
                ))
            except Exception as deploy_err:
                _lb.error(f"produce: 服务部署异常: {deploy_err}", logger="orchestrator.nodes.produce")
                deployment_info = {"ok": False, "error": str(deploy_err)}

            state.artifact["deployment"] = deployment_info
            state.artifact["execution"] = {
                "exit_code": 0 if review_passed else 1,
                "stdout": (
                    f"代码审查: {review_rounds}轮, {'通过' if review_passed else '存在未修复问题'}\n"
                    f"部署文件: app.py / requirements.txt / Dockerfile / docker-compose.yml / README.md\n"
                    f"服务部署: {'成功 ✅ ' + deployment_info.get('access_url', '') if deployment_info.get('ok') else '失败: ' + deployment_info.get('error', '未知错误')}"
                ),
                "stderr": deployment_info.get("logs", "") if not deployment_info.get("ok") else "",
                "sandboxed": True,
                "files": ["app.py", "requirements.txt", "Dockerfile", "docker-compose.yml", "README.md"],
            }
            # 记录部署结果消息
            if deployment_info.get("ok"):
                url = deployment_info.get("access_url", "")
                await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                        f"服务部署成功！访问地址：{url}")
            else:
                err = deployment_info.get("error", "未知错误")
                await _emit_agent_spoke(state, Role.ENGINEER, Stage.PRODUCE,
                                        f"服务部署失败：{err}")
        else:
            state.artifact["deployable_service"] = ds_data
    else:
        # 其他类型直接存入 artifact
        for key in ["design_doc", "comprehensive", "research_report", "business_report"]:
            if key in result:
                state.artifact[key] = result[key]

    # 附件扫描：所有代码/服务类产出都扫描工作区收集产出文件
    if state.deliverable_type in ("code_analysis", "tested_system", "deployable_service"):
        # [CON-24 修复] 用持久化工作区
        from app.config import settings
        ws_root = Path(settings.workspace_root) / state.meeting_id
        attachments = _scan_artifacts(ws_root, state.meeting_id)
        if attachments:
            state.artifact["attachments"] = attachments
            _lb.info(f"produce: 扫描到 {len(attachments)} 个附件文件",
                     logger="orchestrator.nodes.produce",
                     extra={"attachment_files": [a["filename"] for a in attachments]})

    # 第2层：锁定 produce 结论
    state.conclusion_chain.lock("produce", state.artifact)
    # 第5层：记录置信度
    state.confidence_flags["produce"] = confidence
    _lb.info("produce: artifact 已构造, 锁定结论完成", logger="orchestrator.nodes.produce",
             extra={"prd_title": prd.get("title", "?"), "openapi_len": len(openapi),
                    "deliverable_type": state.deliverable_type})
    # 发布 artifact.generated 事件
    await bus.publish(
        make_event(
            "artifact.generated",
            state.meeting_id,
            {
                "meeting_id": state.meeting_id,
                "deliverable_type": state.deliverable_type,
                "prd": prd,
                "openapi": openapi,
            },
        )
    )
    _lb.info("produce: artifact.generated 事件已发布", logger="orchestrator.nodes.produce")
    # 发送进度：产出完成
    await _emit_progress(state, "done", "产出物生成完成！", 100)
    # 产物阶段也做一次漂移检查（针对产出文本）
    artifact_text = json.dumps(state.artifact, ensure_ascii=False, default=str)
    _record_drift(state, Role.MODERATOR, Stage.PRODUCE, artifact_text)
    _lb.info("produce: 漂移检查完成", logger="orchestrator.nodes.produce")
    # 终态
    state.stage = Stage.PRODUCE
    state.status = MeetingStatus.DONE
    _lb.info("produce: 状态已设为 DONE", logger="orchestrator.nodes.produce")

    # LLM 降级检测：如果有阶段使用了 StubLLM 兜底，发 warning 事件
    fallback_stages = [s for s, flag in state.confidence_flags.items() if flag == "fallback"]
    if fallback_stages:
        await bus.publish(make_event(
            "meeting.fallback_warning",
            state.meeting_id,
            {
                "fallback_stages": fallback_stages,
                "message": f"以下阶段使用了降级数据（非真实 LLM 输出）：{', '.join(fallback_stages)}。产出物可能不可靠，请谨慎参考。",
                "severity": "warning",
            },
        ))
        _lb.warning(
            f"会议完成但有 {len(fallback_stages)} 个阶段降级：{fallback_stages}",
            logger="orchestrator.nodes.produce",
        )
    # 迭代二：会议结束后触发记忆提取（失败不影响主流程）
    from app.memory.profile import trigger_extraction
    trigger_extraction(state)
    _lb.info("produce: 记忆提取完成, 准备返回", logger="orchestrator.nodes.produce")
    # [FEEDBACK] Agent 反馈闭环：评估每个 Agent 的判断质量，写回画像供迭代
    try:
        from app.agents.feedback import evaluate_agents
        evaluations = evaluate_agents(state)
        if evaluations:
            _lb.info(
                f"produce: Agent 评估完成 — {len(evaluations)} 个角色, "
                f"top={max(evaluations.items(), key=lambda x: x[1]['overall_score'])[0]}",
                logger="orchestrator.nodes.produce",
            )
    except Exception as fb_err:
        _lb.warning(f"produce: Agent 评估失败（不影响主流程）: {fb_err}",
                     logger="orchestrator.nodes.produce")
    return state
