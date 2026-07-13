# LLM 模型中心：Provider 注册表、模型发现、余额查询、定价表
#
# 设计目标：
# 1. 支持多 LLM 厂商（SiliconFlow / DeepSeek / OpenAI / OpenRouter / 自定义）
# 2. 运行时查询可用模型列表和账户余额
# 3. 支持会议级别的模型切换和 BYOK（用户自带 API Key）
# 4. 维护定价表用于成本估算
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("llm.providers")


# ========== Provider 定义 ==========

@dataclass
class ProviderConfig:
    """LLM 厂商配置"""
    id: str                           # 唯一ID，如 "siliconflow"
    name: str                         # 人类可读名称
    base_url: str                     # API Base URL
    api_key: str = ""                 # 默认API Key（从环境变量读取）
    balance_endpoint: str = ""        # 余额查询路径（相对于base_url），空=不支持
    models_endpoint: str = "/models"  # 模型列表路径
    balance_response_path: tuple[str, ...] = ()  # 余额字段在JSON中的路径，如 ("data","totalBalance")
    models_are_openai_compatible: bool = True
    supports_custom_key: bool = True  # 是否支持用户自带Key
    pricing_note: str = ""            # 定价说明


# 内置 Provider 注册表
PROVIDERS: dict[str, ProviderConfig] = {
    "siliconflow": ProviderConfig(
        id="siliconflow",
        name="硅基流动 SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        api_key=settings.llm_api_key if "siliconflow" in (settings.llm_base_url or "") else "",
        balance_endpoint="/user/info",
        balance_response_path=("data", "totalBalance"),
        supports_custom_key=True,
        pricing_note="按百万Token计费，部分小模型免费",
    ),
    "deepseek": ProviderConfig(
        id="deepseek",
        name="DeepSeek 官方",
        base_url="https://api.deepseek.com/v1",
        balance_endpoint="/user/balance",
        balance_response_path=("balance_infos", 0, "total_balance"),
        supports_custom_key=True,
        pricing_note="DeepSeek-V3 输入¥2/百万，输出¥8/百万",
    ),
    "openai": ProviderConfig(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        balance_endpoint="",  # OpenAI 无公开余额API
        supports_custom_key=True,
        pricing_note="GPT-4o 输入$2.5/百万，输出$10/百万",
    ),
    "openrouter": ProviderConfig(
        id="openrouter",
        name="OpenRouter (多模型聚合)",
        base_url="https://openrouter.ai/api/v1",
        balance_endpoint="/auth/key",  # 需要 GET 带 Authorization
        balance_response_path=("data", "limit_remaining"),
        supports_custom_key=True,
        pricing_note="返回模型列表含定价信息",
    ),
    "custom": ProviderConfig(
        id="custom",
        name="自定义 (OpenAI兼容)",
        base_url="",
        balance_endpoint="",
        models_endpoint="/models",
        supports_custom_key=True,
        pricing_note="任意OpenAI兼容接口",
    ),
}

# 初始化默认 provider 的 API key
if settings.llm_base_url and settings.llm_api_key:
    for pid, p in PROVIDERS.items():
        if pid != "custom" and p.base_url.rstrip("/") in settings.llm_base_url:
            p.api_key = settings.llm_api_key
            break
    else:
        # 不在已知provider中，归为custom
        PROVIDERS["custom"].base_url = settings.llm_base_url
        PROVIDERS["custom"].api_key = settings.llm_api_key


# ========== Provider Fallback Chain ==========

# 默认回退顺序：硅基流动 → DeepSeek → OpenAI → OpenRouter → custom
_FALLBACK_ORDER: list[str] = ["siliconflow", "deepseek", "openai", "openrouter", "custom"]


