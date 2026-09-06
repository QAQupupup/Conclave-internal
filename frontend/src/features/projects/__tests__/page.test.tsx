/**
 * 项目列表页测试（/projects，ADR-017 Phase 2 前端接线）。
 *
 * 覆盖场景：
 * 1. 列表渲染：项目名、标识、议题数、统计页脚
 * 2. 点击行 → 进入项目详情页（路由跳转）
 * 3. 空列表 → 空态引导文案
 * 4. 加载失败 → error toast（非正向）
 */
import * as React from 'react';
import { Routes, Route } from 'react-router';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { api } from '@/lib/api';
import { toast } from '@/hooks/use-toast';
import { renderWithProviders } from '@/test/test-utils';
import ProjectsPage from '@/features/projects/page';

vi.mock('@/lib/api', () => ({
  api: {
    projects: {
      list: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
    issues: {
      get: vi.fn(),
    },
  },
}));

vi.mock('@/hooks/use-toast', () => ({
  toast: vi.fn(),
  useToast: () => ({ toast: vi.fn() }),
  Toaster: () => null,
}));

const mockList = vi.mocked(api.projects.list);
const mockToast = vi.mocked(toast);

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/projects" element={<ProjectsPage />} />
      <Route path="/projects/:id" element={<div>DETAIL_MARKER</div>} />
    </Routes>,
    { initialEntries: ['/projects'] },
  );
}

const SAMPLE_PROJECTS = {
  items: [
    {
      id: 'p1',
      slug: 'conclave',
      name: 'Conclave 平台',
      repo_url: 'https://github.com/example/conclave',
      default_branch: 'main',
      description: '多智能体协作决策平台',
      created_by: 'admin',
      created_at: '2026-09-01T09:00:00Z',
      updated_at: '2026-09-01T09:00:00Z',
      issue_total: 3,
    },
    {
      id: 'p2',
      slug: 'docs-site',
      name: '文档站',
      repo_url: null,
      default_branch: 'main',
      description: null,
      created_by: 'admin',
      created_at: '2026-09-02T09:00:00Z',
      updated_at: '2026-09-02T09:00:00Z',
      issue_total: 0,
    },
  ],
  total: 2,
};

describe('ProjectsPage 项目列表页', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('列表渲染 → 项目名、标识、议题数与统计页脚齐全', async () => {
    mockList.mockResolvedValue(SAMPLE_PROJECTS as never);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Conclave 平台')).toBeDefined();
    });
    expect(screen.getByText('conclave')).toBeDefined();
    expect(screen.getByText('文档站')).toBeDefined();
    expect(screen.getByText('3')).toBeDefined();
    expect(screen.getByText(/共 2 个项目/)).toBeDefined();
  });

  it('点击项目行 → 进入详情页', async () => {
    mockList.mockResolvedValue(SAMPLE_PROJECTS as never);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Conclave 平台')).toBeDefined();
    });
    fireEvent.click(screen.getByText('Conclave 平台'));

    await waitFor(() => {
      expect(screen.getByText('DETAIL_MARKER')).toBeDefined();
    });
  });

  it('空列表 → 显示空态引导', async () => {
    mockList.mockResolvedValue({ items: [], total: 0 } as never);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('暂无项目')).toBeDefined();
    });
    expect(screen.getByText('项目是议题池的命名空间，可绑定代码仓库')).toBeDefined();
  });

  it('加载失败 → 弹出 error toast（非正向）', async () => {
    mockList.mockRejectedValue(new Error('服务不可用'));

    renderPage();

    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: '加载项目列表失败', variant: 'error' }),
      );
    });
  });
});
