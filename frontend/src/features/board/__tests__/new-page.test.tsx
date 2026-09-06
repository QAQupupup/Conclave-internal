/**
 * Board 新建议题页测试（问题 5 拆分后的 /board/new）
 *
 * 覆盖场景：
 * 1. 基础渲染：编辑区 + 右栏配置 + 底部操作条
 * 2. 空议题校验 → 错误提示且不发起请求（非正向）
 * 3. ?from= 复用议题 → 预填源议题文本且标题切换为"复用议题"
 * 4. 发起会议 → POST /meetings + POST /run 并进入会议页
 * 5. 保存草稿 → 仅 POST /meetings 不调用 /run，返回列表页
 * 6. 字数统计随输入更新
 * 7. ?issue= 从议题发起 → 预填议题文本 + 创建时携带 issue_id（ADR-017 Phase 2）
 * 8. ?issue= 议题不可绑定（已闭环）→ 警示条且不携带 issue_id（非正向）
 */
import * as React from 'react';
import { Routes, Route } from 'react-router';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { api } from '@/lib/api';
import { renderWithProviders } from '@/test/test-utils';
import BoardNewPage from '@/features/board/new-page';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    relatedMeetings: vi.fn(),
    issues: { get: vi.fn() },
  },
}));

vi.mock('@/hooks/use-toast', () => ({
  toast: vi.fn(),
  useToast: () => ({ toast: vi.fn() }),
  Toaster: () => null,
}));

const mockApiGet = vi.mocked(api.get);
const mockApiPost = vi.mocked(api.post);
const mockRelated = vi.mocked(api.relatedMeetings);
const mockIssueGet = vi.mocked(api.issues.get);

function renderNewPage(initialEntries: string[] = ['/board/new']) {
  return renderWithProviders(
    <Routes>
      <Route path="/board/new" element={<BoardNewPage />} />
      <Route path="/board" element={<div>BOARD_MARKER</div>} />
      <Route path="/meeting/:id" element={<div>MEETING_MARKER</div>} />
    </Routes>,
    { initialEntries },
  );
}

