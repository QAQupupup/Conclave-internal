/**
 * 全局常量：阶段/角色/状态/证据来源的中文标签与样式类映射。
 * 设计模式：单一数据源（Registry）—— 所有 UI 文本集中一处，避免 STAGE_LABELS/STAGE_NAMES/statusLabel/sourceLabel 多处双写。
 *
 * 复用：types/events.ts 已定义的 STAGE_LABELS / ROLE_LABELS 直接 re-export，
 *       其它组件从 constants.ts 引入即可，无需感知定义文件。
 */

// 阶段顺序与中文标签（来自 types/events.ts）
import { STAGE_ORDER, STAGE_LABELS, ROLE_LABELS } from './types/events.ts'
export { STAGE_ORDER, STAGE_LABELS, ROLE_LABELS }

/** 报告查看器中使用的阶段中文标签（与 STAGE_LABELS 内容一致，过去在 ReportViewer 中重复定义） */
export const STAGE_NAMES = STAGE_LABELS

/** localStorage 键集中管理 */
export const STORAGE_KEYS = {
  meetingId: 'conclave_meeting_id',
  sidebarCollapsed: 'conclave-sidebar-collapsed',
  graphCollapsed: 'conclave-graph-collapsed',
  chatDraft: 'conclave-chat-draft',
  apiToken: 'conclave_api_token',
} as const

/** 会议状态中文标签 + 样式类 */
export interface MeetingStatusInfo {
  text: string
  cls: string
}

export function getMeetingStatusInfo(
  status: string,
  stageLabel: string,
): MeetingStatusInfo {
  switch (status) {
    case 'done':
      return { text: '已完成', cls: 'done' }
    case 'running':
      return { text: `${stageLabel} 运行中`, cls: 'running' }
    case 'paused':
      return { text: '已暂停', cls: 'paused' }
    case 'aborted':
      return { text: '已终止', cls: 'aborted' }
    default:
      return { text: stageLabel, cls: '' }
  }
}

/** 证据来源分类 */
export type EvidenceSourceType = 'doc' | 'web' | 'common' | 'unknown'

/** 证据来源中文标签 */
export const EVIDENCE_SOURCE_LABEL: Record<EvidenceSourceType, string> = {
  doc: '文档证据',
  web: '网络检索',
  common: '通用知识',
  unknown: '未知来源',
}

/** 从原始 source 字符串（如 "doc:foo.md"）解析出分类 */
export function classifyEvidenceSource(source: string | undefined): EvidenceSourceType {
  if (!source) return 'unknown'
  if (source.startsWith('doc:')) return 'doc'
  if (source.startsWith('web:')) return 'web'
  if (source.startsWith('common_knowledge')) return 'common'
  return 'unknown'
}

/** 从原始 source 字符串直接取中文标签（用于 tooltip / AgentGraph 简写） */
export function evidenceSourceLabel(source: string | undefined): string {
  if (!source) return '证据'
  if (source.startsWith('doc:')) return '文档证据'
  if (source.startsWith('web:')) return '网络检索'
  if (source.startsWith('common_knowledge')) return '通用知识'
  return '证据'
}
