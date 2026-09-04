export const WS_HEARTBEAT_INTERVAL = 25_000;
export const WS_RECONNECT_BASE_DELAY = 1000;
export const WS_RECONNECT_MAX_DELAY = 30_000;

export const STAGE_LABELS: Record<string, string> = {
  clarification: '问题澄清',
  intra_team: '内部讨论',
  cross_team: '跨组辩论',
  evidence_check: '证据核验',
  arbitrate: '仲裁裁决',
  produce: '成果产出',
};

export const STAGE_DESCRIPTIONS: Record<string, string> = {
  clarification: '主持人引导澄清问题范围与目标',
  intra_team: '各小组内部展开讨论，形成初步观点',
  cross_team: '不同小组之间进行观点碰撞与辩论',
  evidence_check: '对关键论点进行证据交叉验证',
  arbitrate: '主持人综合各方意见，进行裁决',
  produce: '生成最终交付物',
};

/**
 * 规范化阶段 ID。
 *
 * 后端编排器使用 `clarify` 作为首阶段 ID，前端统一以 `clarification` 为规范拼写
 * （与 STAGE_LABELS / STAGE_DESCRIPTIONS / mock 数据保持一致）。
 * 在接收后端 stage 的边界点统一调用，避免维护两份标签。
 */
export function normalizeStageId(stage: string): string {
  return stage === 'clarify' ? 'clarification' : stage;
}

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

// ---------------------------------------------------------------------------
// 会议创建选项（与 backend/app/schemas/meeting.py CreateMeetingRequest 对齐）
// ---------------------------------------------------------------------------

export interface CreateOption {
  value: string;
  label: string;
  description: string;
}

/** 产出物类型：与 produce 阶段 deliverable_type 分发一致 */
export const DELIVERABLE_TYPES: CreateOption[] = [
  { value: 'prd_openapi', label: 'PRD + OpenAPI', description: '产品需求文档与接口定义' },
  { value: 'design_doc', label: '设计文档', description: '技术方案与架构设计' },
  { value: 'feasibility_report', label: '可行性报告', description: '技术/成本/风险/合规四维可行性结论' },
  { value: 'adr', label: '架构决策记录', description: 'D 决策表格式的 ADR 产出' },
  { value: 'test_suite', label: '测试套件', description: '针对目标范围生成可执行测试代码' },
  { value: 'research_report', label: '研究报告', description: '调研分析与结论' },
  { value: 'business_report', label: '商业报告', description: '市场与商业分析' },
  { value: 'comprehensive', label: '综合报告', description: '多维度综合分析' },
  { value: 'code_analysis', label: '代码分析', description: '沙箱执行的代码级分析' },
  { value: 'tested_system', label: '可运行系统', description: '生成并测试可运行系统' },
  { value: 'deployable_service', label: '可部署服务', description: '生成并部署完整服务' },
];

/** 执行模式：与 orchestrator flow_plan 一致 */
export const FLOW_PLANS: CreateOption[] = [
  { value: 'standard', label: '标准六阶段', description: '澄清→辩论→证据→仲裁→交付' },
  { value: 'instant', label: '即时回答', description: '跳过辩论，快速给出结论' },
  { value: 'plan', label: '先计划后执行', description: '先生成执行计划再逐步执行' },
];

/** 辩论深度 */
export const DEBATE_DEPTHS: CreateOption[] = [
  { value: 'light', label: '轻量', description: '单轮观点，速度快' },
  { value: 'standard', label: '标准', description: '观点碰撞与冲突检验' },
  { value: 'deep', label: '深度', description: '多轮辩论与充分质证' },
];

/** 会议附件允许的文件类型（与 backend/app/routers/documents.py 对齐） */
export const UPLOAD_ACCEPT = '.md,.markdown,.txt';
export const UPLOAD_MAX_SIZE_MB = 10;
export const UPLOAD_ALLOWED_EXTENSIONS = ['.md', '.markdown', '.txt'];
