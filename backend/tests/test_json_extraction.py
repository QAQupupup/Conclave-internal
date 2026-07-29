"""三层 JSON 提取管线单元测试。

测试 _extract_json_with_reasoning 函数的三层回退逻辑：
- Tier 1: 标记分隔提取（主方案）
- Tier 2: 启发式 JSON 块提取（花括号匹配）
- Tier 3: 围栏清理后直接解析
"""

import json

import pytest

from app.agents.llm import (
    _extract_json_with_reasoning,
    _extract_largest_json_block,
    _strip_code_fences,
    _try_parse_json,
)

# ============================================================
# Tier 1: 标记分隔提取
# ============================================================


def test_extract_with_marker():
    """Tier 1: 标记 <<<JSON_RESULT>>> 正常提取"""
    content = '让我分析一下...\n这个议题涉及三个维度...\n<<<JSON_RESULT>>>\n{"claims": []}'
    parsed, reasoning = _extract_json_with_reasoning(content)
    assert parsed == {"claims": []}
    assert "让我分析一下" in reasoning


def test_extract_with_chinese_marker():
    """Tier 1: 中文标记 '这是最终思考后的Json答复' 正常提取"""
    content = '思考过程...\n这是最终思考后的Json答复\n{"claims": []}'
    parsed, reasoning = _extract_json_with_reasoning(content)
    assert parsed == {"claims": []}
    assert "思考过程" in reasoning


def test_extract_with_english_marker():
    """Tier 1: 英文标记 'Final JSON:' 正常提取"""
    content = 'Let me analyze...\nFinal JSON:\n{"result": true}'
    parsed, reasoning = _extract_json_with_reasoning(content)
    assert parsed == {"result": True}
    assert "Let me analyze" in reasoning


def test_extract_marker_with_ck_field():
    """Tier 1: JSON 中包含 _ck 字段（用户提议的方案）"""
    content = '经过深入分析...\n<<<JSON_RESULT>>>\n{"_ck": "这是Json答复", "claims": [{"claim": "test"}]}'
    parsed, reasoning = _extract_json_with_reasoning(content)
    assert parsed["_ck"] == "这是Json答复"
    assert parsed["claims"][0]["claim"] == "test"
    assert "经过深入分析" in reasoning


def test_extract_marker_empty_reasoning():
    """Tier 1: 标记在开头，推理过程为空"""
    content = '<<<JSON_RESULT>>>\n{"claims": []}'
    parsed, reasoning = _extract_json_with_reasoning(content)
    assert parsed == {"claims": []}
    assert reasoning == ""


def test_extract_marker_multiline_reasoning():
    """Tier 1: 多行推理过程"""
    content = (
        "第一步：分析用户需求\n"
        "第二步：评估技术可行性\n"
        "第三步：确定架构方案\n"
        "<<<JSON_RESULT>>>\n"
        '{"decision": "approved"}'
    )
    parsed, reasoning = _extract_json_with_reasoning(content)
    assert parsed == {"decision": "approved"}
    assert "第一步" in reasoning
    assert "第三步" in reasoning


# ============================================================
# Tier 2: 启发式 JSON 块提取
# ============================================================


def test_extract_without_marker():
    """Tier 2: 无标记，启发式提取最大 JSON 块"""
    content = '一些思考文字...\n{"claims": [{"claim": "test"}]}\n更多文字...'
    parsed, _ = _extract_json_with_reasoning(content)
    assert parsed["claims"][0]["claim"] == "test"


def test_extract_without_marker_reasoning_is_full_content():
    """Tier 2: 无标记时，reasoning 返回原始全文"""
    content = '思考内容 {"result": 42} 尾部文字'
    parsed, reasoning = _extract_json_with_reasoning(content)
    assert parsed == {"result": 42}
    assert "思考内容" in reasoning