def get_fallback_chain(model_override: str | None = None) -> list[tuple[str, str, str, str]]:
    """返回可用的 provider 回退链: [(base_url, api_key, model, provider_id), ...]

    按 _FALLBACK_ORDER 排序，跳过没有 api_key 的 provider。
    第一个是当前主配置（per-role 覆盖 > 会议级覆盖 > 环境变量默认），后续是备选。
    调用方应在主 provider 连接失败时依次尝试后续 provider。

    model_override: 可选，格式为 "provider_id:model_id" 或纯 "model_id"。
    当提供时，主配置使用指定的模型而非默认模型。
    """
    chain: list[tuple[str, str, str, str]] = []
    seen_urls: set[str] = set()

    # 解析 model_override 格式: "provider_id:model_id" 或 "model_id"
    override_provider = ""
    override_model = ""
    if model_override:
        if ":" in model_override:
            prefix = model_override.split(":", 1)[0]
            if prefix in PROVIDERS:
                # "siliconflow:deepseek-ai/DeepSeek-V3.2" 或 "openai:gpt-4o" 格式
                override_provider, override_model = model_override.split(":", 1)
            else:
                # ":" 存在但前缀不是已知 provider，视为纯 model_id
                override_model = model_override
        else:
            override_model = model_override

    # 首先加入当前主配置
    try:
        from app.context import get_meeting_id
        mid = get_meeting_id()
        if mid and mid != "-":
            base_url, api_key, model, pid = get_meeting_llm_config(mid)
            # 如果有 model_override，覆盖模型（和 provider）
            if override_model:
                model = override_model
                if override_provider:
                    pid = override_provider
                    p = PROVIDERS.get(pid)
                    if p:
                        base_url = p.base_url
                        api_key = p.api_key or api_key
            if base_url and api_key:
                chain.append((base_url, api_key, model, pid))
                seen_urls.add(base_url.rstrip("/"))
    except Exception:
        pass

    # 如果主配置未设置，用全局默认
    if not chain and settings.llm_base_url and settings.llm_api_key:
        model = override_model or settings.llm_model
        chain.append((settings.llm_base_url, settings.llm_api_key, model, "default"))
        seen_urls.add(settings.llm_base_url.rstrip("/"))

    # 按回退顺序加入其他 provider
    for pid in _FALLBACK_ORDER:
        p = PROVIDERS.get(pid)
        if not p or not p.api_key or not p.base_url:
            continue
        url = p.base_url.rstrip("/")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # 使用该 provider 的默认模型（回退链不使用 override，因为不同 provider 模型名不同）
        model = settings.llm_model  # 统一使用用户配置的模型
        chain.append((p.base_url, p.api_key, model, pid))

    return chain


# ========== 上下文窗口管理 ==========

