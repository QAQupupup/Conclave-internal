"""Casbin 策略 seed 数据与角色管理 CRUD。

系统域策略在启动时 seed；Team 域策略在创建 Team 时写入。
所有公共函数内部通过 get_enforcer() 获取单例，无需调用方传入。

注意：使用 Casbin AsyncEnforcer 异步 API：
- add_policies(rules: list[list[str]]) 批量添加 p 策略
- add_grouping_policies(rules: list[list[str]]) 批量添加 g 策略
- add_policy(*params: str) 添加单条 p 策略
- add_grouping_policy(*params: str) 添加单条 g 策略
- remove_filtered_policy(field_index, *field_values) 按字段过滤删除 p 策略
- remove_filtered_grouping_policy(field_index, *field_values) 按字段过滤删除 g 策略
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.rbac.enforcer import SYSTEM_DOMAIN, get_enforcer, team_domain

if TYPE_CHECKING:
    import casbin

logger = logging.getLogger(__name__)

# ========== 系统级角色 ==========
ROLE_SYSTEM_OWNER = "system_owner"
ROLE_SYSTEM_ADMIN = "system_admin"
ROLE_USER = "user"

# ========== Team 级角色 ==========
ROLE_OWNER = "owner"
ROLE_MAINTAINER = "maintainer"
ROLE_MEMBER = "member"
ROLE_REPORTER = "reporter"
ROLE_BANNED = "banned"

# Team 角色权重（用于级别比较）
# 注意：权重差异要足够大，避免跨级管理
TEAM_ROLE_WEIGHT = {
    ROLE_OWNER: 100,
    ROLE_MAINTAINER: 70,
    ROLE_MEMBER: 30,
    ROLE_REPORTER: 10,
    ROLE_BANNED: 0,
}


def role_can_manage(actor_role: str, target_role: str) -> bool:
    """检查 actor_role 是否可以管理 target_role（即 actor 级别 > target 级别）。

    - owner 可以管理任何人（包括其他 maintainer）
    - maintainer 可以管理 member/reporter/banned，但不能管理 owner 或其他 maintainer
    - member/reporter 不能管理任何人
    """
    actor_w = TEAM_ROLE_WEIGHT.get(actor_role, 0)
    target_w = TEAM_ROLE_WEIGHT.get(target_role, 0)
    return actor_w > target_w


# ========== 系统域默认策略 ==========
# p 策略格式：[sub, dom, obj, act]
_SYSTEM_POLICIES: list[list[str]] = [
    # system_owner 拥有所有权限（通配）
    [ROLE_SYSTEM_OWNER, SYSTEM_DOMAIN, "*", "*"],
    # system_admin 权限
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:tenants", "list"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:tenants", "create"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:tenants", "update"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:users", "list"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:users", "create"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:users", "update"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:users", "ban"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:config", "read"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:config", "update"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:audit", "read"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "team:info", "read"],
    [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "team:members", "list"],
    # TODO(quota): Phase 3 启用时取消注释
    # [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:quotas", "*"],
    # [ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN, "system:feedbacks", "*"],
]

# g 策略格式：[user/role, role, dom]
_SYSTEM_GROUPING: list[list[str]] = [
    [ROLE_SYSTEM_OWNER, ROLE_SYSTEM_ADMIN, SYSTEM_DOMAIN],
]


# ========== Team 域默认策略（每个 Team 创建时写入） ==========
def _team_policies(dom: str) -> list[list[str]]:
    """生成指定 Team 域的默认权限策略。"""
    return [
        # owner 拥有 team:* 所有权限
        [ROLE_OWNER, dom, "team:info", "*"],
        [ROLE_OWNER, dom, "team:settings", "*"],
        [ROLE_OWNER, dom, "team:members", "*"],
        [ROLE_OWNER, dom, "team:meetings", "*"],
        [ROLE_OWNER, dom, "team:reports", "*"],
        [ROLE_OWNER, dom, "team:billing", "*"],
        [ROLE_OWNER, dom, "team:keys", "*"],
        # TODO(quota/feedback): Phase 3-4 启用时取消注释
        # [ROLE_OWNER, dom, "team:quotas", "*"],
        # [ROLE_OWNER, dom, "team:feedbacks", "*"],
        # [ROLE_OWNER, dom, "team:keys", "reveal"],
        # maintainer
        [ROLE_MAINTAINER, dom, "team:info", "read"],
        [ROLE_MAINTAINER, dom, "team:info", "update"],
        [ROLE_MAINTAINER, dom, "team:settings", "read"],
        [ROLE_MAINTAINER, dom, "team:settings", "update"],
        [ROLE_MAINTAINER, dom, "team:members", "list"],
        [ROLE_MAINTAINER, dom, "team:members", "invite"],
        [ROLE_MAINTAINER, dom, "team:members", "remove"],
        [ROLE_MAINTAINER, dom, "team:members", "update_role"],
        [ROLE_MAINTAINER, dom, "team:members", "ban"],
        [ROLE_MAINTAINER, dom, "team:members", "unban"],
        [ROLE_MAINTAINER, dom, "team:meetings", "create"],
        [ROLE_MAINTAINER, dom, "team:meetings", "read"],
        [ROLE_MAINTAINER, dom, "team:meetings", "delete"],
        [ROLE_MAINTAINER, dom, "team:meetings", "control"],
        [ROLE_MAINTAINER, dom, "team:reports", "read"],
        [ROLE_MAINTAINER, dom, "team:reports", "export"],
        [ROLE_MAINTAINER, dom, "team:billing", "read"],
        [ROLE_MAINTAINER, dom, "team:keys", "read"],
        [ROLE_MAINTAINER, dom, "team:keys", "manage"],
        # TODO(quota/feedback): Phase 3-4 启用时取消注释
        # [ROLE_MAINTAINER, dom, "team:quotas", "read"],
        # [ROLE_MAINTAINER, dom, "team:quotas", "update"],
        # [ROLE_MAINTAINER, dom, "team:feedbacks", "read"],
        # [ROLE_MAINTAINER, dom, "team:keys", "reveal"],
        # member
        [ROLE_MEMBER, dom, "team:info", "read"],
        [ROLE_MEMBER, dom, "team:settings", "read"],
        [ROLE_MEMBER, dom, "team:members", "list"],
        [ROLE_MEMBER, dom, "team:meetings", "read"],
        [ROLE_MEMBER, dom, "team:meetings", "create"],
        [ROLE_MEMBER, dom, "team:meetings", "control"],
        [ROLE_MEMBER, dom, "team:reports", "read"],
        [ROLE_MEMBER, dom, "team:keys", "read"],
        # TODO(quota/feedback): Phase 3-4 启用时取消注释
        # [ROLE_MEMBER, dom, "team:quotas", "read_own"],
        # [ROLE_MEMBER, dom, "team:feedbacks", "create"],
        # reporter
        [ROLE_REPORTER, dom, "team:info", "read"],
        [ROLE_REPORTER, dom, "team:members", "list"],
        [ROLE_REPORTER, dom, "team:meetings", "read"],
        [ROLE_REPORTER, dom, "team:reports", "read"],
        # TODO(feedback): Phase 4 启用时取消注释
        # [ROLE_REPORTER, dom, "team:feedbacks", "create"],
        # banned 无任何权限（不写策略，被封禁即无权限）
    ]


def _team_grouping(dom: str) -> list[list[str]]:
    """生成指定 Team 域的角色继承链。owner > maintainer > member > reporter。"""
    return [
        [ROLE_OWNER, ROLE_MAINTAINER, dom],
        [ROLE_MAINTAINER, ROLE_MEMBER, dom],
        [ROLE_MEMBER, ROLE_REPORTER, dom],
    ]


# ========== 公共 API ==========


async def seed_default_policies() -> None:
    """幂等写入系统域默认策略和角色继承。"""
    e = get_enforcer()
    await e.add_policies(_SYSTEM_POLICIES)
    await e.add_grouping_policies(_SYSTEM_GROUPING)
    await e.save_policy()
    logger.info("Casbin 默认策略 seed 完成")


async def seed_team_policies(tenant_id: int) -> None:
    """为新建 Team 写入角色继承链和默认权限策略。幂等。"""
    e = get_enforcer()
    dom = team_domain(tenant_id)
    await e.add_policies(_team_policies(dom))
    await e.add_grouping_policies(_team_grouping(dom))
    await e.save_policy()


async def add_user_to_team_role(user_id: int | str, tenant_id: int, role: str) -> bool:
    """将用户添加到指定 Team 的指定角色。返回是否新增成功。"""
    e = get_enforcer()
    dom = team_domain(tenant_id)
    uid = str(user_id)
    # 先移除该用户在该域的所有现有角色（避免角色叠加）
    await _remove_user_roles_in_domain(e, uid, dom)
    ok: bool = await e.add_grouping_policy(uid, role, dom)
    if ok:
        await e.save_policy()
    return ok


async def add_user_to_system_role(user_id: int | str, role: str) -> bool:
    """将用户添加到系统域指定角色。"""
    e = get_enforcer()
    uid = str(user_id)
    ok: bool = await e.add_grouping_policy(uid, role, SYSTEM_DOMAIN)
    if ok:
        await e.save_policy()
    return ok


async def remove_user_from_team(user_id: int | str, tenant_id: int) -> None:
    """移除用户在指定 Team 的所有角色。"""
    e = get_enforcer()
    dom = team_domain(tenant_id)
    await _remove_user_roles_in_domain(e, str(user_id), dom)
    await e.save_policy()


async def remove_user_role_in_team(user_id: int | str, role: str, tenant_id: int) -> bool:
    """移除用户在指定 Team 的特定角色。"""
    e = get_enforcer()
    dom = team_domain(tenant_id)
    ok: bool = await e.remove_grouping_policy(str(user_id), role, dom)
    if ok:
        await e.save_policy()
    return ok


async def get_user_roles_in_team(user_id: int | str, tenant_id: int) -> list[str]:
    """获取用户在指定 Team 的角色列表。"""
    e = get_enforcer()
    dom = team_domain(tenant_id)
    roles = await e.get_roles_for_user_in_domain(str(user_id), dom)
    return list(roles)


async def get_user_domains(user_id: int | str) -> list[str]:
    """获取用户所属的所有 domain（Team）。"""
    e = get_enforcer()
    all_g = e.get_grouping_policy()
    doms: set[str] = set()
    uid_str = str(user_id)
    for g_rule in all_g:
        if len(g_rule) >= 3 and g_rule[0] == uid_str:
            doms.add(g_rule[2])
    return list(doms)


async def cleanup_tenant_policies(tenant_id: int) -> None:
    """删除租户时清理所有相关 Casbin 策略。"""
    e = get_enforcer()
    dom = team_domain(tenant_id)
    # g 策略格式：[user, role, dom]，field_index=2 按 domain 字段过滤
    await e.remove_filtered_grouping_policy(2, "", "", dom)
    # p 策略格式：[sub, dom, obj, act]，field_index=1 按 dom 字段过滤
    await e.remove_filtered_policy(1, "", dom)
    await e.save_policy()
    logger.info("已清理租户 %d 的 Casbin 策略", tenant_id)


# ========== 内部工具 ==========


async def _remove_user_roles_in_domain(e: casbin.AsyncEnforcer, uid: str, dom: str) -> None:
    """移除用户在指定域的所有 g 策略（角色分配）。

    remove_filtered_grouping_policy(field_index, v0, v1, v2...)
    field_index=0 表示从 v0 开始匹配，g 策略格式：[user(v0), role(v1), domain(v2)]
    """
    await e.remove_filtered_grouping_policy(0, uid, "", dom)
