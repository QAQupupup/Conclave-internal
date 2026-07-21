"""DAO 层多租户过滤工具。

提供：
- tenant_id 参数注入辅助（写操作时自动附加当前租户 ID）
- 查询过滤条件构造
- 系统租户绕过机制（后台任务/管理接口）

使用方式：
```
from app.tenants.dao import current_tenant_id, tenant_scoped_query, with_tenant

# 写操作：
meeting["tenant_id"] = current_tenant_id()

# 读操作：
params = {"owner": username, **tenant_filter_params()}
where = "owner_username = :owner AND tenant_id = :tenant_id"
# 系统租户下 tenant_id = :tenant_id 被替换为 TRUE
```
"""
from __future__ import annotations

from typing import Any

from app.tenants.context import get_tenant_id, is_system_tenant


def current_tenant_id() -> int | None:
    """获取当前租户 ID（用于写操作时填充 tenant_id 字段）。

    系统租户模式下返回 None（调用方需自行处理，通常是管理操作）。
    """
    if is_system_tenant():
        return None
    return get_tenant_id()


def tenant_filter_clause(column: str = "tenant_id", param: str = "tenant_id") -> tuple[str, dict[str, Any]]:
    """生成租户过滤 WHERE 子句和参数。

    返回 (sql_snippet, params_dict)，可直接拼入 SQL 查询。

    - 系统租户：返回 ("TRUE", {})，即不过滤
    - 已设置 tenant_id：返回 ("{column} = :{param}", {param: tid})
    - 未设置 tenant_id（异常情况）：返回 ("FALSE", {})，即匹配不到任何行（防数据泄露）
    """
    if is_system_tenant():
        return "TRUE", {}
    tid = get_tenant_id()
    if tid is None:
        return "FALSE", {}
    return f"{column} = :{param}", {param: tid}


def tenant_filter_params() -> dict[str, Any]:
    """返回租户过滤参数 dict（适用于固定使用 :tenant_id 作为参数名的场景）。"""
    if is_system_tenant():
        return {}
    tid = get_tenant_id()
    if tid is None:
        # 返回不可能匹配的值（防御性）
        return {"tenant_id": -1}
    return {"tenant_id": tid}


def require_tenant_id() -> int:
    """获取当前租户 ID，若未设置则抛出 RuntimeError。

    用于写操作必须绑定租户的场景（创建 meeting、message 等）。
    """
    tid = current_tenant_id()
    if tid is None:
        raise RuntimeError("当前操作需要在租户上下文中执行，但未设置 tenant_id")
    return tid
