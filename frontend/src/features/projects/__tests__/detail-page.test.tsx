/**
 * 项目详情页合入流程测试（/projects/:id，ADR-017 D11 两阶段确认）。
 *
 * 覆盖场景：
 * 1. 合入按钮状态门禁：仅 in_progress/conflict 显示（非正向：open 不显示）
 * 2. conflict 态处置入口：重试合入 + 重新绑会按钮齐全（D11 交回用户处置）
 * 3. 两阶段合入：干跑预览 → 确认合入 → 成功 toast（快乐路径）
 * 4. 预览有冲突 → 确认按钮禁用（非正向）
 * 5. 执行遇 409 冲突 → 展示冲突清单（非正向）
 * 6. extractMergeConflicts：全局错误格式 / FastAPI detail 格式 / 非 ApiError / 非字符串过滤
 */
import * as React from 'react';
import { Routes, Route } from 'react-router';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { api, ApiError } from '@/lib/api';
import { toast } from '@/hooks/use-toast';
import { renderWithProviders } from '@/test/test-utils';
import ProjectDetailPage from '@/features/projects/detail-page';
import { extractMergeConflicts } from '@/features/projects/merge-utils';
import type { Issue, MergeExecuteResponse, MergePreviewResponse } from '@/types';

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: {
      projects: {
        get: vi.fn(),
        listIssues: vi.fn(),
        createIssue: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        delete: vi.fn(),
      },
      issues: {
        get: vi.fn(),
        update: vi.fn(),
        delete: vi.fn(),
        merge: vi.fn(),
      },
    },
  };
});

vi.mock('@/hooks/use-toast', () => ({
  toast: vi.fn(),
  useToast: () => ({ toast: vi.fn() }),
  Toaster: () => null,
}));

const mockGet = vi.mocked(api.projects.get);
const mockListIssues = vi.mocked(api.projects.listIssues);
const mockMerge = vi.mocked(api.issues.merge);
const mockToast = vi.mocked(toast);

const PROJECT_DETAIL = {
  id: 'p1',
  slug: 'conclave',
  name: 'Conclave 平台',
  repo_url: 'https://github.com/example/conclave',
  default_branch: 'main',
  description: null,
  created_by: 'admin',
  created_at: '2026-09-01T09:00:00Z',
  updated_at: '2026-09-01T09:00:00Z',
  issue_stats: { total: 3, open: 1, scheduled: 0, in_progress: 1, conflict: 1, resolved: 0, wontfix: 0 },
};

function makeIssue(overrides: Partial<Issue> = {}): Issue {
  return {
    id: 'i1',
    project_id: 'p1',
    title: '实现登录功能',
    body: null,
    source: 'user',
    status: 'in_progress',
    priority: 50,
    assigned_meeting_id: 'm1',
    created_at: '2026-09-05T09:00:00Z',
    ...overrides,
  };
}

const PREVIEW_OK: MergePreviewResponse = {
  mode: 'preview',
  issue_id: 'i1',
  project_id: 'p1',
  meeting_id: 'm1',
  branch: 'main',
  source_committed: false,
  mergeable: true,
  changed_files: ['M\tsrc/auth.py'],
  conflicts: [],
};

const EXECUTE_OK: MergeExecuteResponse = {
  mode: 'execute',
  merged: true,
  issue_id: 'i1',
  project_id: 'p1',
  meeting_id: 'm1',
  branch: 'main',
  merge_commit_sha: 'abc123def456',
  pushed_to: 'origin/main',
  changed_files: ['M\tsrc/auth.py'],
  issue_status: 'resolved',
};

function renderDetailPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/projects/:id" element={<ProjectDetailPage />} />
    </Routes>,
    { initialEntries: ['/projects/p1'] },
  );
}

function mockPageReady(issues: Issue[]) {
  mockGet.mockResolvedValue(PROJECT_DETAIL as never);
  mockListIssues.mockResolvedValue({ items: issues, total: issues.length } as never);
}

