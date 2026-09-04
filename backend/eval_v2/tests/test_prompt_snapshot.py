"""ADR-015 Phase 1 eval_v2 侧测试：SuiteResult 字段 / SUTClient 快照获取 / Vault 导出。

无需运行中的 SUT 或 LLM。SUTClient 的 HTTP 行为用 httpx.MockTransport 模拟
（只 mock 外部传输层，不 mock 被测函数本身）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from eval_v2.models.result import SuiteResult
from eval_v2.runners.sut_client import SUTClient
from eval_v2.vault.exporter import export_to_vault

_SNAPSHOT_PAYLOAD = {
    "snapshot_id": "sha256:deadbeef",
    "timestamp": "2026-09-04T00:00:00+00:00",
    "git_commit": "abc1234",
    "git_dirty": True,
    "prompts": {
        "conclave_core.prompts": {"hash": "sha256:111", "length": 100},
        "agents.role_templates": {"hash": "sha256:222", "length": 200},
    },
}


def _make_client_with_transport(handler) -> SUTClient:
    """构造 SUTClient 并注入基于 MockTransport 的 httpx 客户端。"""
    sut = SUTClient(base_url="http://sut.test")
    sut._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return sut


class TestSuiteResultSnapshotFields:
    def test_backward_compatible_defaults(self):
        """旧格式数据（无快照字段）可正常构造，默认值为空。"""
        r = SuiteResult(suite_id="s1")
        assert r.prompt_snapshot_id == ""
        assert r.prompt_snapshot == {}
        assert r.git_commit == ""
        assert r.git_dirty is False

    def test_roundtrip_serialization(self):
        """带快照字段的序列化/反序列化往返后字段不变。"""
        r = SuiteResult(
            suite_id="s2",
            prompt_snapshot_id="sha256:deadbeef",
            prompt_snapshot=_SNAPSHOT_PAYLOAD["prompts"],
            git_commit="abc1234",
            git_dirty=True,
        )
        data = r.model_dump(mode="json")
        restored = SuiteResult.model_validate(data)
        assert restored.prompt_snapshot_id == "sha256:deadbeef"
        assert restored.prompt_snapshot == _SNAPSHOT_PAYLOAD["prompts"]
        assert restored.git_commit == "abc1234"
        assert restored.git_dirty is True


class TestSUTClientPromptSnapshot:
    def test_success_returns_payload(self):
        """200 时返回完整快照 payload。"""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/system/prompts/snapshot"
            return httpx.Response(200, json=_SNAPSHOT_PAYLOAD)

        sut = _make_client_with_transport(handler)
        result = asyncio.run(sut.get_prompt_snapshot())
        assert result["snapshot_id"] == "sha256:deadbeef"
        assert result["prompts"]["conclave_core.prompts"]["hash"] == "sha256:111"

    def test_404_returns_empty(self):
        """旧版 SUT 无该端点时返回 {}，不抛异常（向后兼容）。"""
        sut = _make_client_with_transport(lambda req: httpx.Response(404))
        assert asyncio.run(sut.get_prompt_snapshot()) == {}

    def test_connect_timeout_returns_empty(self):
        """连接超时返回 {}，不中断评估流程（异常路径）。"""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("boom")

        sut = _make_client_with_transport(handler)
        assert asyncio.run(sut.get_prompt_snapshot()) == {}


class TestVaultExportSnapshot:
    def test_markdown_contains_snapshot_section(self, tmp_path):
        """带快照的结果导出后，Markdown 含 Prompt Snapshot 小节。"""
        r = SuiteResult(
            suite_id="snap-001",
            prompt_snapshot_id="sha256:deadbeef",
            prompt_snapshot=_SNAPSHOT_PAYLOAD["prompts"],
            git_commit="abc1234",
            git_dirty=True,
        )
        config = {"vault": {"root_path": str(tmp_path), "eval_dir": "eval-history"}}
        md_path = export_to_vault(r, config)

        content = Path(md_path).read_text(encoding="utf-8")
        assert "## Prompt Snapshot (ADR-015)" in content
        assert "sha256:deadbeef" in content
        assert "abc1234" in content
        assert "Prompt Files: 2" in content

    def test_markdown_omits_section_without_snapshot(self, tmp_path):
        """无快照的旧格式结果不渲染空小节（边界）。"""
        r = SuiteResult(suite_id="snap-002")
        config = {"vault": {"root_path": str(tmp_path), "eval_dir": "eval-history"}}
        md_path = export_to_vault(r, config)
        content = Path(md_path).read_text(encoding="utf-8")
        assert "## Prompt Snapshot" not in content