describe('BoardNewPage 新建议题页', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith('/agent-roles')) return Promise.resolve({ roles: [] });
      return Promise.resolve({});
    });
    mockRelated.mockResolvedValue({ meetings: [] });
  });

  it('基础渲染 → 编辑区、配置栏、操作条齐全', async () => {
    renderNewPage();

    expect(screen.getByText('新建议题')).toBeDefined();
    expect(screen.getByLabelText('议题描述')).toBeDefined();
    expect(screen.getByText('启动参数')).toBeDefined();
    expect(screen.getByText('参与角色')).toBeDefined();
    expect(screen.getByText('参考文档')).toBeDefined();
    expect(screen.getByRole('button', { name: /发起会议/ })).toBeDefined();
    expect(screen.getByRole('button', { name: '保存草稿' })).toBeDefined();
    expect(screen.getByRole('button', { name: '取消' })).toBeDefined();
  });

  it('空议题点击发起 → 显示校验错误且不发起请求（非正向）', async () => {
    renderNewPage();

    fireEvent.click(screen.getByRole('button', { name: /发起会议/ }));

    await waitFor(() => {
      expect(screen.getByText('请先输入议题内容')).toBeDefined();
    });
    expect(mockApiPost).not.toHaveBeenCalled();
  });

  it('?from= 复用议题 → 预填源议题且标题为"复用议题"', async () => {
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith('/agent-roles')) return Promise.resolve({ roles: [] });
      if (path.startsWith('/meetings/src1')) {
        return Promise.resolve({
          meeting_id: 'src1',
          topic: '源议题：微服务通信方案对比',
          stage: 'produce',
          status: 'done',
        });
      }
      return Promise.resolve({});
    });

    renderNewPage(['/board/new?from=src1']);

    await waitFor(() => {
      expect(screen.getByText('复用议题')).toBeDefined();
    });
    const textarea = screen.getByLabelText('议题描述') as HTMLTextAreaElement;
    await waitFor(() => {
      expect(textarea.value).toBe('源议题：微服务通信方案对比');
    });
  });

  it('发起会议 → 创建 + 运行并进入会议页', async () => {
    mockApiPost.mockImplementation((path: string) => {
      if (path === '/meetings') return Promise.resolve({ meeting_id: 'new-m1' });
      return Promise.resolve({});
    });

    renderNewPage();

    fireEvent.change(screen.getByLabelText('议题描述'), {
      target: { value: '对比 gRPC 与 REST 的适用场景' },
    });
    fireEvent.click(screen.getByRole('button', { name: /发起会议/ }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/meetings', expect.objectContaining({
        topic: '对比 gRPC 与 REST 的适用场景',
      }));
    });
    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/meetings/new-m1/run');
    });
    await waitFor(() => {
      expect(screen.getByText('MEETING_MARKER')).toBeDefined();
    });
  });

  it('保存草稿 → 仅创建不运行，返回列表页', async () => {
    mockApiPost.mockImplementation((path: string) => {
      if (path === '/meetings') return Promise.resolve({ meeting_id: 'draft-m1' });
      return Promise.resolve({});
    });

    renderNewPage();

    fireEvent.change(screen.getByLabelText('议题描述'), {
      target: { value: '草稿议题：缓存一致性策略' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/meetings', expect.objectContaining({
        topic: '草稿议题：缓存一致性策略',
      }));
    });
    // 草稿不触发运行
    expect(mockApiPost).not.toHaveBeenCalledWith('/meetings/draft-m1/run');
    await waitFor(() => {
      expect(screen.getByText('BOARD_MARKER')).toBeDefined();
    });
  });

  it('字数统计随输入更新', () => {
    renderNewPage();

    fireEvent.change(screen.getByLabelText('议题描述'), { target: { value: '一二三四五' } });
    expect(screen.getByText('5 字')).toBeDefined();
  });

  it('?issue= 从议题发起 → 预填议题文本且创建请求携带 issue_id', async () => {
    mockIssueGet.mockResolvedValue({
      id: 'issue-1',
      project_id: 'p1',
      title: 'push 端点增加重试',
      body: '建议指数退避。',
      source: 'user',
      status: 'open',
      priority: 70,
    } as never);
    mockApiPost.mockImplementation((path: string) => {
      if (path === '/meetings') return Promise.resolve({ meeting_id: 'm-issue' });
      return Promise.resolve({});
    });

    renderNewPage(['/board/new?issue=issue-1']);

    await waitFor(() => {
      expect(screen.getByText('从议题发起')).toBeDefined();
    });
    const textarea = screen.getByLabelText('议题描述') as HTMLTextAreaElement;
    await waitFor(() => {
      expect(textarea.value).toBe('push 端点增加重试\n\n建议指数退避。');
    });
    // 可绑定提示条：告知发起后议题转为进行中
    expect(screen.getByText(/发起后议题将转为进行中/)).toBeDefined();

    fireEvent.click(screen.getByRole('button', { name: /发起会议/ }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        '/meetings',
        expect.objectContaining({ issue_id: 'issue-1' }),
      );
    });
  });

  it('?issue= 议题已闭环 → 警示提示且创建请求不携带 issue_id（非正向）', async () => {
    mockIssueGet.mockResolvedValue({
      id: 'issue-2',
      project_id: 'p1',
      title: '已闭环的议题',
      body: null,
      source: 'user',
      status: 'resolved',
      priority: 50,
    } as never);
    mockApiPost.mockImplementation((path: string) => {
      if (path === '/meetings') return Promise.resolve({ meeting_id: 'm-nobind' });
      return Promise.resolve({});
    });

    renderNewPage(['/board/new?issue=issue-2']);

    await waitFor(() => {
      expect(screen.getByText(/当前状态不可绑定会议/)).toBeDefined();
    });

    fireEvent.click(screen.getByRole('button', { name: /发起会议/ }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        '/meetings',
        expect.not.objectContaining({ issue_id: expect.anything() }),
      );
    });
  });
});
