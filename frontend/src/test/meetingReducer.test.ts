import { describe, it, expect } from 'vitest'
import { meetingReducer, initialStore, type MeetingStore } from '../store/meetingReducer'
import type { MeetingState, DomainEvent } from '../types/events'

/** 构造一个最小的 MeetingState 用于测试 */
function makeMeeting(overrides: Partial<MeetingState> = {}): MeetingState {
  return {
    meeting_id: 'm1',
    topic: 'test topic',
    status: 'running',
    stage: 'clarify',
    created_at: '2026-01-01T00:00:00Z',
    messages: [],
    conflicts: [],
    decisions: [],
    evidence_set: [],
    artifacts: [],
    flow_plan: null,
    ...overrides,
  } as MeetingState
}

describe('meetingReducer', () => {
  describe('reset', () => {
    it('returns initialStore', () => {
      const store: MeetingStore = { meeting: makeMeeting(), replayDone: true, lastError: 'err' }
      const result = meetingReducer(store, { type: 'reset' })
      expect(result).toEqual(initialStore)
    })
  })

  describe('snapshot', () => {
    it('sets meeting and resets replayDone', () => {
      const meeting = makeMeeting({ topic: 'snapshot test' })
      const result = meetingReducer(initialStore, { type: 'snapshot', payload: meeting })
      expect(result.meeting).toEqual(meeting)
      expect(result.replayDone).toBe(false)
    })
  })

  describe('replay.done', () => {
    it('sets replayDone to true', () => {
      const store: MeetingStore = { meeting: makeMeeting(), replayDone: false, lastError: null }
      const result = meetingReducer(store, { type: 'replay.done', events: 5 })
      expect(result.replayDone).toBe(true)
    })
  })

  describe('hydrate', () => {
    it('creates meeting from partial when no baseline', () => {
      const result = meetingReducer(initialStore, {
        type: 'hydrate',
        payload: { meeting_id: 'h1', topic: 'hydrated' },
      })
      expect(result.meeting).not.toBeNull()
      expect(result.meeting!.meeting_id).toBe('h1')
      expect(result.meeting!.topic).toBe('hydrated')
    })

    it('merges with existing baseline', () => {
      const store: MeetingStore = {
        meeting: makeMeeting({ topic: 'original', stage: 'clarify' }),
        replayDone: true,
        lastError: null,
      }
      const result = meetingReducer(store, {
        type: 'hydrate',
        payload: { stage: 'produce' },
      })
      expect(result.meeting!.topic).toBe('original')
      expect(result.meeting!.stage).toBe('produce')
    })
  })

  describe('error', () => {
    it('sets lastError', () => {
      const result = meetingReducer(initialStore, { type: 'error', message: 'boom' })
      expect(result.lastError).toBe('boom')
    })
  })

  describe('event: meeting.created', () => {
    it('updates meeting_id and topic', () => {
      const store: MeetingStore = { meeting: makeMeeting(), replayDone: true, lastError: null }
      const event: DomainEvent = {
        type: 'meeting.created',
        meeting_id: 'm2',
        ts: '2026-01-01T00:00:00Z',
        trace_id: 't1',
        payload: { meeting_id: 'm2', topic: 'new topic' },
      }
      const result = meetingReducer(store, { type: 'event', event })
      expect(result.meeting!.meeting_id).toBe('m2')
      expect(result.meeting!.topic).toBe('new topic')
    })
  })

  describe('event: stage.changed', () => {
    it('updates stage', () => {
      const store: MeetingStore = { meeting: makeMeeting({ stage: 'clarify' }), replayDone: true, lastError: null }
      const event: DomainEvent = {
        type: 'stage.changed',
        meeting_id: 'm1',
        ts: '2026-01-01T00:00:00Z',
        trace_id: 't1',
        payload: { to: 'intra_team' },
      }
      const result = meetingReducer(store, { type: 'event', event })
      expect(result.meeting!.stage).toBe('intra_team')
    })
  })

  describe('event: agent.spoke', () => {
    it('appends message', () => {
      const store: MeetingStore = { meeting: makeMeeting({ messages: [] }), replayDone: true, lastError: null }
      const event: DomainEvent = {
        type: 'agent.spoke',
        meeting_id: 'm1',
        ts: '2026-01-01T00:00:00Z',
        trace_id: 't1',
        payload: {
          message_id: 'msg1',
          meeting_id: 'm1',
          role: 'moderator',
          stage: 'clarify',
          content: 'hello',
        },
      }
      const result = meetingReducer(store, { type: 'event', event })
      expect(result.meeting!.messages).toHaveLength(1)
      expect((result.meeting as any)?.messages[0]?.id).toBe('msg1')
    })

    it('deduplicates by message_id', () => {
      const store: MeetingStore = {
        meeting: makeMeeting({
          messages: [{ id: 'msg1', meeting_id: 'm1', agent_role: 'moderator', stage: 'clarify', content: 'old', claim_refs: [], evidence_refs: [], created_at: '' }],
        }),
        replayDone: true,
        lastError: null,
      }
      const event: DomainEvent = {
        type: 'agent.spoke',
        meeting_id: 'm1',
        ts: '2026-01-01T00:00:00Z',
        trace_id: 't1',
        payload: {
          message_id: 'msg1',
          meeting_id: 'm1',
          role: 'moderator',
          stage: 'clarify',
          content: 'new',
        },
      }
      const result = meetingReducer(store, { type: 'event', event })
      expect(result.meeting!.messages).toHaveLength(1)
      expect((result.meeting as any)?.messages[0]?.content).toBe('old')
    })
  })

  describe('event: control.signal', () => {
    it('updates status', () => {
      const store: MeetingStore = { meeting: makeMeeting({ status: 'running' }), replayDone: true, lastError: null }
      const event: DomainEvent = {
        type: 'control.signal',
        meeting_id: 'm1',
        ts: '2026-01-01T00:00:00Z',
        trace_id: 't1',
        payload: { status: 'paused' },
      }
      const result = meetingReducer(store, { type: 'event', event })
      expect(result.meeting!.status).toBe('paused')
    })
  })

  describe('event: log.entry', () => {
    it('appends log and caps at 500', () => {
      const existingLogs = Array.from({ length: 500 }, (_, i) => ({
        id: `log-${i}`,
        level: 'info' as const,
        logger: 'test',
        message: `log ${i}`,
        timestamp: '2026-01-01T00:00:00Z',
      }))
      const store: MeetingStore = {
        meeting: makeMeeting({ logs: existingLogs } as any),
        replayDone: true,
        lastError: null,
      }
      const event: DomainEvent = {
        type: 'log.entry',
        meeting_id: 'm1',
        ts: '2026-01-01T00:00:00Z',
        trace_id: 't1',
        payload: { level: 'info', logger: 'test', message: 'new log', timestamp: '2026-01-01T00:00:00Z' },
      }
      const result = meetingReducer(store, { type: 'event', event })
      expect((result.meeting as any).logs).toHaveLength(500)
      expect((result.meeting as any).logs[499].message).toBe('new log')
    })
  })
})
