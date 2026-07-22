"""内置插件目录。

Phase 0 阶段留空。Phase 1a 开始在此目录下放 core / cross_cutting 插件：
- auth_tenant/
- billing/
- audit_compliance/
- team_collab/
- branding/
- data_residency/

插件以子目录形式组织，每个子目录是一个 Python 包，包含 __init__.py 和 plugin.py
（插件主类继承 app.plugins.core.PluginBase）。
"""

from __future__ import annotations
