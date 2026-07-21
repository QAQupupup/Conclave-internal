// ChatPanel 组件单元测试
// 覆盖：空态、消息渲染、阶段分隔线、Produce 进度条、新消息提示按钮、onSelectRef 转发等
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { ChatPanel } from '../components/ChatPanel.tsx'

// ---------------------------------------------------------------------------
// Mock：MessageCard 抽象为简单 stub，避免测试子组件
// 当 onSelectRef 被传入时，渲染一个可点击按钮以验证 prop 转发
// ---------------------------------------------------------------------------
vi.mock('../components/MessageCard.tsx', () => ({
  MessageCard: ({ message, onSelectRef }: { message: any; onSelectRef?: (ref: string) => void }) => (
    <div data-testid={`msg-${message.id}`}>
      {message.content}
      {onSelectRef && (
        <button data-testid={`ref-btn-${message.id}`} onClick={() => onSelectRef('ref-1')}>
          ref
        </button>
      )}
    </div>
  ),
}))

// ---------------------------------------------------------------------------
// Mock：useMeeting 返回受控 store
// mockStore 为模块级可变对象，beforeEach 中重置 meeting 字段以驱动各用例
// ---------------------------------------------------------------------------
const mockStore = {
  meeting: null as any,
  replayDone: true,
  lastError: null as string | null,
}

vi.mock('../store/MeetingContext.tsx', () => ({
  useMeeting: () => ({ store: mockStore }),
}))