def estimate_tokens(text: str) -> int:
    """粗略估算文本的 token 数量。

    中文约 2 字符/token，英文约 4 字符/token。
    """
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return (chinese_chars // 2) + (other_chars // 4)


def trim_prompt_to_budget(prompt: str, max_tokens: int = 32000) -> str:
    """如果 prompt 超过 token 预算，截断中间部分，保留头部（指令）和尾部（输出格式）。

    策略：保留前 40% 和后 20% 的 token，中间用 [... 内容已截断 ...] 替代。
    """
    total = estimate_tokens(prompt)
    if total <= max_tokens:
        return prompt

    lines = prompt.split("\n")
    # 保留头部和尾部
    head_tokens = int(max_tokens * 0.4)
    tail_tokens = int(max_tokens * 0.2)

    head_lines: list[str] = []
    head_count = 0
    for line in lines:
        line_tokens = estimate_tokens(line)
        if head_count + line_tokens > head_tokens:
            break
        head_lines.append(line)
        head_count += line_tokens

    tail_lines: list[str] = []
    tail_count = 0
    for line in reversed(lines):
        line_tokens = estimate_tokens(line)
        if tail_count + line_tokens > tail_tokens:
            break
        tail_lines.insert(0, line)
        tail_count += line_tokens

    truncated_note = f"\n[... 内容已截断: 原文约 {total} tokens, 预算 {max_tokens} tokens ...]\n"
    return "\n".join(head_lines) + truncated_note + "\n".join(tail_lines)


# ========== 定价表（人民币 元/百万Token） ==========
# SiliconFlow 定价（2026-07-11 更新，来源：siliconflow.cn/pricing 官方价格页）
# 注意：
#   - 部分模型有分段定价（如<128k和≥128k价格不同），此处取<128k价格作为主价
#   - 缓存命中价格暂不单独支持，仅在主价基础上估算
#   - 免费模型有 RPM/TPM 限制
MODEL_PRICING: dict[str, dict[str, Any]] = {
    # --- DeepSeek 系列 ---
    "deepseek-ai/DeepSeek-V4-Pro": {"input": 12.0, "output": 24.0, "currency": "CNY", "tier": "pro"},
    "deepseek-ai/DeepSeek-V4-Flash": {"input": 1.0, "output": 2.0, "currency": "CNY", "tier": "fast"},
    "deepseek-ai/DeepSeek-V3.2": {"input": 4.0, "output": 6.0, "currency": "CNY", "tier": "standard"},
    "deepseek-ai/DeepSeek-V3.1-Terminus": {"input": 4.0, "output": 12.0, "currency": "CNY", "tier": "standard"},
    "deepseek-ai/DeepSeek-R1": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "reasoning"},
    "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free"},
    # Pro 版（专享，价格与普通版一致但无速率限制）
    "Pro/deepseek-ai/DeepSeek-V4-Pro": {"input": 12.0, "output": 24.0, "currency": "CNY", "tier": "pro"},
    "Pro/deepseek-ai/DeepSeek-V4-Flash": {"input": 1.0, "output": 2.0, "currency": "CNY", "tier": "pro"},
    "Pro/deepseek-ai/DeepSeek-V3.2": {"input": 4.0, "output": 6.0, "currency": "CNY", "tier": "pro"},
    "Pro/deepseek-ai/DeepSeek-V3.1-Terminus": {"input": 4.0, "output": 12.0, "currency": "CNY", "tier": "pro"},
    "Pro/deepseek-ai/DeepSeek-R1": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "pro"},
    # --- Qwen 系列 ---
    "Qwen/Qwen3-8B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free"},
    "Qwen/Qwen3.5-4B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free"},
    "Qwen/Qwen3.5-9B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free"},
    "Qwen/Qwen3.5-27B": {"input": 0.6, "output": 4.8, "currency": "CNY", "tier": "standard"},
    "Qwen/Qwen3.5-35B-A3B": {"input": 0.4, "output": 3.2, "currency": "CNY", "tier": "cheap"},
    "Qwen/Qwen3.5-122B-A10B": {"input": 0.8, "output": 6.4, "currency": "CNY", "tier": "standard"},
    "Qwen/Qwen3.5-397B-A17B": {"input": 1.2, "output": 7.2, "currency": "CNY", "tier": "pro"},
    "Qwen/Qwen3.6-27B": {"input": 3.0, "output": 18.0, "currency": "CNY", "tier": "standard"},
    "Qwen/Qwen3.6-35B-A3B": {"input": 1.8, "output": 10.8, "currency": "CNY", "tier": "cheap"},
    # --- GLM 系列 ---
    "THUDM/GLM-Z1-9B-0414": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free"},
    "zai-org/GLM-5.1": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "standard"},
    "zai-org/GLM-5.2": {"input": 8.0, "output": 28.0, "currency": "CNY", "tier": "standard"},
    "Pro/zai-org/GLM-5.1": {"input": 6.0, "output": 24.0, "currency": "CNY", "tier": "pro"},
    # --- Kimi 系列 ---
    "moonshotai/Kimi-K2.6": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "standard"},
    "Pro/moonshotai/Kimi-K2.6": {"input": 6.5, "output": 27.0, "currency": "CNY", "tier": "pro"},
    "moonshotai/Kimi-K2.7-Code": {"input": 6.5, "output": 27.0, "currency": "CNY", "tier": "standard"},
    # --- MiniMax ---
    "MiniMaxAI/MiniMax-M2.5": {"input": 2.1, "output": 8.4, "currency": "CNY", "tier": "standard"},
    "Pro/MiniMaxAI/MiniMax-M2.5": {"input": 2.1, "output": 8.4, "currency": "CNY", "tier": "pro"},
    # --- 其他 ---
    "tencent/Hunyuan-MT-7B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free"},
    "tencent/Hunyuan-A13B-Instruct": {"input": 1.0, "output": 4.0, "currency": "CNY", "tier": "standard"},
    "meituan-longcat/LongCat-2.0": {"input": 5.0, "output": 20.0, "currency": "CNY", "tier": "standard"},
    "nex-agi/Nex-N2-Pro": {"input": 1.75, "output": 7.0, "currency": "CNY", "tier": "standard"},
    "ByteDance-Seed/Seed-OSS-36B-Instruct": {"input": 1.5, "output": 4.0, "currency": "CNY", "tier": "standard"},
    "stepfun-ai/Step-3.5-Flash": {"input": 0.7, "output": 2.1, "currency": "CNY", "tier": "fast"},
    "inclusionAI/Ling-flash-2.0": {"input": 1.0, "output": 4.0, "currency": "CNY", "tier": "standard"},
    "inclusionAI/Ling-mini-2.0": {"input": 0.5, "output": 2.0, "currency": "CNY", "tier": "cheap"},
    # Embedding/Reranker（免费版）
    "BAAI/bge-m3": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free"},
    "BAAI/bge-reranker-v2-m3": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free"},
    "Pro/BAAI/bge-m3": {"input": 0.07, "output": 0.0, "currency": "CNY", "tier": "pro"},
    "Pro/BAAI/bge-reranker-v2-m3": {"input": 0.07, "output": 0.0, "currency": "CNY", "tier": "pro"},
    "Qwen/Qwen3-VL-Embedding-8B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free"},
    "Qwen/Qwen3-VL-Reranker-8B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free"},
    # --- 兼容别名（cost_tracker旧表兼容） ---
    "deepseek-chat": {"input": 2.0, "output": 8.0, "currency": "CNY", "tier": "standard"},
    "deepseek-reasoner": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "reasoning"},
    "gpt-4o": {"input": 18.0, "output": 72.0, "currency": "CNY", "tier": "pro"},
    "gpt-4o-mini": {"input": 1.08, "output": 4.32, "currency": "CNY", "tier": "cheap"},
    "_default": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "standard"},
}

