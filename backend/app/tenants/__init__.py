"""多租户支持模块。

Phase 1b 实现：
- tenants 表：组织/租户
- User-Tenant 关联：users.tenant_id 外键
- TenantContext：ContextVar 保存当前 tenant_id
- 自动迁移：首次启动创建默认 tenant，关联现有用户
- DAO 过滤：app.tenants.dao 提供查询/写入时的租户隔离工具
"""
from app.tenants.context import (
    create_system_tenant_ctx,
    get_tenant_id,
    is_system_tenant,
    reset_tenant_ctx,
    set_tenant_id,
    tenant_filter,
)
from app.tenants.dao import (
    current_tenant_id,
    require_tenant_id,
    tenant_filter_clause,
    tenant_filter_params,
)
from app.tenants.models import TenantCreate, TenantInfo
from app.tenants.service import (
    create_default_tenant_for_existing_users,
    create_tenant,
    ensure_business_tables_tenant_id,
    ensure_tenants_table,
    get_default_tenant,
    get_tenant,
    get_tenant_by_slug,
)

__all__ = [
    "TenantCreate",
    "TenantInfo",
    "create_default_tenant_for_existing_users",
    "create_system_tenant_ctx",
    "create_tenant",
    "current_tenant_id",
    "ensure_business_tables_tenant_id",
    "ensure_tenants_table",
    "get_default_tenant",
    "get_tenant",
    "get_tenant_by_slug",
    "get_tenant_id",
    "is_system_tenant",
    "require_tenant_id",
    "reset_tenant_ctx",
    "set_tenant_id",
    "tenant_filter",
    "tenant_filter_clause",
    "tenant_filter_params",
]
