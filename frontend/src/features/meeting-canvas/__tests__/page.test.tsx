/**
 * 路由画布页测试（问题 4 整页档画布 /meeting/:id/canvas/:kind）
 *
 * 覆盖场景：
 * 1. replay 画布 → 顶栏标题 + 会议议题上下文 + 返回按钮
 * 2. 返回按钮 → 回到会议页（浏览器后退同语义）
 * 3. 未知画布类别 → 重定向回会议页而非崩溃（非正向）
 * 4. 洞察画布 tab 切换 → URL 驱动（切到相关会议后标题随 URL 变化）
 */
import * as React from 'react';
import { Routes, Route } from 'react-router';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { api } from '@/lib/api';
import { renderWithProviders } from '@/test/test-utils';
import MeetingCanvasPage from '@/features/meeting-canvas/page';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    graphOverview: vi.fn(),
    meetingRelated: vi.fn(),
    getMeetingEvents: vi.fn(),
  },
}));

vi.mock('@/hooks/use-toast', () => ({
  toast: vi.fn(),
  useToast: () => ({ toast: vi.fn() }),
  Toaster: () => null,
}));

const mockApiGet = vi.mocked(api.get);
const mockGraphOverview = vi.mocked(api.graphOverview);
const mockMeetingRelated = vi.mocked(api.meetingRelated);
const mockGetMeetingEvents = vi.mocked(api.getMeetingEvents);

function renderCanvas(initialEntries: string[]) {
  return renderWithProviders(
    <Routes>
      <Route path="/meeting/:id/canvas/:kind" element={<MeetingCanvasPage />} />
      <Route path="/meeting/:id" element={<div>MEETING_MARKER</div>} />
      <Route path="/board" element={<div>BOARD_MARKER</div>} />
    </Routes>,
    { initialEntries },
  );
}

describe('MeetingCanvasPage 路由画布', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // useMeeting：前端格式（有 id + agents）直接透传，不经过规范化
    mockApiGet.mockResolvedValue({
      id: 'm1',
      title: '画布路由测试议题',
      agents: [],
      status: 'running',
      stage: 'clarification',
    });
    mockGraphOverview.mockResolvedValue({ nodes: [], edges: [] });
    mockMeetingRelated.mockResolvedValue({ meetings: [] });
    mockGetMeetingEvents.mockResolvedValue({
      meeting_id: 'm1',
      from_seq: 0,
      last_seq: 0,
      count: 0,
      events: [],
    });
  });

  it('replay 画布 → 顶栏标题、会议议题上下文与返回按钮齐全', async () => {
    renderCanvas(['/meeting/m1/canvas/replay']);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '操作回放' })).toBeDefined();
    });
    // 会议上下文：议题标题展示在顶栏
    await waitFor(() => {
      expect(screen.getByText('画布路由测试议题')).toBeDefined();
    });
    expect(screen.getByRole('button', { name: '返回会议' })).toBeDefined();
  });

  it('返回按钮 → 回到会议页', async () => {
    renderCanvas(['/meeting/m1/canvas/replay']);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '返回会议' })).toBeDefined();
    });
    fireEvent.click(screen.getByRole('button', { name: '返回会议' }));

    await waitFor(() => {
      expect(screen.getByText('MEETING_MARKER')).toBeDefined();
    });
  });

  it('未知画布类别 → 重定向回会议页而非崩溃（非正向）', async () => {
    renderCanvas(['/meeting/m1/canvas/no_such_kind']);

    await waitFor(() => {
      expect(screen.getByText('MEETING_MARKER')).toBeDefined();
    });
  });

  it('洞察画布 tab 切换由 URL 驱动 → 切到相关会议后标题随之变化', async () => {
    renderCanvas(['/meeting/m1/canvas/conflicts']);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '冲突与证据' })).toBeDefined();
    });

    // 画布内置 tab 栏：点击"相关会议"触发 onTabChange → navigate 改 URL
    fireEvent.click(screen.getByRole('button', { name: '相关会议' }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '相关会议' })).toBeDefined();
    });
  });
});
