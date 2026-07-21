# 网络授权审批系统测试
# 验证：网络错误检测、申请创建、自动通过、手动批复、超时降级
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.net_auth import (
    create_auth_request,
    expire_pending_requests,
    get_auth_request,
    get_pending_for_meeting,
    init_auth_table,
    list_auth_requests,
    review_auth_request,
)
from app.net_auth_manager import (
    detect_network_failure,
    determine_needed_level,
    request_network_access,
)

# ---------- 网络错误检测 ----------


class TestDetectNetworkFailure:
    def test_connection_refused(self):
        """连接被拒绝 → 网络错误"""
        r = detect_network_failure(
            "urlopen error: [Errno 111] Connection refused",
            1,
            "import urllib.request; urllib.request.urlopen('https://example.com')",
        )
        assert r is not None
        assert "网络" in r or "connection" in r.lower()

    def test_dns_failure(self):
        """DNS 解析失败 → 网络错误"""
        r = detect_network_failure(
            "socket.gaierror: [Errno -2] Name or service not known",
            1,
            "import requests; requests.get('https://api.example.com')",
        )
        assert r is not None

    def test_module_not_found_requests(self):
        """ModuleNotFoundError: requests → 需要网络安装"""
        r = detect_network_failure(
            "ModuleNotFoundError: No module named 'requests'",
            1,
            "import requests",
        )
        assert r is not None
        assert "requests" in r

    def test_module_not_found_pandas_not_network(self):
        """ModuleNotFoundError: pandas → 非网络问题（数据科学镜像预装）"""
        r = detect_network_failure(
            "ModuleNotFoundError: No module named 'pandas'",
            1,
            "import pandas",
        )
        assert r is None, "pandas 是预装模块，不应触发网络申请"

    def test_syntax_error_not_network(self):
        """语法错误 → 非网络问题"""
        r = detect_network_failure(
            "SyntaxError: invalid syntax",
            1,
            "print('hello')",
        )
        assert r is None

    def test_success_exit_not_network(self):
        """执行成功 → 非网络问题"""
        r = detect_network_failure("", 0, "print('hello')")
        assert r is None


# ---------- 网络级别判断 ----------


class TestDetermineNeededLevel:
    def test_requests_needs_l3(self):
        """代码含 requests → L3"""
        level = determine_needed_level(
            "import requests; r = requests.get('https://api.example.com')",
            "网络连接失败",
        )
        assert level == "L3"

    def test_urllib_needs_l3(self):
        """代码含 urllib → L3"""
        level = determine_needed_level(
            "from urllib.request import urlopen",
            "网络连接失败",
        )
        assert level == "L3"

    def test_pip_install_needs_l2(self):
        """代码含 pip install → L2"""
        level = determine_needed_level(
            "import subprocess; subprocess.run(['pip', 'install', 'six'])",
            "pip install 需要网络",
        )
        assert level == "L2"

    def test_module_missing_needs_l2(self):
        """ModuleNotFoundError（非 HTTP 库）→ L2（需要安装依赖）"""
        level = determine_needed_level(
            "import six",
            "缺少模块 six，需要 pip install",
        )
        assert level == "L2"


# ---------- 申请单 CRUD ----------