# 推荐模型列表（会议中常用）
RECOMMENDED_MODELS = [
    {"id": "Qwen/Qwen3-8B", "name": "Qwen3-8B (免费)", "desc": "8.2B通用模型，完全免费", "recommended_for": "测试/通用任务"},
    {"id": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B", "name": "DeepSeek-R1-8B (免费)", "desc": "推理模型，免费使用", "recommended_for": "推理/数学/代码"},
    {"id": "THUDM/GLM-Z1-9B-0414", "name": "GLM-Z1-9B (免费)", "desc": "9B推理模型，免费使用", "recommended_for": "推理/通用任务"},
    {"id": "deepseek-ai/DeepSeek-V3.2", "name": "DeepSeek-V3.2", "desc": "强JSON遵循，性价比高", "recommended_for": "会议讨论/产出"},
    {"id": "deepseek-ai/DeepSeek-V4-Flash", "name": "DeepSeek-V4-Flash", "desc": "快速响应，成本低", "recommended_for": "快速讨论/简单任务"},
    {"id": "Qwen/Qwen3.5-35B-A3B", "name": "Qwen3.5-35B-MoE", "desc": "MoE小模型，免费额度", "recommended_for": "测试/简单任务"},
    {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek-R1", "desc": "推理模型，深度思考", "recommended_for": "复杂推理/代码审查"},
    {"id": "Pro/deepseek-ai/DeepSeek-V3.2", "name": "DeepSeek-V3.2 Pro", "desc": "专享版，稳定无速率限制", "recommended_for": "生产环境"},
]


def get_model_pricing(model_id: str) -> dict[str, Any]:
    """获取模型定价信息（优先动态抓取，回退到硬编码表）"""
    # 延迟导入避免循环依赖
    from .pricing_fetcher import get_model_pricing as _live_pricing
    return _live_pricing(model_id)


def estimate_cost_cny(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """估算调用成本（人民币）"""
    p = get_model_pricing(model_id)
    cost = (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]
    return round(cost, 6)


# ========== 模型分类辅助 ==========

def categorize_models(models: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """将模型列表分类：free/cheap/standard/pro/reasoning/multimodal/embedding"""
    categories: dict[str, list[dict[str, Any]]] = {
        "recommended": [],
        "free": [],
        "reasoning": [],
        "vision": [],
        "embedding": [],
        "chat": [],
    }
    rec_ids = {m["id"] for m in RECOMMENDED_MODELS}
    for m in models:
        mid = m.get("id", "")
        info = {
            "id": mid,
            "object": m.get("object", "model"),
            "owned_by": m.get("owned_by", ""),
            "pricing": get_model_pricing(mid),
        }
        if mid in rec_ids:
            categories["recommended"].append(info)
        # Embedding/Reranker
        if any(kw in mid.lower() for kw in ["embed", "bge", "rerank"]):
            categories["embedding"].append(info)
        # 视觉/多模态
        elif any(kw in mid.lower() for kw in ["vl", "vision", "image", "ocr", "voice"]):
            categories["vision"].append(info)
        # 推理模型
        elif "R1" in mid or "reasoner" in mid.lower() or "r1" in mid.lower():
            categories["reasoning"].append(info)
        # 免费模型
        elif get_model_pricing(mid).get("tier") == "free" or get_model_pricing(mid).get("input", 0) == 0:
            categories["free"].append(info)
        else:
            categories["chat"].append(info)
    return categories


# ========== 运行时模型选择 ==========

@dataclass
class MeetingLLMConfig:
    """单个会议的 LLM 配置（可覆盖全局默认）"""
    provider_id: str = ""          # provider ID，空=使用默认
    model: str = ""                # 模型ID，空=使用默认
    api_key: str = ""              # 自定义API Key（BYOK），空=使用默认
    base_url: str = ""             # 自定义base_url，空=使用provider默认


# 进程级：会议ID -> MeetingLLMConfig 覆盖
_meeting_overrides: dict[str, MeetingLLMConfig] = {}
# 进程级：缓存的模型列表（provider_id -> (timestamp, models)）
_model_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
CACHE_TTL = 300  # 模型列表缓存5分钟


def set_meeting_model(meeting_id: str, provider_id: str = "", model: str = "",
                      api_key: str = "", base_url: str = "") -> MeetingLLMConfig:
    """设置某个会议的模型覆盖配置"""
    cfg = _meeting_overrides.get(meeting_id, MeetingLLMConfig())
    if provider_id:
        cfg.provider_id = provider_id
    if model:
        cfg.model = model
    if api_key:
        cfg.api_key = api_key
    if base_url:
        cfg.base_url = base_url
    _meeting_overrides[meeting_id] = cfg
    return cfg


def get_meeting_llm_config(meeting_id: str = "") -> tuple[str, str, str, str]:
    """获取会议的有效 LLM 配置 (base_url, api_key, model, provider_id)
    
    优先级：会议覆盖 > 环境变量默认
    """
    # 默认值从环境变量
    default_base = settings.llm_base_url or "https://api.siliconflow.cn/v1"
    default_key = settings.llm_api_key
    default_model = settings.llm_model
    default_provider = "siliconflow" if "siliconflow" in default_base else "custom"

    if not meeting_id or meeting_id not in _meeting_overrides:
        return default_base, default_key, default_model, default_provider

    cfg = _meeting_overrides[meeting_id]
    provider = PROVIDERS.get(cfg.provider_id) if cfg.provider_id else None

    base_url = cfg.base_url or (provider.base_url if provider else default_base)
    api_key = cfg.api_key or (provider.api_key if provider else default_key)
    model = cfg.model or default_model
    provider_id = cfg.provider_id or default_provider

    return base_url, api_key, model, provider_id


def clear_meeting_config(meeting_id: str) -> None:
    """清理会议配置（会议结束时调用）"""
    _meeting_overrides.pop(meeting_id, None)


def _is_provider_model_format(s: str) -> bool:
    """判断字符串是否为 "provider_id:model_id" 格式

    规则：包含 ":" 且 ":" 前面的部分是合法的 provider ID（在 PROVIDERS 中注册）。
    例如：siliconflow:deepseek-ai/DeepSeek-V3.2 → True
          openai:gpt-4o → True
          deepseek-ai/DeepSeek-V3.2 → False（无 ":"）
    """
    if ":" not in s:
        return False
    prefix = s.split(":", 1)[0]
    return prefix in PROVIDERS


def resolve_models_for_meeting(
    role_configs: list[dict[str, Any]],
    meeting_model: str = "",
    stage_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """为会议快照所有角色和阶段的最终模型配置。

    在会议启动时调用一次，将结果存入 MeetingState.resolved_models，
    运行时 LLM 调用直接读取快照，不再动态 resolve，消除中途切模型的不确定性。

    优先级（从高到低）：
    1. 角色级 model_override（role_configs 中的 model_override 字段）
    2. 阶段级覆盖（stage_overrides 参数，key 为 @stage_name）
    3. 会议级 model（meeting_model 参数）
    4. ENV 默认（settings.llm_model）

    Args:
        role_configs: 会议角色配置列表，每项可含 model_override 字段
        meeting_model: 会议级模型（空=用 ENV 默认）
        stage_overrides: 阶段级模型覆盖，如 {"@arbitrate": "deepseek-ai/DeepSeek-R1"}

    Returns:
        dict[str, str]: {key: "provider_id:model_id"}
            key 为角色 id（如 "engineer"）或 @阶段名（如 "@arbitrate"）
    """
    default_provider = "siliconflow" if "siliconflow" in (settings.llm_base_url or "") else "custom"

    # 解析 meeting_model 中是否已含 provider 前缀（如 "siliconflow:deepseek-ai/DeepSeek-V4-Flash"）
    if meeting_model and _is_provider_model_format(meeting_model):
        # meeting_model 已是 "provider:model" 格式，直接作为默认值使用
        default_resolved = meeting_model
    elif meeting_model:
        # meeting_model 是纯 model_id，拼接 provider 前缀
        default_resolved = f"{default_provider}:{meeting_model}"
    else:
        # 无会议级覆盖，使用 ENV 默认
        default_resolved = f"{default_provider}:{settings.llm_model}"

    resolved: dict[str, str] = {}

    # 1. 解析每个角色的模型
    for rc in role_configs:
        role_id = rc.get("id", rc.get("role", ""))
        if not role_id:
            continue
        role_model = rc.get("model_override", "")
        if role_model:
            # 角色有自己的模型覆盖
            if _is_provider_model_format(role_model):
                resolved[role_id] = role_model  # 已经是 "provider:model" 格式
            else:
                resolved[role_id] = f"{default_provider}:{role_model}"
        else:
            # 继承会议级模型（已含 provider 前缀）
            resolved[role_id] = default_resolved

    # 2. 解析阶段级覆盖（@stage_name 格式）
    default_stages = ["clarify", "intra_team", "cross_team", "evidence_check", "arbitrate", "produce"]
    for stage in default_stages:
        key = f"@{stage}"
        if stage_overrides and key in stage_overrides:
            stage_model = stage_overrides[key]
            if _is_provider_model_format(stage_model):
                resolved[key] = stage_model  # 已是 "provider:model" 格式
            else:
                resolved[key] = f"{default_provider}:{stage_model}"
        # 不设置默认阶段覆盖（角色级即可，阶段覆盖是可选的增强）

    return resolved


def resolve_model_from_snapshot(
    resolved_models: dict[str, str],
    agent_role: str = "",
    stage: str = "",
) -> str:
    """从快照中解析某次 LLM 调用应使用的模型。

    优先级：阶段覆盖 > 角色覆盖 > 返回空字符串（fallback 到会议级/ENV）

    Args:
        resolved_models: 会议启动时快照的模型配置
        agent_role: 当前 Agent 角色（如 "engineer"）
        stage: 当前阶段名（如 "intra_team"）

    Returns:
        "provider_id:model_id" 或空字符串（表示用默认）
    """
    if not resolved_models:
        return ""
    # 优先查阶段覆盖
    stage_key = f"@{stage}"
    if stage_key in resolved_models:
        return resolved_models[stage_key]
    # 其次查角色覆盖
    if agent_role and agent_role in resolved_models:
        return resolved_models[agent_role]
    return ""


# ========== 远程查询：模型列表和余额 ==========

async def fetch_models(provider_id: str = "", api_key: str = "", base_url: str = "",
                       use_cache: bool = True) -> list[dict[str, Any]]:
    """从Provider拉取可用模型列表
    
    优先从缓存返回（5分钟TTL），use_cache=False强制刷新
    """
    # 确定用哪个provider
    if provider_id and provider_id in PROVIDERS:
        p = PROVIDERS[provider_id]
        url = f"{(base_url or p.base_url).rstrip('/')}{p.models_endpoint}"
        key = api_key or p.api_key
        cache_key = f"{provider_id}:{url}:{key[:10]}"
    elif base_url:
        # 自定义endpoint
        url = f"{base_url.rstrip('/')}/models"
        key = api_key
        cache_key = f"custom:{url}:{key[:10]}"
        p = PROVIDERS["custom"]
    else:
        # 默认provider
        p = PROVIDERS["siliconflow"]
        url = f"{p.base_url}{p.models_endpoint}"
        key = api_key or p.api_key
        cache_key = f"siliconflow:{url}:{key[:10]}"

    # 缓存检查
    if use_cache and cache_key in _model_cache:
        ts, models = _model_cache[cache_key]
        if time.monotonic() - ts < CACHE_TTL:
            return models

    if not key:
        logger.warning("fetch_models: 无API Key，无法拉取模型列表")
        return []

    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            _model_cache[cache_key] = (time.monotonic(), models)
            logger.info(f"fetch_models: 从 {url} 拉取到 {len(models)} 个模型")
            return models
    except Exception as e:
        logger.error(f"fetch_models 失败: {e}")
        return []


async def fetch_balance(provider_id: str = "", api_key: str = "", base_url: str = "") -> dict[str, Any]:
    """查询账户余额
    
    返回: {"balance": float, "currency": "CNY"|"USD", "raw": {...}, "provider": str, "supported": bool}
    """
    # 确定provider
    if provider_id and provider_id in PROVIDERS:
        p = PROVIDERS[provider_id]
    elif base_url:
        p = PROVIDERS["custom"]
        p.base_url = base_url
    else:
        p = PROVIDERS["siliconflow"]

    endpoint = p.balance_endpoint
    if not endpoint:
        return {
            "balance": None,
            "currency": "CNY",
            "raw": {},
            "provider": p.id,
            "supported": False,
            "message": f"{p.name} 不支持余额查询API",
        }

    url = f"{(base_url or p.base_url).rstrip('/')}{endpoint}"
    key = api_key or p.api_key
    if not key:
        return {"balance": None, "currency": "CNY", "raw": {}, "provider": p.id, "supported": False, "message": "未配置API Key"}

    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # 按path提取余额
        balance_val = data
        for part in p.balance_response_path:
            if isinstance(balance_val, dict) and part in balance_val:
                balance_val = balance_val[part]
            elif isinstance(balance_val, list) and isinstance(part, int) and part < len(balance_val):
                balance_val = balance_val[part]
            else:
                balance_val = None
                break

        # 解析为float
        balance_float: float | None = None
        if balance_val is not None:
            try:
                balance_float = float(balance_val)
            except (ValueError, TypeError):
                balance_float = None

        # 判断币种（OpenRouter/OpenAI是USD，国内厂商是RMB）
        currency = "USD" if p.id in ("openai", "openrouter") else "CNY"

        return {
            "balance": balance_float,
            "currency": currency,
            "raw": data if isinstance(data, dict) else {},
            "provider": p.id,
            "supported": True,
            "message": "ok",
        }
    except httpx.HTTPStatusError as e:
        return {
            "balance": None, "currency": "CNY", "raw": {},
            "provider": p.id, "supported": True,
            "message": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
        }
    except Exception as e:
        return {
            "balance": None, "currency": "CNY", "raw": {},
            "provider": p.id, "supported": True,
            "message": f"查询失败: {e}",
        }


def invalidate_model_cache() -> None:
    """清除模型列表缓存（用于调试）"""
    _model_cache.clear()


def list_providers() -> list[dict[str, Any]]:
    """列出所有已注册的Provider"""
    return [
        {
            "id": p.id,
            "name": p.name,
            "base_url": p.base_url,
            "has_key": bool(p.api_key),
            "supports_balance": bool(p.balance_endpoint),
            "supports_custom_key": p.supports_custom_key,
            "supports_models_list": bool(p.models_endpoint),
            "pricing_note": p.pricing_note,
        }
        for p in PROVIDERS.values()
    ]
