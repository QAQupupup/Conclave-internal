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
  BorrowAutoApprovedPayload,
  BorrowAwaitingUserPayload,
  ControlSignalPayload,
  DomainEvent,
  EvidenceAttachedPayload,
  InterventionReplyPayload,
  LogEntry,
  MeetingState,
  StageChangedPayload,
} from '../types/events.ts'
import { LOG_CONSTANTS } from '../hooks/useMeetingLogs.ts'

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
  | { type: 'logs.hydrate'; payload: LogEntry[] }
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

    // 从 localStorage 加载历史日志
    case 'logs.hydrate': {
      if (!store.meeting) return store
      // 合并 hydrate 的日志与现有日志（按 id 去重，hydrate 的日志是历史，现有日志可能是 snapshot 后收到的新日志）
      const existing = store.meeting.logs ?? []
      const existingIds = new Set(existing.map((l) => l.id))
      const merged = [...action.payload.filter((l) => !existingIds.has(l.id)), ...existing]
        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
        .slice(-LOG_CONSTANTS.MAX_LOGS_PER_MEETING)
      return { ...store, meeting: { ...store.meeting, logs: merged } }
    }

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
              artifact: {
                ...meeting.artifact,
                ...(p.prd !== undefined ? { prd: p.prd } : {}),
                ...(p.openapi !== undefined ? { openapi: p.openapi } : {}),
                ...(p.deliverable_type ? { deliverable_type: p.deliverable_type } : {}),
                ...(p.code_analysis !== undefined ? { code_analysis: p.code_analysis } : {}),
                ...(p.tested_system !== undefined ? { tested_system: p.tested_system } : {}),
                ...(p.deployable_service !== undefined ? { deployable_service: p.deployable_service } : {}),
                ...(p.design_doc !== undefined ? { design_doc: p.design_doc } : {}),
                ...(p.comprehensive !== undefined ? { comprehensive: p.comprehensive } : {}),
                ...(p.research_report !== undefined ? { research_report: p.research_report } : {}),
                ...(p.business_report !== undefined ? { business_report: p.business_report } : {}),
                ...(p.execution !== undefined ? { execution: p.execution } : {}),
                ...(p.attachments !== undefined ? { attachments: p.attachments } : {}),
                ...(p.deployment !== undefined ? { deployment: p.deployment } : {}),
                ...(p.review !== undefined ? { review: p.review } : {}),
                ...(p.answer !== undefined ? { answer: p.answer } : {}),
                ...(p.flow !== undefined ? { flow: p.flow } : {}),
                meeting_id: p.meeting_id,
              },
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
          const p = ev.payload as { flow_plan: string; debate_depth?: string; skipped_stages: string[] }
          return {
            ...store,
            meeting: {
              ...meeting,
              flow_plan: p.flow_plan,
              ...(p.debate_depth ? { debate_depth: p.debate_depth } : {}),
              ...(p.skipped_stages ? { skipped_stages: p.skipped_stages } : {}),
            },
          }
        }
        case 'intervention.reply': {
          const p = ev.payload as InterventionReplyPayload
          if (p.meeting_id && p.meeting_id !== meeting.meeting_id) return store
          return {
            ...store,
            meeting: {
              ...meeting,
              intervention_messages: p.intervention_messages ?? meeting.intervention_messages,
            },
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
        case 'borrow.auto_approved': {
          const p = ev.payload as BorrowAutoApprovedPayload
          // 自动批准后 borrowed_agents 已在后端更新，通过 snapshot 同步；
          // 这里主要更新 auto_borrow_count
          return {
            ...store,
            meeting: {
              ...meeting,
              auto_borrow_count: p.auto_borrow_count,
            },
          }
        }
        case 'borrow.awaiting_user': {
          const p = ev.payload as BorrowAwaitingUserPayload
          return {
            ...store,
            meeting: {
              ...meeting,
              pending_borrow_request: {
                id: p.request_id,
                requester: 'moderator',
                target_role: p.target_role,
                goal: p.goal,
                necessary: p.necessary,
                no_loan_cost: p.no_loan_cost,
                requested_at: new Date().toISOString(),
                stage: meeting.stage ?? '',
              },
              auto_borrow_count: p.auto_borrow_count,
            },
          }
        }
        case 'borrow.approved_by_user': {
          return {
            ...store,
            meeting: {
              ...meeting,
              pending_borrow_request: null,
            },
          }
        }
        case 'borrow.rejected_by_user': {
          return {
            ...store,
            meeting: {
              ...meeting,
              pending_borrow_request: null,
            },
          }
        }
        case 'borrow.frozen': {
          return {
            ...store,
            meeting: {
              ...meeting,
              pending_borrow_request: null,
              borrow_frozen: true,
            },
          }
        }
        case 'produce.progress': {
          const p = ev.payload as { step: string; message: string; percent: number }
          return {
            ...store,
            meeting: {
              ...meeting,
              produce_progress: { step: p.step, message: p.message, percent: p.percent },
            },
          }
        }
        case 'log.entry': {
          const p = ev.payload as { level: string; logger: string; message: string; timestamp: string; agent_role?: string; stage?: string }
          const newEntry: LogEntry = {
            id: `log-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            level: p.level as LogEntry['level'],
            logger: p.logger,
            message: p.message,
            timestamp: p.timestamp,
            agent_role: p.agent_role,
            stage: p.stage,
          }
          const existingLogs = meeting.logs ?? []
          const logs = [...existingLogs, newEntry].slice(-LOG_CONSTANTS.MAX_LOGS_PER_MEETING)
          return {
            ...store,
            meeting: { ...meeting, logs },
          }
        }
        // ---- 新增事件处理 ----
        case 'instant.completed':
        case 'fast_path.completed': {  // 兼容旧事件名
          const p = ev.payload as { deliverable_type?: string; answer?: string }
          return {
            ...store,
            meeting: {
              ...meeting,
              status: 'done' as const,
              stage: 'produce' as const,
              flow_plan: 'instant' as const,
              ...(p.answer ? { artifact: { ...meeting.artifact, answer: p.answer, flow: 'instant' } } : {}),
            },
          }
        }
        case 'produce.degradation': {
          const p = ev.payload as { message: string; severity?: string }
          const existing = meeting.degradation_warnings ?? []
          return {
            ...store,
            meeting: {
              ...meeting,
              degradation_warnings: [...existing, { message: p.message, severity: p.severity ?? 'warning', ts: new Date().toISOString() }],
            },
          }
        }
        case 'service.deployed': {
          const p = ev.payload as { service_id: string; url: string; port: number }
          return {
            ...store,
            meeting: {
              ...meeting,
              deployed_services: [...(meeting.deployed_services ?? []), p],
            },
          }
        }
        case 'service.deploy_failed': {
          const p = ev.payload as { error: string; stage?: string }
          return {
            ...store,
            meeting: {
              ...meeting,
              deployment_error: p.error,
            },
          }
        }
        case 'captcha.pending': {
          const p = ev.payload as { session_id: string; url?: string; screenshot_url?: string }
          return {
            ...store,
            meeting: { ...meeting, captcha_pending: p },
          }
        }
        case 'captcha.resolved': {
          return {
            ...store,
            meeting: { ...meeting, captcha_pending: null },
          }
        }
        case 'captcha.timeout': {
          return {
            ...store,
            meeting: { ...meeting, captcha_pending: null },
          }
        }
        case 'net_auth.requested': {
          const p = ev.payload as { request_id: string; url: string; reason?: string }
          return {
            ...store,
            meeting: { ...meeting, pending_net_auth: p },
          }
        }
        case 'net_auth.reviewed':
        case 'net_auth.timeout': {
          return {
            ...store,
            meeting: { ...meeting, pending_net_auth: null },
          }
        }
        case 'meeting.failed': {
          return {
            ...store,
            meeting: { ...meeting, status: 'failed' as const },
          }
        }
        case 'meeting.done': {
          // instant 模式完成时发布，与 instant.completed 冗余但确保状态一致
          return {
            ...store,
            meeting: {
              ...meeting,
              status: 'done' as const,
              stage: (ev.payload as { flow?: string })?.flow === 'instant' ? 'produce' as const : meeting.stage,
            },
          }
        }
        case 'meeting.error': {
          // 后台任务异常事件
          const p = ev.payload as { error?: string; message?: string; error_detail?: string }
          return {
            ...store,
            meeting: {
              ...meeting,
              status: 'failed' as const,
              error_detail: p.error || p.error_detail || p.message || '未知错误',
            },
          }
        }
        case 'run.started': {
          // 会议开始运行事件
          return {
            ...store,
            meeting: {
              ...meeting,
              status: 'running' as const,
            },
          }
        }
        // control.ack / loan.requested / loan.resolved 等暂不改变核心状态
        default:
          return store
      }
    }

    default:
      return store
  }
}
