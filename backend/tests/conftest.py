"""共享测试 fixtures。

核心原则：
- 默认使用 stub/mock，不调用真实 LLM
- 如需真实 LLM，显式使用 test_real_llm_e2e.py 或设置 CONCLAVE_USE_REAL_LLM=1
"""
from __future__ import annotations

import pytest


@pytest.fixture
def sample_wiki_topic() -> str:
    """来自历史会议的真实议题"""
    return "开发一个基于FastAPI和React的个人Wiki系统，涵盖文档管理、归档、回顾、分析、时间线统计、Markdown和图表功能"


@pytest.fixture
def sample_stock_topic() -> str:
    return "分析苹果公司（AAPL）股票未来三个月走势，包含技术面、基本面和舆情风险"


@pytest.fixture(autouse=True)
def _dispose_db_resources_after_test():
    """每个测试结束后释放数据库连接资源，避免跨测试泄漏。"""
    yield
    try:
        from app.db.engine import dispose_async_engine
        from app.db_legacy import close_db_pool
        dispose_async_engine()
        close_db_pool()
    except Exception:
        pass
