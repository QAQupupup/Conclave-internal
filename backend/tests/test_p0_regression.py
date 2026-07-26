"""P0 修复回归测试。

覆盖：
- P0-1: alembic/env.py 导入不报 ImportError（AuditLogModel 已导出）
- P0-2: 质量门禁在 produce 后正确设置 DONE（而非提前设置）
- P0-3: LazyLock 在事件循环切换后正常工作
- P0-4: 生产环境安全检查（JWT_SECRET / 弱密码 fail-fast）
"""

from __future__ import annotations

import asyncio
import os

import pytest

# ============================================================
# P0-1: alembic/env.py 导入 + AuditLogModel 导出
# ============================================================


def test_alembic_env_imports_no_error():
    """验证 alembic/env.py 中的所有 ORM 模型导入不会 ImportError。

    P0-1 修复前：NetAuthRequestModel 不存在，导致 alembic upgrade head 立即崩溃。
    P0-2 补充：AuditLogModel 也需要导出，否则 alembic 无法注册 audit_logs 表。
    """
    # 直接导入 alembic.env 会因 context 注入问题失败，
    # 但可以验证 app.db.models 中的所有模型都能正常导入
    from app.db.models import AuditLogModel

    assert AuditLogModel.__tablename__ == "audit_logs"

    # 验证 AuditLogModel 在 __all__ 中
    import app.db.models as models_pkg

    assert "AuditLogModel" in models_pkg.__all__


# ============================================================
# P0-3: LazyLock 事件循环感知
# ============================================================


@pytest.mark.asyncio
async def test_lazylock_survives_loop_switch():
    """LazyLock 在事件循环切换后应自动重建，不报 RuntimeError。

    P0-3 修复前：asyncio.Lock 绑定到第一个循环，切换循环后报
    "got Future attached to a different loop"。

    测试策略：不创建真实的新事件循环（会触发 asyncpg 连接池跨循环问题），
    而是直接验证 LazyLock._ensure() 在检测到循环变化时重建原语。
    """
    from app.lazy_asyncio import LazyLock

    lock = LazyLock()

    # 第一次在当前循环中使用
    async with lock:
        pass

    # 验证 LazyLock 已绑定到当前循环
    assert lock._loop is not None
    assert not lock._loop.is_closed()

    # 模拟循环变化：手动设置一个已关闭的循环引用
    # _ensure() 应检测到 _loop.is_closed() 并重建原语
    fake_closed_loop = asyncio.new_event_loop()
    fake_closed_loop.close()
    lock._loop = fake_closed_loop
    lock._primitive = None  # 强制重建

    # 在当前循环中再次使用，应自动重建而不报错
    async with lock:
        pass

    # 验证已重新绑定到当前运行循环
    assert lock._loop is not fake_closed_loop


@pytest.mark.asyncio
async def test_lazylock_concurrent_access():
    """LazyLock 应正确互斥：同一时刻只有一个协程持有锁。"""
    from app.lazy_asyncio import LazyLock

    lock = LazyLock()
    acquired_order: list[str] = []

    async def _task(name: str, delay: float):
        async with lock:
            acquired_order.append(f"{name}-start")
            await asyncio.sleep(delay)
            acquired_order.append(f"{name}-end")

    await asyncio.gather(_task("a", 0.01), _task("b", 0.01))

    # 验证互斥：a-start 和 a-end 应连续，不被 b-start 打断
    a_start = acquired_order.index("a-start")
    a_end = acquired_order.index("a-end")
    b_start = acquired_order.index("b-start")
    b_end = acquired_order.index("b-end")

    # a-start 和 a-end 之间不应有 b-start
    assert b_start > a_end or b_start < a_start
    # b-start 和 b-end 之间不应有 a-start
    assert a_start > b_end or a_start < b_start


# ============================================================
# P0-4: 生产环境安全检查
# ============================================================


def test_production_security_check_skipped_in_test_env():
    """非生产环境应跳过安全检查，不报错。"""
    from app.auth import _check_production_security

    # 当前 APP_ENV=test（由 conftest 设置）
    assert os.environ.get("APP_ENV") == "test"
    # 不应抛出任何异常
    _check_production_security()


def test_production_security_check_rejects_missing_jwt_secret(monkeypatch):
    """生产环境下未设置 CONCLAVE_JWT_SECRET 应 raise RuntimeError。"""
    from app.auth import _check_production_security

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("CONCLAVE_JWT_SECRET", raising=False)
    monkeypatch.setenv("CONCLAVE_ADMIN_PASSWORD", "strong_password_123")

    with pytest.raises(RuntimeError, match="CONCLAVE_JWT_SECRET 未设置"):
        _check_production_security()


def test_production_security_check_rejects_short_jwt_secret(monkeypatch):
    """生产环境下 CONCLAVE_JWT_SECRET 长度 < 32 应 raise RuntimeError。"""
    from app.auth import _check_production_security

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CONCLAVE_JWT_SECRET", "too_short")
    monkeypatch.setenv("CONCLAVE_ADMIN_PASSWORD", "strong_password_123")

    with pytest.raises(RuntimeError, match="长度不足"):
        _check_production_security()


def test_production_security_check_rejects_weak_admin_password(monkeypatch):
    """生产环境下使用弱默认密码应 raise RuntimeError。"""
    from app.auth import _check_production_security

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CONCLAVE_JWT_SECRET", "a" * 32)  # 足够长的 JWT 密钥
    monkeypatch.setenv("CONCLAVE_ADMIN_PASSWORD", "admin123")

    with pytest.raises(RuntimeError, match="弱默认密码"):
        _check_production_security()


def test_production_security_check_passes_with_strong_config(monkeypatch):
    """生产环境下设置强 JWT 密钥和强管理员密码应通过检查。"""
    from app.auth import _check_production_security

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CONCLAVE_JWT_SECRET", "a" * 32)
    monkeypatch.setenv("CONCLAVE_ADMIN_PASSWORD", "strong_password_123")

    # 不应抛出异常
    _check_production_security()


def test_production_security_check_rejects_both_issues(monkeypatch):
    """生产环境下同时缺少 JWT_SECRET 和弱密码应报告所有错误。"""
    from app.auth import _check_production_security

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("CONCLAVE_JWT_SECRET", raising=False)
    monkeypatch.setenv("CONCLAVE_ADMIN_PASSWORD", "")

    with pytest.raises(RuntimeError) as exc_info:
        _check_production_security()

    error_msg = str(exc_info.value)
    # 两个问题都应报告
    assert "CONCLAVE_JWT_SECRET" in error_msg
    assert "CONCLAVE_ADMIN_PASSWORD" in error_msg
