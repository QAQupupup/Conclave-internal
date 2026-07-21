/* Conclave 前端共享类型定义
 * 消除 api.ts / ws.ts / AppContext.tsx / reportLayouts.ts 中的 any
 * 对应后端 app/domain/meeting.py 的 sections 结构
 */

/* ═══ 会议相关类型 ═══ */

/** 冲突项 */
export interface Conflict {
  id?: string;
  summary: string;
  sideA: string;
  sideB: string;
  verdict?: string;
  rationale?: string;
  trace?: string;
}

/** 声明项 */
export interface Claim {
  id?: string;
  text: string;
  source?: string;
  confidence?: number;
}

/** 置信度标记 */
export interface ConfidenceFlag {
  stage: string;
  level: 'high' | 'medium' | 'low';
  reason?: string;
}

/** 会议产出文档 */
export interface MeetingArtifact {
  prd: {
    title: string;
    goal: string;
    scope?: string;
    assumptions?: string[];
    constraints?: string[];
    apiEndpoints?: string[];
    openQuestions?: string[];
  };
  openapi?: string;
  attachments?: unknown[];
}

/** 报告数据（reportLayouts.ts 中各 _layout* 函数的参数类型） */
export interface ProduceData {
  clarifiedTopic: string;
  adoptedClaims: string[];
  keyQuestions: string[];
  teamConfig: Array<{ role: string; stance: string }>;
  conflicts: Conflict[];
  decisions: Array<{ conflictId?: string; rationale?: string }>;
  artifact: MeetingArtifact;
}

/* ═══ WS 消息类型 ═══ */

/** WS 快照状态（onSnapshot 回调参数） */
export interface WsSnapshotState {
  meeting_id?: string;
  stage?: string | number;
  status?: string;
  topic?: string;
  messages?: unknown[];
  conflicts?: unknown[];
  claims?: unknown[];
  [key: string]: unknown;
}

/* ═══ API 返回类型 ═══ */

/** 健康检查结果 */
export interface HealthCheckResult {
  ok: boolean;
  host_id: number;
  host_name: string;
  health_status: string;
  health_detail?: Record<string, unknown>;
  error?: string;
}

/** Docker 主机预设 */
export interface DockerHostPreset {
  presets: unknown[];
  connection_types: string[];
  required_fields: Record<string, string[]>;
}

/** 容器信息 */
export interface ContainerInfo {
  id: string;
  name: string;
  image: string;
  status: string;
  state: string;
}

/** 偏好设置值 */
export type PreferenceValue = string | number | boolean | string[] | Record<string, unknown>;