def test_extract_nested_json():
    """Tier 2: 嵌套 JSON 结构"""
    content = '<<<JSON_RESULT>>>\n{"outer": {"inner": {"deep": true}}}'
    parsed, _ = _extract_json_with_reasoning(content)
    assert parsed["outer"]["inner"]["deep"] is True


def test_extract_json_with_braces_in_string():
    """Tier 2: JSON 字符串值中包含花括号（字符串感知匹配）"""
    content = '<<<JSON_RESULT>>>\n{"text": "function() { return {}; }"}'
    parsed, _ = _extract_json_with_reasoning(content)
    assert parsed["text"] == "function() { return {}; }"


def test_extract_json_with_escaped_quotes():
    """Tier 2: JSON 字符串中包含转义引号"""
    content = '<<<JSON_RESULT>>>\n{"msg": "He said \\"hello\\""}'
    parsed, _ = _extract_json_with_reasoning(content)
    assert parsed["msg"] == 'He said "hello"'


def test_extract_multiple_json_blocks():
    """Tier 2: 文本中有多个 JSON 块，提取第一个合法的"""
    content = '前文 {"first": 1} 中间 {"second": 2} 后文'
    parsed, _ = _extract_json_with_reasoning(content)
    assert parsed == {"first": 1}


# ============================================================
# Tier 3: 围栏清理后直接解析
# ============================================================


def test_extract_with_code_fence():
    """Tier 3: ```json 围栏包裹的 JSON"""
    content = '```json\n{"claims": []}\n```'
    parsed, _ = _extract_json_with_reasoning(content)
    assert parsed == {"claims": []}


def test_extract_with_plain_code_fence():
    """Tier 3: ``` 围栏包裹的 JSON（无 json 标记）"""
    content = '```\n{"result": true}\n```'
    parsed, _ = _extract_json_with_reasoning(content)
    assert parsed == {"result": True}


def test_extract_pure_json():
    """Tier 3: 纯 JSON 文本（无标记、无围栏、无多余文字）"""
    content = '{"claims": [{"claim": "pure"}]}'
    parsed, _ = _extract_json_with_reasoning(content)
    assert parsed["claims"][0]["claim"] == "pure"


# ============================================================
# 边界与异常场景
# ============================================================


def test_extract_empty():
    """空内容应抛出 JSONDecodeError"""
    with pytest.raises(json.JSONDecodeError):
        _extract_json_with_reasoning("")


def test_extract_whitespace_only():
    """纯空白内容应抛出 JSONDecodeError"""
    with pytest.raises(json.JSONDecodeError):
        _extract_json_with_reasoning("   \n\t  ")


def test_extract_no_json():
    """无任何 JSON 结构的纯文本应抛出 JSONDecodeError"""
    with pytest.raises(json.JSONDecodeError):
        _extract_json_with_reasoning("这是一段纯文本，没有任何 JSON 内容。")


def test_extract_marker_no_json_after():
    """标记后无 JSON 内容，应回退到 Tier 2/3"""
    content = "思考过程<<<JSON_RESULT>>>"
    with pytest.raises(json.JSONDecodeError):
        _extract_json_with_reasoning(content)


def test_extract_marker_invalid_json_after():
    """标记后 JSON 不合法，应回退到 Tier 2/3"""
    content = "思考<<<JSON_RESULT>>>{invalid json}"
    with pytest.raises(json.JSONDecodeError):
        _extract_json_with_reasoning(content)


# ============================================================
# 辅助函数单元测试
# ============================================================


