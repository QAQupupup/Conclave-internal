// ========== RBAC / Team 多租户类型 ==========

export type SystemRole = 'system_owner' | 'system_admin' | 'user';
export type TeamRole = 'owner' | 'maintainer' | 'member' | 'reporter' | 'banned';

export interface TeamMember {
  user_id: number;
  username: string;
  display_name?: string;
  email?: string;
  role: TeamRole;
  is_banned: boolean;
  joined_at: string;
  invited_by?: number;
}

export interface TeamDetail {
  id: number;
  name: string;
  slug: string;
  description: string;
  plan: string;
  is_active: boolean;
  owner_id: number;
  created_at: string;
  settings: Record<string, unknown>;
  my_role?: TeamRole;
  member_count?: number;
}

export interface TeamListResponse {
  items: TeamDetail[];
}

export interface TeamMemberListResponse {
  items: TeamMember[];
  total: number;
  page: number;
  page_size: number;
  my_role?: TeamRole;
}

export interface EffectiveConfig {
  llm_model?: string;
  llm_base_url?: string;
  embed_model?: string;
  rerank_model?: string;
  web_search_mode?: string;
  ui_theme?: string;
  ui_language?: string;
  // 权限标志（前端用于条件渲染）
  can_create_meeting?: boolean;
  can_manage_members?: boolean;
  can_edit_settings?: boolean;
  [key: string]: unknown;
}

// ========== Role 元数据（用于 UI 展示） ==========

export interface TeamRoleMeta {
  value: TeamRole;
  label: string;
  description: string;
  badgeClass: string;
  weight: number;
}

export const TEAM_ROLE_META: Record<TeamRole, TeamRoleMeta> = {
  owner: {
    value: 'owner',
    label: '所有者',
    description: '拥有 Team 全部权限',
    badgeClass: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
    weight: 100,
  },
  maintainer: {
    value: 'maintainer',
    label: '维护者',
    description: '可管理成员、会议和设置',
    badgeClass: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300',
    weight: 70,
  },
  member: {
    value: 'member',
    label: '成员',
    description: '可发起会议、查看报告',
    badgeClass: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
    weight: 30,
  },
  reporter: {
    value: 'reporter',
    label: '记者',
    description: '仅可查看会议和报告',
    badgeClass: 'bg-sky-100 text-sky-800 dark:bg-sky-900/30 dark:text-sky-300',
    weight: 10,
  },
  banned: {
    value: 'banned',
    label: '已封禁',
    description: '无法访问该 Team',
    badgeClass: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
    weight: 0,
  },
};

/**
 * 判断当前角色是否可以管理目标角色。
 * 规则：actor 权重大于 target 才可管理；
 * owner 可管理任何人；maintainer 可管理 member/reporter/banned。
 */
export function canManageRole(actorRole: TeamRole | string, targetRole: TeamRole | string): boolean {
  const a = TEAM_ROLE_META[actorRole as TeamRole]?.weight ?? 0;
  const t = TEAM_ROLE_META[targetRole as TeamRole]?.weight ?? 0;
  return a > t;
}

/**
 * 获取角色可分配的下级角色列表（用于角色选择下拉）。
 */
export function getAssignableRoles(actorRole: TeamRole | string): TeamRole[] {
  const myWeight = TEAM_ROLE_META[actorRole as TeamRole]?.weight ?? 0;
  return (Object.keys(TEAM_ROLE_META) as TeamRole[]).filter(
    (r) => TEAM_ROLE_META[r].weight < myWeight && r !== 'banned'
  );
}
