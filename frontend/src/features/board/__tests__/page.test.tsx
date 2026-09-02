/**
 * Board 列表页测试（问题 5 拆分后的 /board）
 *
 * 覆盖场景：
 * 1. 后端格式列表数据正常规范化渲染（标题/状态/分页文案）
 * 2. 空数据无筛选 → 空态文案 + 新建议题入口
 * 3. 有筛选无结果 → 筛选空态 + 清除筛选按钮（非正向）
 * 4. 状态页签切换 → 请求携带 status 参数（多值逗号分隔）
 * 5. 搜索防抖 → 请求携带 q 参数
 * 6. 分页计算：total 45 / pageSize 20 → 1/3 页且上一页禁用（边界）
 * 7. 新建议题按钮 → 导航到 /board/new
 * 8. 草稿行（running+is_running=false）→ 显示"待启动"并可启动进入会议页
 * 9. 删除流程 → 确认弹窗 + DELETE 调用
 * 10. 列表接口失败 → 不崩溃，回退空态（异常路径）
 */
import * as React from 'react';
import { Routes, Route } from 'react-router';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { api } from '@/lib/api';
import { renderWithProviders } from '@/test/test-utils';
import BoardPage from '@/features/board/page';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('@/hooks/use-toast', () => ({
  toast: vi.fn(),
  useToast: () => ({ toast: vi.fn() }),
  Toaster: () => null,
}));

const mockApiGet = vi.mocked(api.get);
const mockApiPost = vi.mocked(api.post);
const mockApiDelete = vi.mocked(api.delete);

/** 构造后端格式会议行（与 GET /meetings 返回契约一致） */
function backendMeeting(overrides: Record<string, unknown> = {}) {
  return {
    meeting_id: 'm1',
    topic: '测试议题一',
    stage: 'clarification',
    status: 'running',
    created_at: '2026-09-01T10:00:00Z',
    is_running: true,
    message_count: 12,
    agents: [{ id: 'a1', name: '架构师', role: 'architect', state: 'working' }],
    tags: ['架构'],
    ...overrides,
  };
}

function mockListResponse(meetings: unknown[], total?: number) {
  mockApiGet.mockResolvedValue({ meetings, total: total ?? meetings.length });
}

/** 用路由壳渲染，便于断言导航结果 */
function renderBoard(initialEntries: string[] = ['/board']) {
  return renderWithProviders(
    <Routes>
      <Route path="/board" element={<BoardPage />} />
      <Route path="/board/new" element={<div>NEW_PAGE_MARKER</div>} />
      <Route path="/meeting/:id" element={<div>MEETING_MARKER</div>} />
    </Routes>,
    { initialEntries },
  );
}