def test_strip_code_fences_json():
    """_strip_code_fences: 去掉 ```json 围栏"""
    assert _strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_code_fences_plain():
    """_strip_code_fences: 去掉 ``` 围栏"""
    assert _strip_code_fences('```\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_code_fences_no_fence():
    """_strip_code_fences: 无围栏时原样返回"""
    assert _strip_code_fences('{"a": 1}') == '{"a": 1}'


def test_try_parse_json_valid():
    """_try_parse_json: 合法 JSON 返回解析结果"""
    assert _try_parse_json('{"a": 1}') == {"a": 1}


def test_try_parse_json_with_fence():
    """_try_parse_json: 带围栏的 JSON"""
    assert _try_parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_try_parse_json_invalid():
    """_try_parse_json: 非法 JSON 返回 None"""
    assert _try_parse_json("not json at all") is None


def test_try_parse_json_with_embedded_json():
    """_try_parse_json: 文本中嵌入的 JSON 块"""
    assert _try_parse_json('前文 {"a": 1} 后文') == {"a": 1}


def test_extract_largest_json_block_simple():
    """_extract_largest_json_block: 简单 JSON 块"""
    result = _extract_largest_json_block('前文 {"a": 1} 后文')
    assert result == {"a": 1}


def test_extract_largest_json_block_nested():
    """_extract_largest_json_block: 嵌套 JSON"""
    result = _extract_largest_json_block('{"outer": {"inner": 42}}')
    assert result == {"outer": {"inner": 42}}


def test_extract_largest_json_block_with_string_braces():
    """_extract_largest_json_block: 字符串中的花括号不干扰匹配"""
    result = _extract_largest_json_block('{"code": "if (x) { return; }"}')
    assert result == {"code": "if (x) { return; }"}


def test_extract_largest_json_block_no_json():
    """_extract_largest_json_block: 无 JSON 返回 None"""
    assert _extract_largest_json_block("纯文本无JSON") is None


def test_extract_largest_json_block_multiple_candidates():
    """_extract_largest_json_block: 多个候选，返回第一个合法的"""
    result = _extract_largest_json_block('{"first": 1} {"second": 2}')
    assert result == {"first": 1}


# ============================================================
# 真实场景模拟
# ============================================================


def test_realistic_deepseek_output_with_reasoning():
    """模拟 DeepSeek 输出：先推理再标记输出 JSON"""
    content = (
        "让我分析这个议题的核心矛盾。\n"
        "\n"
        "首先，从产品架构师的角度来看，系统需要支持异步任务处理以解耦耗时操作。\n"
        "其次，从工程师的角度来看，引入消息队列会增加系统复杂度。\n"
        "\n"
        "综合两方观点，我认为应该采用轻量级的本地异步方案。\n"
        "\n"
        "<<<JSON_RESULT>>>\n"
        '{"conflicts": [{"id": "c1", "type": "preference", '
        '"summary": "是否引入异步队列", "side_a": "架构师：需要", '
        '"side_b": "工程师：过度设计"}]}'
    )
    parsed, reasoning = _extract_json_with_reasoning(content)
    assert len(parsed["conflicts"]) == 1
    assert parsed["conflicts"][0]["id"] == "c1"
    assert "从产品架构师的角度" in reasoning


def test_realistic_qwen_output_with_richmedia():
    """模拟 Qwen 输出：<RichMediaReference> 前有思考内容"""
    content = "分析用户需求...\n确定技术方案...\n<RichMediaReference>"
    # 这个场景由 _call_api 处理 native_reasoning，extract 只负责 JSON
    # 如果没有 JSON，应该抛出异常
    with pytest.raises(json.JSONDecodeError):
        _extract_json_with_reasoning(content)


def test_realistic_minimal_output():
    """模拟最小化输出：只有 JSON，无推理"""
    content = '{"clarified_topic": "测试议题", "key_questions": ["Q1"], "team_config": [], "complexity": "fast"}'
    parsed, reasoning = _extract_json_with_reasoning(content)
    assert parsed["clarified_topic"] == "测试议题"
    assert reasoning == ""


def test_realistic_mixed_fence_and_marker():
    """模拟混合场景：标记后有围栏包裹的 JSON"""
    content = '分析完成。\n<<<JSON_RESULT>>>\n```json\n{"result": "mixed"}\n```'
    parsed, reasoning = _extract_json_with_reasoning(content)
    assert parsed == {"result": "mixed"}
    assert "分析完成" in reasoning