describe('ProjectDetailPage 合入入口（ADR-017 D11）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('合入按钮状态门禁：in_progress 显示，open 不显示（非正向）', async () => {
    mockPageReady([
      makeIssue(),
      makeIssue({ id: 'i2', title: '优化性能', status: 'open', assigned_meeting_id: null }),
    ]);

    renderDetailPage();

    await waitFor(() => {
      expect(screen.getByText('实现登录功能')).toBeDefined();
    });
    expect(screen.getByText('优化性能')).toBeDefined();
    // 仅 in_progress 一条议题可合入
    expect(screen.getAllByText('合入')).toHaveLength(1);
  });

  it('conflict 态处置入口：重试合入 + 重新绑会按钮齐全（D11）', async () => {
    mockPageReady([makeIssue({ id: 'i3', title: '冲突议题', status: 'conflict' })]);

    renderDetailPage();

    await waitFor(() => {
      expect(screen.getByText('冲突议题')).toBeDefined();
    });
    // conflict 态：可重试合入（合入按钮）+ 可重新绑会（发起会议按钮）
    expect(screen.getByText('合入')).toBeDefined();
    expect(screen.getByText('发起会议')).toBeDefined();
    // 「合入冲突」同时出现在状态过滤 pill 与行徽章（共 2 处）
    expect(screen.getAllByText('合入冲突')).toHaveLength(2);
  });

  it('两阶段合入：干跑预览 → 确认合入 → 成功 toast', async () => {
    mockPageReady([makeIssue()]);
    mockMerge.mockImplementation(async (_id: string, confirm: boolean) =>
      confirm ? EXECUTE_OK : PREVIEW_OK,
    );

    renderDetailPage();

    await waitFor(() => {
      expect(screen.getByText('实现登录功能')).toBeDefined();
    });
    fireEvent.click(screen.getByText('合入'));

    // 第一阶段：打开即干跑预览（confirm=false，不落状态）
    await waitFor(() => {
      expect(mockMerge).toHaveBeenCalledWith('i1', false);
    });
    await waitFor(() => {
      expect(screen.getByText(/目标分支：main/)).toBeDefined();
    });
    // 变更清单 "M\tpath" 渲染（空白规范化后用正则匹配）
    expect(screen.getByText(/M\s+src\/auth\.py/)).toBeDefined();

    // 第二阶段：确认后正式合入（confirm=true）
    fireEvent.click(screen.getByText('确认合入'));
    await waitFor(() => {
      expect(mockMerge).toHaveBeenCalledWith('i1', true);
    });
    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({ title: '已合入 main' }));
    });
  });

  it('预览有冲突 → 确认按钮禁用，仅展示冲突清单（非正向）', async () => {
    mockPageReady([makeIssue()]);
    mockMerge.mockResolvedValue({
      ...PREVIEW_OK,
      mergeable: false,
      conflicts: ['src/auth.py'],
    } as never);

    renderDetailPage();

    await waitFor(() => {
      expect(screen.getByText('实现登录功能')).toBeDefined();
    });
    fireEvent.click(screen.getByText('合入'));

    await waitFor(() => {
      expect(screen.getByText(/合并冲突/)).toBeDefined();
    });
    expect(screen.getByText('src/auth.py')).toBeDefined();
    // 有冲突时不得确认合入
    expect(screen.queryByText('确认合入')).toBeNull();
  });

  it('执行遇 409 冲突 → 展示冲突清单并收起确认按钮（非正向）', async () => {
    mockPageReady([makeIssue()]);
    mockMerge.mockImplementation(async (_id: string, confirm: boolean) => {
      if (!confirm) return PREVIEW_OK;
      throw new ApiError('合并冲突', 409, {
        error: { code: 'MERGE_CONFLICT', message: '合并冲突', details: { conflicts: ['src/core.py'] } },
      });
    });

    renderDetailPage();

    await waitFor(() => {
      expect(screen.getByText('实现登录功能')).toBeDefined();
    });
    fireEvent.click(screen.getByText('合入'));
    await waitFor(() => {
      expect(screen.getByText('确认合入')).toBeDefined();
    });

    fireEvent.click(screen.getByText('确认合入'));

    await waitFor(() => {
      expect(mockMerge).toHaveBeenCalledWith('i1', true);
    });
    // 后端已将议题置 conflict 态，弹窗展示冲突清单
    await waitFor(() => {
      expect(screen.getByText('src/core.py')).toBeDefined();
    });
    expect(screen.queryByText('确认合入')).toBeNull();
  });
});

describe('extractMergeConflicts 冲突清单提取', () => {
  it('全局错误格式：error.details.conflicts', () => {
    const err = new ApiError('合并冲突', 409, {
      error: { details: { conflicts: ['a.py', 'b.py'] } },
    });
    expect(extractMergeConflicts(err)).toEqual(['a.py', 'b.py']);
  });

  it('FastAPI 原生 detail 格式兼容', () => {
    const err = new ApiError('x', 409, { detail: { conflicts: ['c.py'] } });
    expect(extractMergeConflicts(err)).toEqual(['c.py']);
  });

  it('非 ApiError → 空清单（非正向）', () => {
    expect(extractMergeConflicts(new Error('boom'))).toEqual([]);
    expect(extractMergeConflicts(null)).toEqual([]);
  });

  it('conflicts 中非字符串元素被过滤（非正向）', () => {
    const err = new ApiError('x', 409, {
      error: { details: { conflicts: ['a.py', 123, null] } },
    });
    expect(extractMergeConflicts(err)).toEqual(['a.py']);
  });
});