describe('BoardPage 列表页', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('后端格式列表 → 标题、状态徽标、分页文案正常渲染', async () => {
    mockListResponse([
      backendMeeting(),
      // m2 显式置空标签，保证"架构"标签断言唯一命中 m1
      backendMeeting({ meeting_id: 'm2', topic: '测试议题二', status: 'done', is_running: false, tags: [] }),
    ]);

    renderBoard();

    await waitFor(() => {
      expect(screen.getByText('测试议题一')).toBeDefined();
    });
    expect(screen.getByText('测试议题二')).toBeDefined();
    expect(screen.getByText('运行中')).toBeDefined();
    // "已完成"同时出现在状态页签与行徽标中，精确断言两处各一
    expect(screen.getAllByText('已完成')).toHaveLength(2);
    // 内联标签
    expect(screen.getByText('架构')).toBeDefined();
    // 分页文案
    expect(screen.getByText(/共 2 条 · 第 1 \/ 1 页/)).toBeDefined();
  });

  it('空数据且无筛选 → 显示空态与新建议题入口', async () => {
    mockListResponse([]);

    renderBoard();

    await waitFor(() => {
      expect(screen.getByText('暂无讨论，发起一个新议题开始吧')).toBeDefined();
    });
    // 空态内的新建议题按钮
    expect(screen.getAllByText('新建议题').length).toBeGreaterThanOrEqual(1);
  });

  it('有筛选但无结果 → 显示筛选空态与清除按钮（非正向）', async () => {
    // 首次全量有数据，切页签后返回空
    mockApiGet.mockImplementation((path: string) => {
      if (path.includes('status=')) return Promise.resolve({ meetings: [], total: 0 });
      return Promise.resolve({ meetings: [backendMeeting()], total: 1 });
    });

    renderBoard();

    await waitFor(() => {
      expect(screen.getByText('测试议题一')).toBeDefined();
    });

    fireEvent.click(screen.getByRole('tab', { name: '已完成' }));

    await waitFor(() => {
      expect(screen.getByText('未找到匹配的讨论')).toBeDefined();
    });
    expect(screen.getByText('清除筛选条件')).toBeDefined();
  });

  it('切换到"进行中"页签 → 请求携带多值 status 参数', async () => {
    mockListResponse([backendMeeting()]);

    renderBoard();

    await waitFor(() => {
      expect(screen.getByText('测试议题一')).toBeDefined();
    });

    fireEvent.click(screen.getByRole('tab', { name: '进行中' }));

    await waitFor(() => {
      const calls = mockApiGet.mock.calls.map((c) => String(c[0]));
      // URLSearchParams 会将逗号编码为 %2C
      expect(calls.some((p) => p.includes('status=running%2Cpaused'))).toBe(true);
    });
  });

  it('搜索输入防抖后 → 请求携带 q 参数', async () => {
    mockListResponse([backendMeeting()]);

    renderBoard();

    await waitFor(() => {
      expect(screen.getByText('测试议题一')).toBeDefined();
    });

    fireEvent.change(screen.getByLabelText('搜索议题'), { target: { value: '量子' } });

    await waitFor(
      () => {
        const calls = mockApiGet.mock.calls.map((c) => String(c[0]));
        expect(calls.some((p) => p.includes('q=') && p.includes('%E9%87%8F%E5%AD%90'))).toBe(true);
      },
      { timeout: 2000 },
    );
  });

  it('total=45 → 分页数 1/3 且上一页按钮禁用（边界）', async () => {
    mockListResponse([backendMeeting()], 45);

    renderBoard();

    await waitFor(() => {
      expect(screen.getByText(/共 45 条 · 第 1 \/ 3 页/)).toBeDefined();
    });
    const prev = screen.getByLabelText('上一页');
    expect(prev.hasAttribute('disabled')).toBe(true);
    const next = screen.getByLabelText('下一页');
    expect(next.hasAttribute('disabled')).toBe(false);
  });

  it('点击页头"新建议题" → 导航到 /board/new', async () => {
    mockListResponse([backendMeeting()]);

    renderBoard();

    await waitFor(() => {
      expect(screen.getByText('测试议题一')).toBeDefined();
    });

    fireEvent.click(screen.getByRole('button', { name: /新建议题/ }));

    await waitFor(() => {
      expect(screen.getByText('NEW_PAGE_MARKER')).toBeDefined();
    });
  });

  it('草稿行（running 但 is_running=false）→ 显示"待启动"并可启动进入会议页', async () => {
    mockListResponse([backendMeeting({ status: 'running', is_running: false })]);
    mockApiPost.mockResolvedValue({});

    renderBoard();

    await waitFor(() => {
      expect(screen.getByLabelText('启动讨论')).toBeDefined();
    });
    // 草稿徽标与提示
    expect(screen.getByText('待启动')).toBeDefined();
    expect(screen.getByText('已创建，尚未启动')).toBeDefined();

    fireEvent.click(screen.getByLabelText('启动讨论'));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/meetings/m1/run');
    });
    await waitFor(() => {
      expect(screen.getByText('MEETING_MARKER')).toBeDefined();
    });
  });

  it('删除流程 → 确认弹窗出现，确认后调用 DELETE', async () => {
    mockListResponse([backendMeeting({ status: 'done', is_running: false })]);
    mockApiDelete.mockResolvedValue({});

    renderBoard();

    await waitFor(() => {
      expect(screen.getByLabelText('删除讨论')).toBeDefined();
    });

    fireEvent.click(screen.getByLabelText('删除讨论'));

    // 确认弹窗标题
    await waitFor(() => {
      expect(screen.getByText('确定要删除「测试议题一」吗？')).toBeDefined();
    });

    fireEvent.click(screen.getByRole('button', { name: '删除' }));

    await waitFor(() => {
      expect(mockApiDelete).toHaveBeenCalledWith('/meetings/m1');
    });
  });

  it('列表接口失败 → 不崩溃并回退空态（异常路径）', async () => {
    mockApiGet.mockRejectedValue(new Error('Network error'));

    renderBoard();

    await waitFor(() => {
      expect(screen.getByText('暂无讨论，发起一个新议题开始吧')).toBeDefined();
    }, { timeout: 3000 });
  });
});
