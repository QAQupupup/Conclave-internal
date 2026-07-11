"""硅基流动（SiliconFlow）定价动态抓取模块

从 https://siliconflow.cn/pricing 页面解析 Next.js RSC Flight 数据，
提取所有模型的实时输入/输出定价。

工作原理：
1. SiliconFlow定价页是Next.js App Router，模型数据通过 self.__next_f.push() 内嵌
2. 数据格式为React Flight协议：行对象以 $HEX_ID:{...json...} 定义，引用时用 "$HEX_ID"
3. 我们解析所有行对象，构建引用表，然后从chats数组中提取模型信息
4. 支持两种定价格式：
   a) 简单格式：直接有 inputPrice 和 price(output) 字段
   b) pricing引用格式：pricing指向一个数组，包含 {specification:"prompt"} 和 {specification:"completion"} 对象

设计原则：
- 启动时异步抓取一次，缓存24小时到磁盘
- 抓取失败时回退到内置的硬编码价格表
- 不依赖Playwright，仅用httpx+正则解析HTML中的内嵌JSON数据
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_PRICING_URL = "https://siliconflow.cn/pricing"
_CACHE_FILE = Path(__file__).parent.parent / "data" / "sf_pricing_cache.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24小时

# 内置回退价格表（当动态抓取失败时使用，2026-07-11从官网同步）
_FALLBACK_PRICING: dict[str, dict[str, Any]] = {
    "deepseek-ai/DeepSeek-V4-Pro": {"input": 12.0, "output": 24.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "deepseek-ai/DeepSeek-V4-Flash": {"input": 1.0, "output": 2.0, "currency": "CNY", "tier": "fast", "source": "fallback"},
    "deepseek-ai/DeepSeek-V3.2": {"input": 4.0, "output": 6.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "deepseek-ai/DeepSeek-V3.1-Terminus": {"input": 4.0, "output": 12.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "deepseek-ai/DeepSeek-V3": {"input": 2.0, "output": 8.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "deepseek-ai/DeepSeek-R1": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "reasoning", "source": "fallback"},
    "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free", "source": "fallback"},
    "Pro/deepseek-ai/DeepSeek-V4-Pro": {"input": 12.0, "output": 24.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "Pro/deepseek-ai/DeepSeek-V4-Flash": {"input": 1.0, "output": 2.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "Pro/deepseek-ai/DeepSeek-V3.2": {"input": 4.0, "output": 6.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "Pro/deepseek-ai/DeepSeek-V3": {"input": 2.0, "output": 8.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "Pro/deepseek-ai/DeepSeek-V3.1-Terminus": {"input": 4.0, "output": 12.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "Pro/deepseek-ai/DeepSeek-R1": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "Qwen/Qwen3-8B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free", "source": "fallback"},
    "Qwen/Qwen3.5-4B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free", "source": "fallback"},
    "Qwen/Qwen3.5-9B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free", "source": "fallback"},
    "Qwen/Qwen3.5-27B": {"input": 0.6, "output": 4.8, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "Qwen/Qwen3.5-35B-A3B": {"input": 0.4, "output": 3.2, "currency": "CNY", "tier": "cheap", "source": "fallback"},
    "Qwen/Qwen3.5-122B-A10B": {"input": 0.8, "output": 6.4, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "Qwen/Qwen3.5-397B-A17B": {"input": 1.2, "output": 7.2, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "Qwen/Qwen3.6-27B": {"input": 3.0, "output": 18.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "Qwen/Qwen3.6-35B-A3B": {"input": 1.8, "output": 10.8, "currency": "CNY", "tier": "cheap", "source": "fallback"},
    "THUDM/GLM-Z1-9B-0414": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free", "source": "fallback"},
    "zai-org/GLM-5.1": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "zai-org/GLM-5.2": {"input": 8.0, "output": 28.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "Pro/zai-org/GLM-5.1": {"input": 6.0, "output": 24.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "moonshotai/Kimi-K2.6": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "Pro/moonshotai/Kimi-K2.6": {"input": 6.5, "output": 27.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "moonshotai/Kimi-K2.7-Code": {"input": 6.5, "output": 27.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "MiniMaxAI/MiniMax-M2.5": {"input": 2.1, "output": 8.4, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "Pro/MiniMaxAI/MiniMax-M2.5": {"input": 2.1, "output": 8.4, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "tencent/Hunyuan-MT-7B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free", "source": "fallback"},
    "tencent/Hunyuan-A13B-Instruct": {"input": 1.0, "output": 4.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "meituan-longcat/LongCat-2.0": {"input": 5.0, "output": 20.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "nex-agi/Nex-N2-Pro": {"input": 1.75, "output": 7.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "ByteDance-Seed/Seed-OSS-36B-Instruct": {"input": 1.5, "output": 4.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "stepfun-ai/Step-3.5-Flash": {"input": 0.7, "output": 2.1, "currency": "CNY", "tier": "fast", "source": "fallback"},
    "inclusionAI/Ling-flash-2.0": {"input": 1.0, "output": 4.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "inclusionAI/Ling-mini-2.0": {"input": 0.5, "output": 2.0, "currency": "CNY", "tier": "cheap", "source": "fallback"},
    "BAAI/bge-m3": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free", "source": "fallback"},
    "BAAI/bge-reranker-v2-m3": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free", "source": "fallback"},
    "Pro/BAAI/bge-m3": {"input": 0.07, "output": 0.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "Pro/BAAI/bge-reranker-v2-m3": {"input": 0.07, "output": 0.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "Qwen/Qwen3-VL-Embedding-8B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free", "source": "fallback"},
    "Qwen/Qwen3-VL-Reranker-8B": {"input": 0.0, "output": 0.0, "currency": "CNY", "tier": "free", "source": "fallback"},
    "deepseek-chat": {"input": 2.0, "output": 8.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
    "deepseek-reasoner": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "reasoning", "source": "fallback"},
    "gpt-4o": {"input": 18.0, "output": 72.0, "currency": "CNY", "tier": "pro", "source": "fallback"},
    "gpt-4o-mini": {"input": 1.08, "output": 4.32, "currency": "CNY", "tier": "cheap", "source": "fallback"},
    "_default": {"input": 4.0, "output": 16.0, "currency": "CNY", "tier": "standard", "source": "fallback"},
}

# 模块级缓存
_dynamic_pricing: dict[str, dict[str, Any]] = {}
_fetch_lock = asyncio.Lock()
_last_fetch_time: float = 0
_fetch_started = False


def _parse_price(val: Any) -> float | None:
    if val is None:
        return None
    try:
        s = str(val).strip()
        if not s:
            return None
        f = float(s)
        return f if f >= 0 else None
    except (ValueError, TypeError):
        return None


def _determine_tier(input_price: float, output_price: float, model_name: str, sub_type: str = "") -> str:
    if input_price == 0 and output_price == 0:
        return "free"
    name_lower = model_name.lower()
    if sub_type == "reasoning" or "r1" in name_lower or "/deepseek-r1" in name_lower:
        return "reasoning"
    if model_name.startswith("Pro/"):
        return "pro"
    if output_price <= 2.0:
        return "fast"
    if output_price <= 5.0:
        return "cheap"
    if output_price >= 20.0:
        return "pro"
    return "standard"


def _resolve_flight_rows(text: str) -> dict[str, Any]:
    """解析React Flight协议的行对象，构建{hex_id: json_value}引用表

    Flight数据格式：每行以 HEXID:{json} 定义一个值，后续用 "$HEXID" 引用它。
    我们需要找到所有 $HEXID:{...} 模式并解析JSON。
    """
    rows: dict[str, Any] = {}

    # 匹配 $HEXID:JSON_VALUE 的模式
    # HEXID是十六进制字符串（如5cb, 5b9, 5ba, L10等）
    # JSON_VALUE可以是对象{}、数组[]、字符串"..."、数字、布尔值、null
    row_pattern = re.compile(r'(?:^|\n)([0-9a-zA-Z]+):')

    # 策略：找到所有看起来像行定义的起始位置，然后尝试解析JSON
    pos = 0
    while True:
        m = row_pattern.search(text, pos)
        if not m:
            break
        row_id = m.group(1)
        json_start = m.end()

        # 尝试从json_start解析JSON值
        # 跳过空白
        while json_start < len(text) and text[json_start] in ' \t':
            json_start += 1
        if json_start >= len(text):
            pos = m.end()
            continue

        json_str = None
        try:
            if text[json_start] == '{':
                # 找配对的}
                depth = 0
                in_str = False
                escape = False
                for i in range(json_start, min(json_start + 5000, len(text))):
                    c = text[i]
                    if escape:
                        escape = False
                        continue
                    if c == '\\':
                        escape = True
                        continue
                    if c == '"':
                        in_str = not in_str
                        continue
                    if in_str:
                        continue
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            json_str = text[json_start:i+1]
                            break
            elif text[json_start] == '[':
                depth = 0
                in_str = False
                escape = False
                for i in range(json_start, min(json_start + 5000, len(text))):
                    c = text[i]
                    if escape:
                        escape = False
                        continue
                    if c == '\\':
                        escape = True
                        continue
                    if c == '"':
                        in_str = not in_str
                        continue
                    if in_str:
                        continue
                    if c == '[':
                        depth += 1
                    elif c == ']':
                        depth -= 1
                        if depth == 0:
                            json_str = text[json_start:i+1]
                            break
        except Exception:
            pass

        if json_str:
            try:
                val = json.loads(json_str)
                rows[row_id] = val
            except json.JSONDecodeError:
                pass
            pos = json_start + len(json_str)
        else:
            pos = m.end()

    return rows


def _resolve_value(val: Any, rows: dict[str, Any], depth: int = 0) -> Any:
    """递归解析Flight引用：如果val是"$HEXID"且rows中存在，则替换为实际值"""
    if depth > 10:
        return val
    if isinstance(val, str) and val.startswith("$") and len(val) < 20:
        ref_id = val[1:]
        if ref_id in rows:
            return _resolve_value(rows[ref_id], rows, depth + 1)
    elif isinstance(val, dict):
        return {k: _resolve_value(v, rows, depth + 1) for k, v in val.items()}
    elif isinstance(val, list):
        return [_resolve_value(v, rows, depth + 1) for v in val]
    return val


def _extract_pricing_from_model(model: dict[str, Any], rows: dict[str, Any]) -> tuple[float | None, float | None]:
    """从模型对象中提取(输入价格, 输出价格)，单位元/M Tokens"""
    input_price = None
    output_price = None

    # 方法1：直接用inputPrice字段
    if "inputPrice" in model:
        input_price = _parse_price(model["inputPrice"])

    # 方法2：通过pricing引用解析
    pricing_ref = model.get("pricing")
    if pricing_ref:
        pricing_data = _resolve_value(pricing_ref, rows)
        if isinstance(pricing_data, list):
            for item in pricing_data:
                if isinstance(item, dict):
                    spec = item.get("specification", "")
                    p = _parse_price(item.get("price"))
                    if spec == "prompt" and p is not None:
                        input_price = p
                    elif spec == "completion" and p is not None:
                        output_price = p
        elif isinstance(pricing_data, dict):
            for key in ("prompt", "input"):
                if key in pricing_data:
                    p = _parse_price(pricing_data[key].get("price") if isinstance(pricing_data[key], dict) else pricing_data[key])
                    if p is not None:
                        input_price = p
            for key in ("completion", "output"):
                if key in pricing_data:
                    p = _parse_price(pricing_data[key].get("price") if isinstance(pricing_data[key], dict) else pricing_data[key])
                    if p is not None:
                        output_price = p

    # 方法3：使用price字段作为输出价格（仅当output_price还未设置时）
    if output_price is None and "price" in model:
        p = _parse_price(model["price"])
        # 验证：output_price应该大于等于input_price（通常），或者如果是embedding模型output=0
        if p is not None:
            output_price = p

    # Embedding/reranker模型output_price=0
    sub_type = model.get("subType", "")
    if sub_type in ("embedding", "reranker") and output_price is None:
        output_price = 0.0

    return input_price, output_price


def _parse_flight_data(html: str) -> dict[str, dict[str, Any]]:
    """从Next.js RSC Flight HTML中解析模型定价数据"""
    pricing: dict[str, dict[str, Any]] = {}

    # 提取所有 self.__next_f.push([1,"..."]) 内容
    scripts = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)

    # 解码并合并
    all_text_parts = []
    for s in scripts:
        try:
            decoded = s.encode().decode("unicode_escape", errors="replace")
            all_text_parts.append(decoded)
        except Exception:
            all_text_parts.append(s)
    all_text = "\n".join(all_text_parts)

    # 构建Flight行引用表
    rows = _resolve_flight_rows(all_text)
    logger.debug(f"解析到 {len(rows)} 个Flight行对象")

    # 找到所有包含modelName的模型对象
    # 策略：在all_text中找到所有"modelName":"X"的位置，然后从该位置向后扩展提取JSON对象
    model_positions = [(m.start(), m.group(1)) for m in re.finditer(r'"modelName"\s*:\s*"([^"]+)"', all_text)]

    for pos, model_name in model_positions:
        if "/" not in model_name or len(model_name) > 100:
            continue

        # 从modelName字段位置向前找到对象开始的{
        obj_start = all_text.rfind("{", 0, pos)
        if obj_start == -1:
            continue

        # 从obj_start找到配对的}
        depth = 0
        in_str = False
        escape = False
        obj_end = -1
        for i in range(obj_start, min(obj_start + 10000, len(all_text))):
            c = all_text[i]
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    obj_end = i + 1
                    break

        if obj_end == -1:
            continue

        obj_str = all_text[obj_start:obj_end]
        try:
            model = json.loads(obj_str)
        except json.JSONDecodeError:
            # 可能包含$HEXID引用，先替换再解析
            # 将 "$HEXID" 替换为 null 以允许JSON解析
            cleaned = re.sub(r'"[$][0-9a-zA-Z]+"', 'null', obj_str)
            try:
                model = json.loads(cleaned)
            except json.JSONDecodeError:
                continue

        if not isinstance(model, dict) or "modelName" not in model:
            continue

        # 提取定价
        input_price, output_price = _extract_pricing_from_model(model, rows)

        if input_price is None:
            continue
        if output_price is None:
            output_price = input_price

        sub_type = model.get("subType", "")
        tier = _determine_tier(input_price, output_price, model_name, sub_type)
        if model_name.startswith("Pro/") and tier not in ("free", "pro"):
            tier = "pro"

        # 如果同一模型名已经有记录，且旧数据更完整，保留旧数据
        if model_name in pricing:
            existing = pricing[model_name]
            # 如果新数据的output_price是0但旧数据不是，可能是embedding的误判，保留新的
            # 否则如果output_price明显不合理（如小于input_price很多），保留旧数据
            if output_price == 0 and input_price > 0 and sub_type not in ("embedding", "reranker"):
                continue
            if output_price > 0 and input_price > 0 and output_price < input_price * 0.5:
                # 输出价格不到输入的一半，可能是匹配到了缓存价格，跳过
                continue

        pricing[model_name] = {
            "input": input_price,
            "output": output_price,
            "currency": "CNY",
            "tier": tier,
            "source": "siliconflow_live",
            "fetched_at": time.time(),
            "sub_type": sub_type,
            "context_len": model.get("contextLen"),
        }

    return pricing


def _load_cache() -> dict[str, dict[str, Any]] | None:
    try:
        if not _CACHE_FILE.exists():
            return None
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "pricing" not in data:
            return None
        age = time.time() - data.get("fetched_at", 0)
        if age > _CACHE_TTL_SECONDS:
            return None
        return data["pricing"]
    except Exception as e:
        logger.warning(f"加载定价缓存失败: {e}")
        return None


def _save_cache(pricing: dict[str, dict[str, Any]]) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({
                "fetched_at": time.time(),
                "pricing": pricing,
                "model_count": len(pricing),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"保存定价缓存失败: {e}")


async def _fetch_live_pricing() -> dict[str, dict[str, Any]]:
    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
        ) as client:
            resp = await client.get(_PRICING_URL)
            resp.raise_for_status()
            html = resp.text

        pricing = _parse_flight_data(html)
        logger.info(f"从硅基流动官网抓取到 {len(pricing)} 个模型定价")
        return pricing
    except Exception as e:
        logger.error(f"抓取硅基流动定价失败: {e}", exc_info=True)
        return {}


async def ensure_pricing_loaded() -> None:
    """确保定价数据已加载（启动时异步调用，不阻塞启动）"""
    global _dynamic_pricing, _last_fetch_time, _fetch_started

    if _fetch_started:
        return
    _fetch_started = True

    cached = _load_cache()
    if cached:
        _dynamic_pricing = cached
        _last_fetch_time = time.time()
        logger.info(f"从缓存加载了 {len(cached)} 个模型定价")
        return

    asyncio.create_task(_refresh_pricing_async())


async def _refresh_pricing_async() -> None:
    global _dynamic_pricing, _last_fetch_time

    async with _fetch_lock:
        pricing = await _fetch_live_pricing()
        if pricing:
            _dynamic_pricing = pricing
            _last_fetch_time = time.time()
            _save_cache(pricing)
            logger.info(f"定价数据已更新，共 {len(pricing)} 个模型")
        else:
            _dynamic_pricing = dict(_FALLBACK_PRICING)
            _last_fetch_time = time.time()
            logger.warning("定价抓取失败，使用内置回退价格表")


def get_model_pricing(model_id: str) -> dict[str, Any]:
    """获取模型定价（优先动态抓取，回退到硬编码表）"""
    if model_id in _dynamic_pricing:
        return _dynamic_pricing[model_id]
    return _FALLBACK_PRICING.get(model_id, _FALLBACK_PRICING["_default"])


def get_all_pricing() -> dict[str, dict[str, Any]]:
    """获取所有定价（动态数据覆盖回退数据）"""
    merged = dict(_FALLBACK_PRICING)
    merged.update(_dynamic_pricing)
    return merged


def get_pricing_status() -> dict[str, Any]:
    live_count = sum(1 for p in _dynamic_pricing.values() if p.get("source") == "siliconflow_live")
    return {
        "live_models": live_count,
        "fallback_models": len(_FALLBACK_PRICING),
        "total_available": len(get_all_pricing()),
        "last_fetch": _last_fetch_time,
        "cache_file": str(_CACHE_FILE),
    }


async def refresh_pricing() -> dict[str, Any]:
    """强制刷新定价数据"""
    async with _fetch_lock:
        pricing = await _fetch_live_pricing()
        if pricing:
            global _dynamic_pricing, _last_fetch_time
            _dynamic_pricing = pricing
            _last_fetch_time = time.time()
            _save_cache(pricing)
            return {"success": True, "model_count": len(pricing), "source": "siliconflow_live"}
        return {"success": False, "error": "抓取失败，保留现有数据"}