// ---------------------------------------------------------------------------
// 辅助：构造一条 MeetingMessage
// ---------------------------------------------------------------------------
function mkMessage(overrides: Record<string, any> = {}): any {
  return {
    id: overrides.id ?? 'msg-1',
    meeting_id: 'm1',
    agent_role: 'moderator',
    stage: 'clarify',
    content: 'hello',
    claim_refs: [],
    evidence_refs: [],
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('ChatPanel', () => {
  beforeEach(() => {
    // 每个用例前重置为合理的默认会议状态
    mockStore.meeting = {
      meeting_id: 'm1',
      topic: 'test',
      stage: 'clarify',
      status: 'running',
      messages: [],
      produce_progress: null,
    }
    mockStore.replayDone = true
    mockStore.lastError = null
  })

  // 1. 空态
  it('renders "暂无发言" hint when there are no messages', () => {
    render(<ChatPanel />)
    expect(screen.getByText(/暂无发言/)).toBeInTheDocument()
  })

  // 2. 消息渲染
  it('renders all messages', () => {
    mockStore.meeting.messages = [
      mkMessage({ id: 'a', content: 'Alpha' }),
      mkMessage({ id: 'b', content: 'Beta' }),
    ]
    render(<ChatPanel />)
    expect(screen.getByTestId('msg-a')).toHaveTextContent('Alpha')
    expect(screen.getByTestId('msg-b')).toHaveTextContent('Beta')
  })

  // 3. 阶段分隔线：相邻消息阶段不同时显示 Divider
  it('shows a Divider when consecutive messages have different stages', () => {
    mockStore.meeting.messages = [
      mkMessage({ id: 'a', stage: 'clarify', content: 'A' }),
      mkMessage({ id: 'b', stage: 'intra_team', content: 'B' }),
    ]
    const { container } = render(<ChatPanel />)
    // 分隔线文本为当前消息阶段的中文标签
    expect(screen.getByText('队内发言')).toBeInTheDocument()
    expect(container.querySelector('.ant-divider')).not.toBeNull()
  })

  // 4. 无分隔线：相邻消息阶段相同时不显示 Divider
  it('does NOT show a Divider when consecutive messages have the same stage', () => {
    mockStore.meeting.messages = [
      mkMessage({ id: 'a', stage: 'clarify', content: 'A' }),
      mkMessage({ id: 'b', stage: 'clarify', content: 'B' }),
    ]
    const { container } = render(<ChatPanel />)
    expect(container.querySelector('.ant-divider')).toBeNull()
  })

  // 5. 首条消息无分隔线（prevStage=null）
  it('does not render a separator before the first message', () => {
    mockStore.meeting.messages = [mkMessage({ id: 'a', stage: 'clarify', content: 'A' })]
    const { container } = render(<ChatPanel />)
    expect(container.querySelector('.ant-divider')).toBeNull()
  })

  // 6. Produce 进度条：stage=produce + status=running + 进度存在时显示
  it('shows the Progress bar when stage=produce, status=running, and produceProgress present', () => {
    mockStore.meeting.stage = 'produce'
    mockStore.meeting.status = 'running'
    mockStore.meeting.produce_progress = { step: 's1', message: '生成中', percent: 42 }
    const { container } = render(<ChatPanel />)
    expect(screen.getByText('生成中')).toBeInTheDocument()
    expect(container.querySelector('.ant-progress')).not.toBeNull()
    expect(container.querySelector('.chat-panel-progress-wrap')).not.toBeNull()
  })

  // 7. 非 produce 阶段不显示进度条
  it('hides the Progress bar when stage is not "produce"', () => {
    mockStore.meeting.stage = 'clarify'
    mockStore.meeting.status = 'running'
    mockStore.meeting.produce_progress = { step: 's1', message: '生成中', percent: 42 }
    const { container } = render(<ChatPanel />)
    expect(container.querySelector('.ant-progress')).toBeNull()
    expect(container.querySelector('.chat-panel-progress-wrap')).toBeNull()
  })

  // 8. 进度 100% 时隐藏进度条
  it('hides the Progress bar when percent is 100', () => {
    mockStore.meeting.stage = 'produce'
    mockStore.meeting.status = 'running'
    mockStore.meeting.produce_progress = { step: 's1', message: '完成', percent: 100 }
    const { container } = render(<ChatPanel />)
    expect(container.querySelector('.ant-progress')).toBeNull()
    expect(container.querySelector('.chat-panel-progress-wrap')).toBeNull()
  })

  // 9. 新消息按钮初始隐藏（位于底部时）
  it('does not show the "新消息" button when at the bottom', () => {
    mockStore.meeting.messages = [mkMessage({ id: 'a', content: 'A' })]
    render(<ChatPanel />)
    expect(screen.queryByRole('button', { name: /新消息/ })).toBeNull()
  })

  // 10. 面板标题
  it('renders the "聊天流" panel title', () => {
    render(<ChatPanel />)
    expect(screen.getByText('聊天流')).toBeInTheDocument()
  })

  // 11. 消息顺序
  it('renders messages in array order', () => {
    mockStore.meeting.messages = [
      mkMessage({ id: 'a', content: 'First' }),
      mkMessage({ id: 'b', content: 'Second' }),
      mkMessage({ id: 'c', content: 'Third' }),
    ]
    const { container } = render(<ChatPanel />)
    const items = container.querySelectorAll('[data-testid^="msg-"]')
    expect(items).toHaveLength(3)
    expect(items[0]).toHaveTextContent('First')
    expect(items[1]).toHaveTextContent('Second')
    expect(items[2]).toHaveTextContent('Third')
  })

  // 12. onSelectRef 转发：点击消息 ref 触发回调
  it('calls onSelectRef when a message ref is clicked', () => {
    const onSelectRef = vi.fn()
    mockStore.meeting.messages = [mkMessage({ id: 'a', content: 'A' })]
    render(<ChatPanel onSelectRef={onSelectRef} />)
    fireEvent.click(screen.getByTestId('ref-btn-a'))
    expect(onSelectRef).toHaveBeenCalledWith('ref-1')
  })

  // 13. 额外：用户上滚后新消息到达时显示"新消息"按钮
  it('shows the "新消息" button when scrolled up and new messages arrive', async () => {
    mockStore.meeting.messages = [mkMessage({ id: 'a', content: 'A' })]
    const { container, rerender } = render(<ChatPanel />)
    const scrollEl = container.querySelector('.chat-list') as HTMLElement

    // 模拟用户向上滚动（不在底部）
    Object.defineProperty(scrollEl, 'scrollHeight', { configurable: true, value: 1000 })
    Object.defineProperty(scrollEl, 'clientHeight', { configurable: true, value: 400 })
    scrollEl.scrollTop = 100
    fireEvent.scroll(scrollEl)

    // 新增一条消息并重新渲染
    mockStore.meeting.messages = [
      mkMessage({ id: 'a', content: 'A' }),
      mkMessage({ id: 'b', content: 'B' }),
    ]
    rerender(<ChatPanel />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /新消息/ })).toBeInTheDocument()
    })
  })

  // 14. 额外：点击"新消息"按钮滚动回底部并隐藏按钮
  it('hides the "新消息" button after clicking it', async () => {
    mockStore.meeting.messages = [mkMessage({ id: 'a', content: 'A' })]
    const { container, rerender } = render(<ChatPanel />)
    const scrollEl = container.querySelector('.chat-list') as HTMLElement

    Object.defineProperty(scrollEl, 'scrollHeight', { configurable: true, value: 1000 })
    Object.defineProperty(scrollEl, 'clientHeight', { configurable: true, value: 400 })
    scrollEl.scrollTop = 100
    fireEvent.scroll(scrollEl)

    mockStore.meeting.messages = [
      mkMessage({ id: 'a', content: 'A' }),
      mkMessage({ id: 'b', content: 'B' }),
    ]
    rerender(<ChatPanel />)

    const btn = await screen.findByRole('button', { name: /新消息/ })
    // 点击后滚动到底部，按钮应消失
    // 模拟滚动到底部：scrollTop 设为最大
    Object.defineProperty(scrollEl, 'scrollHeight', { configurable: true, value: 1000 })
    Object.defineProperty(scrollEl, 'clientHeight', { configurable: true, value: 400 })
    scrollEl.scrollTop = 600 // 1000 - 400 = 600 即在底部阈值内
    fireEvent.click(btn)
    fireEvent.scroll(scrollEl)

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /新消息/ })).toBeNull()
    })
  })
})