class TestAuthRequestCRUD:
    async def test_create_and_get(self):
        """创建申请单并查询"""
        await init_auth_table()
        rid = f"auth-crud-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=120)

        await create_auth_request(
            request_id=rid,
            meeting_id="mtg-crud-test",
            stage="produce",
            code_snippet="import requests",
            requested_level="L3",
            detected_level="L1",
            failure_reason="网络连接失败",
            stderr_output="connection refused",
            expires_at=expires,
        )

        req = await get_auth_request(rid)
        assert req is not None
        assert req["id"] == rid
        assert req["meeting_id"] == "mtg-crud-test"
        assert req["status"] == "pending"
        assert req["requested_level"] == "L3"

    async def test_list_by_meeting(self):
        """按会议 ID 过滤列表"""
        await init_auth_table()
        mid = f"mtg-list-{uuid.uuid4().hex[:8]}"
        for i in range(3):
            await create_auth_request(
                request_id=f"auth-list-{mid}-{i}",
                meeting_id=mid,
                stage="produce",
                code_snippet="code",
                requested_level="L2",
                detected_level="L1",
                failure_reason="test",
                stderr_output="err",
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
            )

        reqs = await list_auth_requests(meeting_id=mid)
        assert len(reqs) >= 3

    async def test_list_by_status(self):
        """按状态过滤列表"""
        await init_auth_table()
        rid = f"auth-status-{uuid.uuid4().hex[:8]}"
        await create_auth_request(
            request_id=rid,
            meeting_id=f"mtg-status-{uuid.uuid4().hex[:8]}",
            stage="produce",
            code_snippet="code",
            requested_level="L2",
            detected_level="L1",
            failure_reason="test",
            stderr_output="err",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )

        pending = await list_auth_requests(status="pending")
        assert any(r["id"] == rid for r in pending)

    async def test_review_approved(self):
        """批复：批准"""
        await init_auth_table()
        rid = f"auth-approve-{uuid.uuid4().hex[:8]}"
        await create_auth_request(
            request_id=rid,
            meeting_id=f"mtg-approve-{uuid.uuid4().hex[:8]}",
            stage="produce",
            code_snippet="code",
            requested_level="L3",
            detected_level="L1",
            failure_reason="test",
            stderr_output="err",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )

        result = await review_auth_request(rid, "approved", "同意，继续执行")
        assert result["status"] == "approved"
        assert result["review_action"] == "approved"
        assert result["review_comment"] == "同意，继续执行"
        assert result["reviewed_at"] is not None

    async def test_review_denied(self):
        """批复：拒绝"""
        await init_auth_table()
        rid = f"auth-deny-{uuid.uuid4().hex[:8]}"
        await create_auth_request(
            request_id=rid,
            meeting_id=f"mtg-deny-{uuid.uuid4().hex[:8]}",
            stage="produce",
            code_snippet="code",
            requested_level="L3",
            detected_level="L1",
            failure_reason="test",
            stderr_output="err",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )

        result = await review_auth_request(rid, "denied", "不允许访问外部网络")
        assert result["status"] == "denied"

    async def test_review_already_reviewed(self):
        """重复批复：已批复的申请不能再批复"""
        await init_auth_table()
        rid = f"auth-double-{uuid.uuid4().hex[:8]}"
        await create_auth_request(
            request_id=rid,
            meeting_id=f"mtg-double-{uuid.uuid4().hex[:8]}",
            stage="produce",
            code_snippet="code",
            requested_level="L2",
            detected_level="L1",
            failure_reason="test",
            stderr_output="err",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )

        # 第一次批复
        await review_auth_request(rid, "approved", "ok")
        # 第二次批复（应无效，返回原始记录但 status 不变）
        result = await review_auth_request(rid, "denied", "changed mind")
        assert result["status"] == "approved"  # 仍是第一次的结果

    async def test_expire_pending(self):
        """过期检查：超时的 pending 申请标记为 expired"""
        await init_auth_table()
        rid = f"auth-expire-{uuid.uuid4().hex[:8]}"
        # 创建一个已过期的申请
        await create_auth_request(
            request_id=rid,
            meeting_id=f"mtg-expire-{uuid.uuid4().hex[:8]}",
            stage="produce",
            code_snippet="code",
            requested_level="L2",
            detected_level="L1",
            failure_reason="test",
            stderr_output="err",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),  # 已过期
        )

        expired = await expire_pending_requests()
        assert any(e["id"] == rid for e in expired)

        req = await get_auth_request(rid)
        assert req["status"] == "expired"

    async def test_get_pending_for_meeting(self):
        """获取某会议的 pending 申请"""
        await init_auth_table()
        rid = f"auth-pending-{uuid.uuid4().hex[:8]}"
        mid = f"mtg-pending-{uuid.uuid4().hex[:8]}"
        await create_auth_request(
            request_id=rid,
            meeting_id=mid,
            stage="produce",
            code_snippet="code",
            requested_level="L2",
            detected_level="L1",
            failure_reason="test",
            stderr_output="err",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )

        pending = await get_pending_for_meeting(mid)
        assert len(pending) >= 1
        assert all(p["status"] == "pending" for p in pending)


