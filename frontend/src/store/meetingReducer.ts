// 事件驱动的会议状态 reducer
// 接收 WS 控制帧（snapshot / replay.done）与 DomainEvent，按 type 更新 state
// 设计要点：
//  1. snapshot 为基线状态；replay.done 之前的历史事件可能已反映在 snapshot 中，
//     故 agent.spoke 按 message_id 去重，evidence.attached 按 conflict_id+quote upsert，
//     避免刷新页面后重放历史事件导致重复
//  2. 实时事件（replay.done 之后）正常追加
//  3. 所有更新均为不可变写法
import type {
  AgentSpokePayload,
  ArtifactGeneratedPayload,
  ControlSignalPayload,
  DomainEvent,
  EvidenceAttachedPayload,
  MeetingState,
  StageChangedPayload,
} from '../types/events.ts'

/** reducer 管理的 store：会议状态 + 回放标记 + 最近错误 */
export interface MeetingStore {
  meeting: MeetingState | null
  replayDone: boolean
  lastError: string | null
}

/** 初始空 store */
export const initialStore: MeetingStore = {
  meeting: null,
  replayDone: false,
  lastError: null,
}

/** reducer 接受的动作联合类型 */
export type MeetingAction =
  | { type: 'reset' }
  | { type: 'snapshot'; payload: MeetingState }
  | { type: 'replay.done'; events: number }
  | { type: 'hydrate'; payload: Partial<MeetingState> }
  | { type: 'event'; event: DomainEvent }
  | { type: 'error'; message: string }

/**
 * 把 agent.spoke 事件 payload 转换为一条 MeetingMessage 并追加（按 id 去重）
 */
function applyAgentSpoke(meeting: MeetingState, payload: AgentSpokePayload): MeetingState {
  const messages = meeting.messages ?? []
  // 已存在同 message_id 则不重复追加
  if (messages.some((m) => m.id === payload.message_id)) {
    return meeting
  }
  const newMsg = {
    id: payload.message_id,
    meeting_id: payload.meeting_id,
    agent_role: payload.role,
    stage: payload.stage,
    content: payload.content,
    claim_refs: payload.claim_refs ?? [],
    evidence_refs: [],
    created_at: new Date().toISOString(),
  }
  return { ...meeting, messages: [...messages, newMsg] }
}

/**
 * 证据注入：按 conflict_id upsert 到 evidence_set，并把该条 assessment 追加进去
 */
function applyEvidenceAttached(meeting: MeetingState, payload: EvidenceAttachedPayload): MeetingState {
  const evidenceSet = meeting.evidence_set ? [...meeting.evidence_set] : []
  const idx = evidenceSet.findIndex((e) => e.conflict_id === payload.conflict_id)
  const assessment = {
    conflict_id: payload.conflict_id,
    quote: payload.quote,
    source: payload.source,
    supports: payload.supports,
  }
  if (idx >= 0) {
    // 已存在该 conflict 的证据集合，追加 assessment（按 quote 去重）
    const existing = evidenceSet[idx]
    const assessments = existing.assessments ?? []
    if (!assessments.some((a) => a.quote === assessment.quote && a.source === assessment.source)) {
      evidenceSet[idx] = { ...existing, assessments: [...assessments, assessment] }
    }
  } else {
    evidenceSet.push({ conflict_id: payload.conflict_id, assessments: [assessment] })
  }
  return { ...meeting, evidence_set: evidenceSet }
}

/**
 * 核心 reducer：根据 action 类型更新 store
 */
export function meetingReducer(store: MeetingStore, action: MeetingAction): MeetingStore {
  switch (action.type) {
    case 'reset':
      return initialStore

    // WS 连接时回放的快照，作为基线状态
    case 'snapshot':
      return {
        meeting: action.payload,
        replayDone: false,
        lastError: null,
      }

    // 历史事件回放结束
    case 'replay.done':
      return { ...store, replayDone: true }

    // GET /meetings/:id 刷新后合并完整状态（覆盖字段）
    case 'hydrate': {
      if (!store.meeting) {
        // 尚无基线时直接用 hydrate 内容构造（保留默认值）
        const base: MeetingState = {
          meeting_id: action.payload.meeting_id ?? '',
          topic: action.payload.topic ?? '',
          stage: action.payload.stage ?? 'clarify',
          status: action.payload.status ?? 'running',
          ...action.payload,
        }
        return { ...store, meeting: base }
      }
      return { ...store, meeting: { ...store.meeting, ...action.payload } }
    }

    case 'error':
      return { ...store, lastError: action.message }

    // 领域事件分发
    case 'event': {
      if (!store.meeting) return store
      const ev = action.event
      const meeting = store.meeting
      switch (ev.type) {
        case 'meeting.created': {
          const p = ev.payload as { meeting_id: string; topic: string }
          return {
            ...store,
            meeting: { ...meeting, meeting_id: p.meeting_id, topic: p.topic },
          }
        }
        case 'stage.changed': {
          const p = ev.payload as StageChangedPayload
          return { ...store, meeting: { ...meeting, stage: p.to } }
        }
        case 'agent.spoke': {
          const p = ev.payload as AgentSpokePayload
          // 防御：仅处理同会议事件
          if (p.meeting_id && p.meeting_id !== meeting.meeting_id) return store
          return { ...store, meeting: applyAgentSpoke(meeting, p) }
        }
        case 'evidence.attached': {
          const p = ev.payload as EvidenceAttachedPayload
          return { ...store, meeting: applyEvidenceAttached(meeting, p) }
        }
        case 'artifact.generated': {
          const p = ev.payload as ArtifactGeneratedPayload
          return {
            ...store,
            meeting: {
              ...meeting,
              artifact: { meeting_id: p.meeting_id, prd: p.prd, openapi: p.openapi },
              stage: 'produce',
            },
          }
        }
        case 'control.signal': {
          const p = ev.payload as ControlSignalPayload
          return {
            ...store,
            meeting: { ...meeting, status: p.status ?? meeting.status },
          }
        }
        case 'flow_plan.set': {
          const p = ev.payload as { flow_plan: string; skipped_stages: string[] }
          return {
            ...store,
            meeting: { ...meeting, flow_plan: p.flow_plan },
          }
        }
        case 'meeting.fallback_warning': {
          const p = ev.payload as { fallback_stages: string[]; message: string; severity: string }
          return {
            ...store,
            meeting: {
              ...meeting,
              fallback_warning: { stages: p.fallback_stages, message: p.message },
            },
          }
        }
        // control.ack / loan.requested / loan.resolved / error 等暂不改变核心状态
        default:
          return store
      }
    }

    default:
      return store
  }
}
