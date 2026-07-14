"""MeetingCharter 锚点注入测试

测试覆盖：
1. to_prompt_anchor 生成格式正确性
2. charter 不可变性（original_topic 不可篡改）
3. constraints 加载和注入
4. forbidden_topics 注入
5. check_drift 漂移检测（major/minor/none）
6. register_borrow / is_already_borrowed 借调防重复
7. _load_constraints_from_file 安全加载（文件大小、注入过滤）
8. build_charter_from_clarify 完整流程
9. 空 charter 边界情况
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from conclave_core.charter import (
    DEFAULT_CONSTRAINTS,
    MeetingCharter,
    build_charter_from_clarify,
    _load_constraints_from_file,
)
from conclave_core import charter as charter_module
from conclave_core.charter_logic import (
    to_prompt_anchor,
    check_drift,
    register_borrow,
    is_already_borrowed,
    _scope_keywords,
)


# ============================================================
# 1. to_prompt_anchor 格式测试
# ============================================================

class TestToPromptAnchor:
    """锚点文本生成格式验证"""

    def test_basic_anchor_contains_all_fields(self):
        """锚点应包含所有非空字段"""
        charter = MeetingCharter(
            meeting_id="m1",
            original_topic="原始议题",
            clarified_topic="澄清议题",
            meeting_goal="达成共识",
            scope=["边界1", "边界2"],
            constraints=["约束1", "约束2"],
            forbidden_topics=["禁止A"],
            borrow_history=["角色1::approved"],
        )
        anchor = to_prompt_anchor(charter)
        assert "【会议宪章锚点" in anchor
        assert "原始议题：原始议题" in anchor
        assert "澄清议题：澄清议题" in anchor
        assert "会议目标：达成共识" in anchor
        assert "边界1" in anchor and "边界2" in anchor
        assert "约束1" in anchor and "约束2" in anchor
        assert "禁止A" in anchor
        assert "角色1::approved" in anchor

    def test_anchor_with_empty_fields(self):
        """空字段应优雅降级"""
        charter = MeetingCharter(
            meeting_id="m2",
            original_topic="只有原始议题",
        )
        anchor = to_prompt_anchor(charter)
        assert "原始议题：只有原始议题" in anchor
        assert "澄清议题" not in anchor
        assert "议题边界：未限定" in anchor
        assert "行为约束：无" in anchor
        # "禁止话题" 出现在结尾指令中，但不应作为独立字段行
        assert "禁止话题：" not in anchor

    def test_anchor_ends_with_instruction(self):
        """锚点应以不得漂移指令结尾"""
        charter = MeetingCharter(meeting_id="m3", original_topic="test")
        anchor = to_prompt_anchor(charter)
        assert "不得扩展到边界外" in anchor


# ============================================================
# 2. MeetingCharter 不可变性
# ============================================================

class TestCharterImmutability:
    """original_topic 不可篡改验证"""

    def test_original_topic_cannot_be_modified(self):
        """Pydantic BaseModel 默认可变，但 original_topic 语义上不可篡改"""
        charter = MeetingCharter(
            meeting_id="m1",
            original_topic="用户原始输入",
        )
        # original_topic 应该始终是用户原始输入
        assert charter.original_topic == "用户原始输入"

    def test_clarified_topic_defaults_to_original(self):
        """未提供 clarified_topic 时应默认为 original_topic"""
        charter = build_charter_from_clarify(
            meeting_id="m1",
            original_topic="原始",
            clarified_topic="",
        )
        assert charter.clarified_topic == "原始"


# ============================================================
# 3. constraints 加载和注入
# ============================================================

class TestConstraintsLoading:
    """行为约束加载验证"""

    def test_default_constraints_loaded(self):
        """无外部约束文件时应加载默认约束"""
        with patch.object(charter_module, "_CONSTRAINTS_FILE", "/nonexistent/path.yaml"):
            constraints = _load_constraints_from_file()
            assert constraints == DEFAULT_CONSTRAINTS
            assert len(constraints) > 0

    def test_custom_constraints_from_yaml(self, tmp_path):
        """从 YAML 文件加载自定义约束"""
        yaml_content = """
constraints:
  - text: "自定义约束1"
  - text: "自定义约束2"
"""
        constraint_file = tmp_path / "constraints.yaml"
        constraint_file.write_text(yaml_content, encoding="utf-8")

        with patch.object(charter_module, "_CONSTRAINTS_FILE", str(constraint_file)):
            constraints = _load_constraints_from_file()
            assert "自定义约束1" in constraints
            assert "自定义约束2" in constraints

    def test_template_injection_filtered(self, tmp_path):
        """模板注入模式应被过滤"""
        yaml_content = """
constraints:
  - text: "{{ exec('import os') }}"
  - text: "{% import os %}"
  - text: "__import__('os')"
  - text: "正常约束"
