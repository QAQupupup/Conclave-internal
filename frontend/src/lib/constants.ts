export const WS_HEARTBEAT_INTERVAL = 25_000;
export const WS_RECONNECT_BASE_DELAY = 1000;
export const WS_RECONNECT_MAX_DELAY = 30_000;

export const STAGE_LABELS: Record<string, string> = {
  clarify: '问题澄清',
  clarification: '问题澄清',
  intra_team: '内部讨论',
  cross_team: '跨组辩论',
  evidence_check: '证据核验',
  arbitrate: '仲裁裁决',
  produce: '成果产出',
};

export const STAGE_DESCRIPTIONS: Record<string, string> = {
  clarify: '主持人引导澄清问题范围与目标',
  clarification: '主持人引导澄清问题范围与目标',
  intra_team: '各小组内部展开讨论，形成初步观点',
  cross_team: '不同小组之间进行观点碰撞与辩论',
  evidence_check: '对关键论点进行证据交叉验证',
  arbitrate: '主持人综合各方意见，进行裁决',
  produce: '生成最终交付物',
};

export const ROLE_LABELS: Record<string, string> = {
  moderator: '主持人',
  product_architect: '产品架构师',
  architect: '产品架构师',
  engineer: '工程师',
  security_expert: '安全专家',
  security: '安全专家',
  data_engineer: '数据分析师',
  data: '数据分析师',
  ux_designer: 'UX 设计师',
  ux: 'UX 设计师',
  marketing_expert: '市场专家',
  marketing: '市场专家',
};

export const ROLE_AVATAR_COLORS: Record<string, string> = {
  moderator: 'var(--color-role-moderator)',
  product_architect: 'var(--color-role-architect)',
  architect: 'var(--color-role-architect)',
  engineer: 'var(--color-role-engineer)',
  security_expert: 'var(--color-role-security)',
  security: 'var(--color-role-security)',
  data_engineer: 'var(--color-role-data)',
  data: 'var(--color-role-data)',
  ux_designer: 'var(--color-role-ux)',
  ux: 'var(--color-role-ux)',
  marketing_expert: 'var(--color-role-marketing, var(--color-role-data))',
  marketing: 'var(--color-role-marketing, var(--color-role-data))',
};

export const MESSAGE_STREAM_DEBOUNCE_MS = 16; // ~60fps
export const VIRTUAL_OVERSCAN = 8;
export const MESSAGE_FETCH_PAGE_SIZE = 50;
