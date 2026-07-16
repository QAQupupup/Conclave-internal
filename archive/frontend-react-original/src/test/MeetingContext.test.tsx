import { render, screen, waitFor, act } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import { MeetingProvider, useMeeting } from '../store/MeetingContext.tsx'
import type { MeetingAction } from '../store/meetingReducer.ts'

let capturedDispatch: ((action: MeetingAction) => void) | null = null

const noop = () => {}

vi.mock('../hooks/useWebSocket.ts', () => ({
  useWebSocket: (_meetingId: string | null, dispatch: (action: MeetingAction) => void) => {
    capturedDispatch = dispatch
    return {
      connected: false,
      connectionError: null,
      lastSeq: 0,
      sendControl: noop,
      sendBorrow: noop,
      approveBorrow: noop,
      rejectBorrow: noop,
      freezeBorrow: noop,
    }
  },
}))

const getMeetingDetail = vi.fn()
vi.mock('../lib/api.ts', async () => {
  const actual = await vi.importActual<typeof import('../lib/api.ts')>('../lib/api.ts')
  return {
    ...actual,
    getMeetingDetail: (...args: Parameters<typeof actual.getMeetingDetail>) => getMeetingDetail(...args),
  }
})

function TestConsumer() {
  const { store, connected, connectionError } = useMeeting()
  return (
    <div>
      <span data-testid="connected">{connected ? 'yes' : 'no'}</span>
      <span data-testid="error">{connectionError ?? 'none'}</span>
      <span data-testid="topic">{store.meeting?.topic ?? ''}</span>
      <span data-testid="stage">{store.meeting?.stage ?? ''}</span>
      <span data-testid="msg-count">{store.meeting?.messages?.length ?? 0}</span>
      <span data-testid="last-error">{store.lastError ?? ''}</span>
    </div>
  )
}

describe('MeetingContext', () => {
  beforeEach(() => {
    capturedDispatch = null
    getMeetingDetail.mockReset()
    window.history.pushState({}, '', '/')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('handles hydrate failure gracefully and keeps empty store', async () => {
    window.history.pushState({}, '', '/meeting/test-mtg')
    getMeetingDetail.mockRejectedValueOnce(new Error('network down'))

    render(
      <MeetingProvider>
        <TestConsumer />
      </MeetingProvider>
    )

    await waitFor(() => expect(getMeetingDetail).toHaveBeenCalledWith('test-mtg'))
    expect(screen.getByTestId('topic').textContent).toBe('')
    expect(screen.getByTestId('error').textContent).toBe('none')
  })

  it('hydrates store from REST and exposes connected state', async () => {
    window.history.pushState({}, '', '/meeting/test-mtg')
    getMeetingDetail.mockResolvedValueOnce({
      meeting_id: 'test-mtg',
      topic: 'Test Topic',
      stage: 'clarify',
      status: 'running',
    })

    render(
      <MeetingProvider>
        <TestConsumer />
      </MeetingProvider>
    )

    await waitFor(() => expect(screen.getByTestId('topic').textContent).toBe('Test Topic'))
    expect(screen.getByTestId('stage').textContent).toBe('clarify')
    expect(screen.getByTestId('connected').textContent).toBe('no')
  })

  it('updates state when websocket dispatches events', async () => {
    window.history.pushState({}, '', '/meeting/test-mtg')
    getMeetingDetail.mockResolvedValueOnce({
      meeting_id: 'test-mtg',
      topic: 'Test Topic',
      stage: 'clarify',
      status: 'running',
      messages: [],
    })

    render(
      <MeetingProvider>
        <TestConsumer />
      </MeetingProvider>
    )

    await waitFor(() => expect(screen.getByTestId('topic').textContent).toBe('Test Topic'))

    act(() => {
      capturedDispatch?.({
        type: 'event',
        event: {
          type: 'agent.spoke',
          meeting_id: 'test-mtg',
          ts: new Date().toISOString(),
          payload: {
            meeting_id: 'test-mtg',
            role: 'moderator',
            stage: 'clarify',
            content: 'hello',
            claim_refs: [],
            message_id: 'msg-1',
          },
        },
      })
    })

    expect(screen.getByTestId('msg-count').textContent).toBe('1')
  })

  it('records error action in store', async () => {
    window.history.pushState({}, '', '/meeting/test-mtg')
    getMeetingDetail.mockResolvedValueOnce({
      meeting_id: 'test-mtg',
      topic: 'Test Topic',
      stage: 'clarify',
      status: 'running',
    })

    render(
      <MeetingProvider>
        <TestConsumer />
      </MeetingProvider>
    )

    await waitFor(() => expect(screen.getByTestId('topic').textContent).toBe('Test Topic'))

    act(() => {
      capturedDispatch?.({ type: 'error', message: 'something went wrong' })
    })

    expect(screen.getByTestId('last-error').textContent).toBe('something went wrong')
  })
})
