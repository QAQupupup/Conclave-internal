"""插件异常类单元测试。"""

from __future__ import annotations

from app.plugins.core.exceptions import (
    AccessDenied,
    ConclaveException,
    PluginDependencyError,
    PluginLoadError,
    PluginRejected,
    QuotaExceeded,
    SetupRequired,
)


def test_conclave_exception_defaults():
    e = ConclaveException("boom")
    assert e.message == "boom"
    assert e.code == "PLUGIN_ERROR"
    assert e.status_code == 500
    assert e.details == {}
    assert str(e) == "boom"


def test_derived_exceptions():
    assert PluginRejected("no").status_code == 403
    assert SetupRequired().status_code == 403
    assert QuotaExceeded().status_code == 429
    assert AccessDenied().status_code == 403


def test_plugin_load_error_details():
    e = PluginLoadError("auth", "import failed")
    assert e.code == "PLUGIN_LOAD_ERROR"
    assert e.details["plugin_name"] == "auth"
    assert e.details["reason"] == "import failed"


def test_plugin_dependency_error():
    e = PluginDependencyError("cycle: a->b->a")
    assert e.code == "PLUGIN_DEPENDENCY_ERROR"
    assert "cycle" in e.message
