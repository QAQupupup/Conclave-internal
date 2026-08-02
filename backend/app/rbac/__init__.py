"""Casbin RBAC 模块：RBAC with Domains 多租户权限。

- enforcer: AsyncEnforcer 单例初始化与获取
- policies: 默认策略 seed、角色 CRUD、角色级别比较
- deps: FastAPI 权限依赖（require_permission, require_system_admin）
- migrations: 数据库 DDL 迁移
"""

from app.rbac.deps import get_current_user, require_permission, require_system_admin
from app.rbac.enforcer import (
    SYSTEM_DOMAIN,
    get_enforcer,
    init_rbac,
    reload_policies,
    team_domain,
)
from app.rbac.migrations import ensure_rbac_tables
from app.rbac.policies import (
    ROLE_BANNED,
    ROLE_MAINTAINER,
    ROLE_MEMBER,
    ROLE_OWNER,
    ROLE_REPORTER,
    ROLE_SYSTEM_ADMIN,
    ROLE_SYSTEM_OWNER,
    ROLE_USER,
    TEAM_ROLE_WEIGHT,
    add_user_to_team_role,
    cleanup_tenant_policies,
    get_user_domains,
    get_user_roles_in_team,
    remove_user_from_team,
    remove_user_role_in_team,
    role_can_manage,
    seed_default_policies,
    seed_team_policies,
)

__all__ = [
    # policies
    "ROLE_BANNED",
    "ROLE_MAINTAINER",
    "ROLE_MEMBER",
    "ROLE_OWNER",
    "ROLE_REPORTER",
    "ROLE_SYSTEM_ADMIN",
    "ROLE_SYSTEM_OWNER",
    "ROLE_USER",
    # enforcer
    "SYSTEM_DOMAIN",
    "TEAM_ROLE_WEIGHT",
    "add_user_to_team_role",
    "cleanup_tenant_policies",
    # migrations
    "ensure_rbac_tables",
    # deps
    "get_current_user",
    "get_enforcer",
    "get_user_domains",
    "get_user_roles_in_team",
    "init_rbac",
    "reload_policies",
    "remove_user_from_team",
    "remove_user_role_in_team",
    "require_permission",
    "require_system_admin",
    "role_can_manage",
    "seed_default_policies",
    "seed_team_policies",
    "team_domain",
]
