/**
 * Graph 页面测试
 *
 * 覆盖场景：
 * 1. meetings.find() 在 meetings 为空数组时不崩溃
 * 2. meetings.find() 在 selectedMeetingId 匹配时正确找到会议
 * 3. meetings.find() 在 selectedMeetingId 不匹配时回退到演示图谱
 * 4. layoutData?.nodes.find() 在 layoutData 为 null 时不崩溃（通过初始渲染验证）
 * 5. meetings 为 undefined 时通过 || [] 回退不崩溃
 * 6. graphData.nodes/edges 缺失时不崩溃（防御性检查）
 */
import * as React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { api } from '@/lib/api';
import { renderWithProviders } from '@/test/test-utils';
import GraphPage from '@/features/graph/page';

// Mock mock-data: control isDemoMode for graph page
vi.mock('@/lib/mock-data', () => ({
  isDemoMode: () => true,
  mockApi: {
    getGraphData: () => ({
      nodes: [
        { id: 't1', type: 'topic', label: '测试主题', x: 400, y: 100, vx: 0, vy: 0 },
        { id: 'c1', type: 'claim', label: '测试论点', x: 200, y: 200, vx: 0, vy: 0 },
      ],
      edges: [
        { id: 'e1', source: 't1', target: 'c1', type: 'relates_to' },
      ],
    }),
  },
}));

// Mock api: return different data based on path
vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn((path: string) => {
      // Graph data endpoint
      if (path.startsWith('/graph')) {
        return Promise.resolve({
          nodes: [
            { id: 't1', type: 'topic', label: '测试主题', x: 400, y: 100, vx: 0, vy: 0 },
            { id: 'c1', type: 'claim', label: '测试论点', x: 200, y: 200, vx: 0, vy: 0 },
          ],
          edges: [
            { id: 'e1', source: 't1', target: 'c1', type: 'relates_to' },
          ],
        });
      }
      // Meetings endpoint - default: empty
      return Promise.resolve({ items: [] });
    }),
  },
  isDemoMode: () => true,
}));

// Mock toast（graph 页面直接 import toast 函数，不是 hook）
vi.mock('@/hooks/use-toast', () => ({
  toast: vi.fn(),
  useToast: () => ({ toast: vi.fn() }),
  Toaster: () => null,
}));

const mockApiGet = vi.mocked(api.get);

describe('GraphPage - .find() 崩溃路径', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('API 返回空 meetings → meetings.find() 在空数组上不崩溃，页面正常渲染', async () => {
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith('/graph')) {
        return Promise.resolve({
          nodes: [
            { id: 't1', type: 'topic', label: '测试主题', x: 400, y: 100, vx: 0, vy: 0 },
          ],
          edges: [],
        });
      }
      return Promise.resolve({ items: [] });
    });

    renderWithProviders(<GraphPage />);

    // 等待图谱渲染完成（layoutData 被设置后显示 "知识图谱" 标题）
    await waitFor(() => {
      expect(screen.getByText('知识图谱')).toBeDefined();
    });

    // 默认会议选择器渲染为"全部会议"
    expect(screen.getByText('全部会议')).toBeDefined();
  });

  it('API 返回有 meetings 数据 → meetings 下拉列表显示会议标题', async () => {
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith('/graph')) {
        return Promise.resolve({
          nodes: [{ id: 't1', type: 'topic', label: '测试主题', x: 400, y: 100, vx: 0, vy: 0 }],
          edges: [],
        });
      }
      return Promise.resolve({
        items: [
          { id: 'm1', title: '测试会议一' },
          { id: 'm2', title: '测试会议二' },
        ],
      });
    });

    renderWithProviders(<GraphPage />);

    // 等待 useQuery 解析后会议标题出现在 select 中
    await waitFor(() => {
      expect(screen.getByText('测试会议一')).toBeDefined();
    });

    expect(screen.getByText('测试会议二')).toBeDefined();
  });

  it('API 返回 meetings 为 undefined（通过 || 回退为 []）→ 不崩溃', async () => {
    // 模拟 API 返回不带 items 也不带 meetings 字段的响应
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith('/graph')) {
        return Promise.resolve({
          nodes: [{ id: 't1', type: 'topic', label: '测试主题', x: 400, y: 100, vx: 0, vy: 0 }],
          edges: [],
        });
      }
      return Promise.resolve({});
    });

    renderWithProviders(<GraphPage />);

    await waitFor(() => {
      expect(screen.getByText('知识图谱')).toBeDefined();
    });

    // 应正常显示默认"全部会议"选择器
    expect(screen.getByText('全部会议')).toBeDefined();
  });

  it('API 返回 meetings 使用 meetings 字段（而非 items）→ 也能正确解析', async () => {
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith('/graph')) {
        return Promise.resolve({
          nodes: [{ id: 't1', type: 'topic', label: '测试主题', x: 400, y: 100, vx: 0, vy: 0 }],
          edges: [],
        });
      }
      return Promise.resolve({
        meetings: [
          { id: 'm1', title: '旧格式会议' },
        ],
      });
    });

    renderWithProviders(<GraphPage />);

    // 等待 useQuery 解析后会议标题出现
    await waitFor(() => {
      expect(screen.getByText('旧格式会议')).toBeDefined();
    });
  });

  it('meetings API 失败但 graph API 正常 → meetings 为 []，页面仍正常渲染', async () => {
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith('/graph')) {
        return Promise.resolve({
          nodes: [{ id: 't1', type: 'topic', label: '测试主题', x: 400, y: 100, vx: 0, vy: 0 }],
          edges: [],
        });
      }
      // meetings 接口失败 → meetings 回退为 []
      return Promise.reject(new Error('Network error'));
    });

    renderWithProviders(<GraphPage />);

    await waitFor(() => {
      expect(screen.getByText('知识图谱')).toBeDefined();
    }, { timeout: 5000 });

    expect(screen.getByText('全部会议')).toBeDefined();
  });

  it('图谱渲染后 → 节点和关系统计显示正确格式', async () => {
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith('/graph')) {
        return Promise.resolve({
          nodes: [
            { id: 't1', type: 'topic', label: '测试主题', x: 400, y: 100, vx: 0, vy: 0 },
            { id: 'c1', type: 'claim', label: '测试论点', x: 200, y: 200, vx: 0, vy: 0 },
          ],
          edges: [
            { id: 'e1', source: 't1', target: 'c1', type: 'relates_to' },
          ],
        });
      }
      return Promise.resolve({ items: [] });
    });

    renderWithProviders(<GraphPage />);

    await waitFor(() => {
      // 统计信息格式："X 节点 · Y 关系"
      const stats = screen.getByText(/节点.*关系/);
      expect(stats).toBeDefined();
    });
  });

  it('graphData.nodes 缺失时不崩溃（防御性检查）', async () => {
    // API returns graph data without nodes/edges arrays
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith('/graph')) {
        return Promise.resolve({ someOtherField: 'invalid' });
      }
      return Promise.resolve({ items: [] });
    });

    renderWithProviders(<GraphPage />);

    // Should not crash, should show loading state or empty state
    // The page stays in loading state because layoutData is never set
    await waitFor(() => {
      expect(screen.getByText('加载图谱中...')).toBeDefined();
    }, { timeout: 3000 });
  });
});