"""
        constraint_file = tmp_path / "constraints.yaml"
        constraint_file.write_text(yaml_content, encoding="utf-8")

        with patch.object(charter_module, "_CONSTRAINTS_FILE", str(constraint_file)):
            constraints = _load_constraints_from_file()
            # 注入模式应被替换为 [FILTERED]
            assert any("[FILTERED]" in c for c in constraints)
            # 正常约束应保留
            assert "正常约束" in constraints

    def test_file_size_limit(self, tmp_path):
        """超过 1MB 的约束文件应回退到默认"""
        constraint_file = tmp_path / "huge.yaml"
        constraint_file.write_text("x: " + "A" * (2 * 1024 * 1024), encoding="utf-8")

        with patch.object(charter_module, "_CONSTRAINTS_FILE", str(constraint_file)):
            constraints = _load_constraints_from_file()
            assert constraints == DEFAULT_CONSTRAINTS

    def test_max_constraints_limit(self, tmp_path):
        """约束数量超过上限应截断"""
        items = [{"text": f"约束{i}"} for i in range(100)]
        yaml_content = "constraints:\n" + "\n".join(f"  - text: \"{item['text']}\"" for item in items)
        constraint_file = tmp_path / "many.yaml"
        constraint_file.write_text(yaml_content, encoding="utf-8")

        with patch.object(charter_module, "_CONSTRAINTS_FILE", str(constraint_file)):
            constraints = _load_constraints_from_file()
            assert len(constraints) <= 50

    def test_invalid_yaml_falls_back(self, tmp_path):
        """无效 YAML 应回退到默认约束"""
        constraint_file = tmp_path / "invalid.yaml"
        constraint_file.write_text("{{invalid yaml", encoding="utf-8")

        with patch.object(charter_module, "_CONSTRAINTS_FILE", str(constraint_file)):
            constraints = _load_constraints_from_file()
            assert constraints == DEFAULT_CONSTRAINTS


# ============================================================
# 4. check_drift 漂移检测
# ============================================================

class TestCheckDrift:
    """漂移检测逻辑验证"""

    def _make_charter(self, **kwargs) -> MeetingCharter:
        defaults = {
            "meeting_id": "m1",
            "original_topic": "API设计",
            "clarified_topic": "REST API 设计规范",
            "scope": ["REST", "API", "端点"],
        }
        defaults.update(kwargs)
        return MeetingCharter(**defaults)

    def test_no_drift_on_topic(self):
        """发言在议题范围内，无漂移"""
        charter = self._make_charter()
        result = check_drift(charter, "我们需要设计 REST API 端点的认证方案")
        assert not result.is_drift

    def test_major_drift_on_forbidden_topic(self):
        """触及禁止话题，重大漂移"""
        charter = self._make_charter(forbidden_topics=["政治", "宗教"])
        result = check_drift(charter, "这个问题和政治有关")
        assert result.is_drift
        assert result.severity == "major"
        assert "政治" in result.reason

    def test_minor_drift_on_off_topic(self):
        """发言不含任何 scope 关键词，轻微漂移"""
        charter = self._make_charter(scope=["Python", "算法"])
        result = check_drift(charter, "今天天气真好啊")
        assert result.is_drift
        assert result.severity == "minor"

    def test_no_drift_with_empty_content(self):
        """空内容不应判定为漂移"""
        charter = self._make_charter()
        result = check_drift(charter, "")
        assert not result.is_drift

    def test_no_drift_with_empty_scope(self):
        """scope 和 clarified_topic 都为空时不做关键词检测"""
        charter = self._make_charter(scope=[], clarified_topic="")
        result = check_drift(charter, "完全无关的内容")
        assert not result.is_drift


# ============================================================
# 5. register_borrow / is_already_borrowed
# ============================================================

class TestBorrowTracking:
    """借调防重复验证"""

    def test_register_borrow(self):
        """注册借调后应能检测到已借调"""
        charter = MeetingCharter(meeting_id="m1", original_topic="test")
        assert not is_already_borrowed(charter, "architect")
        register_borrow(charter, "architect", "approved")
        assert is_already_borrowed(charter, "architect")

    def test_register_borrow_no_duplicate(self):
        """重复注册同一角色不应产生多条记录"""
        charter = MeetingCharter(meeting_id="m1", original_topic="test")
        register_borrow(charter, "architect", "approved")
        register_borrow(charter, "architect", "rejected")
        count = sum(1 for e in charter.borrow_history if e.startswith("architect::"))
        assert count == 1

    def test_register_empty_role_ignored(self):
        """空角色名应被忽略"""
        charter = MeetingCharter(meeting_id="m1", original_topic="test")
        register_borrow(charter, "", "approved")
        assert len(charter.borrow_history) == 0


# ============================================================
# 6. build_charter_from_clarify 完整流程
# ============================================================

class TestBuildCharterFromClarify:
    """宪章构造完整流程验证"""

    def test_full_charter_build(self):
        """完整构造宪章"""
        with patch.object(charter_module, "_CONSTRAINTS_FILE", "/nonexistent"):
            charter = build_charter_from_clarify(
                meeting_id="meeting-123",
                original_topic="设计用户认证系统",
                clarified_topic="OAuth 2.0 认证方案设计",
                key_questions=["Token 过期策略", "刷新机制"],
                extra_constraints=["必须支持多租户"],
                forbidden_topics=["非认证相关"],
            )
            assert charter.meeting_id == "meeting-123"
            assert charter.original_topic == "设计用户认证系统"
            assert charter.clarified_topic == "OAuth 2.0 认证方案设计"
            assert "OAuth 2.0 认证方案设计" in charter.scope
            assert "Token 过期策略" in charter.scope
            assert "必须支持多租户" in charter.constraints
            assert "非认证相关" in charter.forbidden_topics
            assert charter.borrow_history == []

    def test_charter_anchor_injects_into_prompt(self):
        """构造的 charter 生成锚点后应包含所有关键信息"""
        with patch.object(charter_module, "_CONSTRAINTS_FILE", "/nonexistent"):
            charter = build_charter_from_clarify(
                meeting_id="m1",
                original_topic="设计API",
                clarified_topic="RESTful API 设计",
                key_questions=["版本管理"],
            )
            anchor = to_prompt_anchor(charter)
            assert "RESTful API 设计" in anchor
            assert "版本管理" in anchor
            assert "【会议宪章锚点" in anchor
