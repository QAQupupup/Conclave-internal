"""eval 目录专用 conftest.py

本目录的测试是对「已部署的 Conclave 服务」做黑盒 HTTP 评估，
不依赖 app 内部模块、不创建测试数据库、不 truncate 表。

通过 --confcutdir=eval 运行时，pytest 不会加载 backend/conftest.py，
避免其 session 级 fixture 对 dev 数据库做 TRUNCATE 破坏。

运行方式（容器内）：
  cd /app && python -m pytest eval/test_deployable_service.py -v --confcutdir=eval

运行方式（宿主机，需服务已启动）：
  cd backend && python -m pytest eval/test_deployable_service.py -v --confcutdir=eval
"""

from __future__ import annotations


# 仅注册 marker，不做任何数据库 / app 初始化
def pytest_configure(config):
    config.addinivalue_line("markers", "real_llm: 需要真实 LLM 的测试（设置 CONCLAVE_EVAL_REAL_LLM=1 启用）")
    config.addinivalue_line("markers", "slow: 耗时较长的测试（默认运行，可用 -k 'not slow' 跳过）")
