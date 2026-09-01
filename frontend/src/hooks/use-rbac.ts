/**
 * useRbac：RBAC 权限辅助 Hook。
 *
 * 提供：
 * - 当前用户在当前 Team 的角色
 * - 系统管理员判断
 * - 权限判断函数（can）
 * - 可管理角色列表（用于角色下拉）
 */
import { useMemo } from 'react';
import { useAuthStore } from '@/stores/auth-slice';
import {
  TEAM_ROLE_META,
  canManageRole,
  getAssignableRoles,
  type TeamRole,
} from '@/types/rbac';

export interface RbacHelpers {
  /** 当前 Team 角色（owner/maintainer/member/reporter/banned 或空） */
  teamRole: TeamRole | '';
  /** 是否系统管理员（system_owner / system_admin） */
  isSystemAdmin: boolean;
  /** 是否系统所有者（system_owner，最高权限） */
  isSystemOwner: boolean;
  /** 是否当前 Team 的 owner */
  isTeamOwner: boolean;
  /** 是否当前 Team 的 maintainer 或以上 */
  canManageMembers: boolean;
  /** 是否可编辑 Team 设置 */
  canEditSettings: boolean;
  /** 是否可发起会议 */
  canCreateMeeting: boolean;
  /** 是否可查看所有会议（包括他人创建的） */
  canViewAllMeetings: boolean;
  /** 是否可以管理某个角色（用于成员管理操作按钮的显示） */
  canManage: (targetRole: TeamRole | string) => boolean;
  /** 获取当前角色可分配的角色列表 */
  assignableRoles: TeamRole[];
  /** 角色元数据 */
  roleMeta: typeof TEAM_ROLE_META;
}

export function useRbac(): RbacHelpers {
  const user = useAuthStore((s) => s.user);

  return useMemo<RbacHelpers>(() => {
    const systemRole = user?.system_role || user?.role || 'user';
    const isSystemOwner = systemRole === 'system_owner';
    const isSystemAdmin = isSystemOwner || systemRole === 'system_admin' || systemRole === 'admin';

    // 当前 Team 角色：从 user.roles 数组取第一个；system_owner 在任何 Team 视为 owner
    let teamRole: TeamRole | '' = '';
    if (isSystemOwner) {
      teamRole = 'owner';
    } else if (isSystemAdmin) {
      teamRole = 'maintainer';
    } else if (user?.roles && user.roles.length > 0) {
      const r = user.roles[0];
      if (r in TEAM_ROLE_META) teamRole = r as TeamRole;
    } else if (user?.tenants) {
      // 从 tenants 列表中找当前 tenant 的角色
      const tid = user.tenant_id;
      const cur = user.tenants.find((t) => String(t.id) === String(tid));
      if (cur && cur.role in TEAM_ROLE_META) teamRole = cur.role as TeamRole;
    }

    const roleWeight = teamRole ? TEAM_ROLE_META[teamRole].weight : 0;
    const isTeamOwner = teamRole === 'owner';
    const canManageMembers = roleWeight >= TEAM_ROLE_META.maintainer.weight;
    const canEditSettings = roleWeight >= TEAM_ROLE_META.maintainer.weight;
    const canCreateMeeting = roleWeight >= TEAM_ROLE_META.member.weight;
    const canViewAllMeetings = roleWeight >= TEAM_ROLE_META.member.weight;

    const canManage = (targetRole: TeamRole | string) => {
      if (isSystemOwner) return true;
      if (!teamRole) return false;
      return canManageRole(teamRole, targetRole);
    };

    const assignableRoles = getAssignableRoles(teamRole);

    return {
      teamRole,
      isSystemAdmin,
      isSystemOwner,
      isTeamOwner,
      canManageMembers,
      canEditSettings,
      canCreateMeeting,
      canViewAllMeetings,
      canManage,
      assignableRoles,
      roleMeta: TEAM_ROLE_META,
    };
  }, [user]);
}
