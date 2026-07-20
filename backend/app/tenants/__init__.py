"""多租户支持模块。

Phase 1b 实现：
- tenants 表：组织/租户
- User-Tenant 关联：users.tenant_id 外键
- TenantContext：ContextVar 保存当前 tenant_id
- 自动迁移：首次启动创建默认 tenant，关联现有用户
"""
from app.tenants.context import (
    create_system_tenant_ctx,
    get_tenant_id,
    reset_tenant_ctx,
    set_tenant_id,
    tenant_filter,
)
from app.tenants.models import TenantCreate, TenantInfo
from app.tenants.service import (
    create_default_tenant_for_existing_users,
    create_tenant,
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
    "ensure_tenants_table",
    "get_default_tenant",
    "get_tenant",
    "get_tenant_by_slug",
    "get_tenant_id",
    "reset_tenant_ctx",
    "set_tenant_id",
    "tenant_filter",
]