# ---------- 授权流程（自动通过/手动批复/超时） ----------


class TestAuthFlow:
    async def test_auto_approve(self, monkeypatch):
        """AUTO_APPROVE=1 时自动通过"""
        # 设置自动通过
        import app.net_auth_manager as nam

        monkeypatch.setattr(nam, "AUTO_APPROVE", True)

        await init_auth_table()
        result = await request_network_access(
            meeting_id="mtg-auto-approve",
            stage="produce",
            code="import requests; requests.get('https://api.example.com')",
            detected_level="L1",
            failure_reason="网络连接失败",
            stderr="connection refused",
        )

        assert result["approved"] is True
        assert result["level"] == "L3"
        assert "request_id" in result

        # DB 应有 approved 记录
        req = await get_auth_request(result["request_id"])
        assert req is not None
        assert req["status"] == "approved"
        assert "自动通过" in req["review_comment"]

    async def test_timeout_degrade(self, monkeypatch):
        """超时未批复 → 降级处理"""
        import app.net_auth_manager as nam

        monkeypatch.setattr(nam, "AUTO_APPROVE", False)
        monkeypatch.setattr(nam, "AUTH_TIMEOUT_SECONDS", 2)  # 2 秒超时

        await init_auth_table()
        result = await request_network_access(
            meeting_id="mtg-timeout-test",
            stage="produce",
            code="import requests",
            detected_level="L1",
            failure_reason="缺少模块 requests",
            stderr="ModuleNotFoundError: No module named 'requests'",
        )

        assert result["approved"] is False
        assert result.get("timeout") is True

    async def test_manual_approve(self, monkeypatch):
        """手动批复：创建申请 → 批准 → 等待方收到"""
        import app.net_auth_manager as nam

        monkeypatch.setattr(nam, "AUTO_APPROVE", False)
        monkeypatch.setattr(nam, "AUTH_TIMEOUT_SECONDS", 30)

        await init_auth_table()

        # 异步发起申请
        task = asyncio.create_task(
            request_network_access(
                meeting_id="mtg-manual-test",
                stage="produce",
                code="import requests",
                detected_level="L1",
                failure_reason="缺少模块 requests",
                stderr="ModuleNotFoundError: No module named 'requests'",
            )
        )

        # 等申请创建
        await asyncio.sleep(1)

        # 查 pending 并批准
        pending = await get_pending_for_meeting("mtg-manual-test")
        assert len(pending) >= 1
        reviewed = await review_auth_request(pending[0]["id"], "approved", "手动批准")
        assert reviewed["status"] == "approved"

        # 等待申请方收到结果
        result = await task
        assert result["approved"] is True

    async def test_manual_deny(self, monkeypatch):
        """手动批复：拒绝 → 返回 denied"""
        import app.net_auth_manager as nam

        monkeypatch.setattr(nam, "AUTO_APPROVE", False)
        monkeypatch.setattr(nam, "AUTH_TIMEOUT_SECONDS", 30)

        await init_auth_table()

        task = asyncio.create_task(
            request_network_access(
                meeting_id="mtg-deny-flow",
                stage="produce",
                code="import requests",
                detected_level="L1",
                failure_reason="缺少模块 requests",
                stderr="ModuleNotFoundError: No module named 'requests'",
            )
        )

        await asyncio.sleep(1)

        pending = await get_pending_for_meeting("mtg-deny-flow")
        assert len(pending) >= 1
        await review_auth_request(pending[0]["id"], "denied", "不允许联网")

        result = await task
        assert result["approved"] is False
        assert result.get("denied") is True
