/**
 * CanvasRail 悬浮画布入口徽标轨测试
 *
 * 覆盖场景：
 * 1. 渲染 4 个入口徽标（冲突与证据/相关会议/可观测/操作回放）
 * 2. 点击徽标打开对应画布（写入 ui-slice.activeCanvas）
 * 3. 再次点击当前激活徽标收起画布（toggle）
 * 4. 单焦点互斥：切换到另一个徽标替换当前画布
 * 5. 冲突徽标显示数量角标（冲突条目 + 支撑边）
 * 6. 无冲突数据时不渲染角标（边界）
 */
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { CanvasRail } from '@/components/meeting/canvas-rail';
import { useUIStore } from '@/stores/ui-slice';
import { renderWithProviders } from '@/test/test-utils';
import { api } from '@/lib/api';
import { useMeetingDetailRaw } from '@/hooks/use-meetings';

vi.mock('@/hooks/use-meetings', () => ({
  useMeetingDetailRaw: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: {
    graphOverview: vi.fn(),
  },
}));

const mockDetail = useMeetingDetailRaw as Mock;
const mockGraphOverview = api.graphOverview as Mock;

describe('CanvasRail', () => {
  beforeEach(() => {
    useUIStore.setState({ activeCanvas: null, insightsCanvasSize: 'M' });
    mockDetail.mockReturnValue({ data: undefined, isLoading: false });
    mockGraphOverview.mockResolvedValue({ edges: [] });
    vi.clearAllMocks();
  });

  it('渲染 4 个画布入口徽标', () => {
    renderWithProviders(<CanvasRail meetingId="m1" />);
    expect(screen.getByLabelText('冲突与证据')).toBeDefined();
    expect(screen.getByLabelText('相关会议')).toBeDefined();
    expect(screen.getByLabelText('可观测')).toBeDefined();
    expect(screen.getByLabelText('操作回放')).toBeDefined();
  });

  it('点击徽标打开对应画布并标记按压态', () => {
    renderWithProviders(<CanvasRail meetingId="m1" />);
    const badge = screen.getByLabelText('冲突与证据');
    fireEvent.click(badge);
    expect(useUIStore.getState().activeCanvas).toBe('conflicts');
    expect(screen.getByLabelText('冲突与证据').getAttribute('aria-pressed')).toBe('true');
  });

  it('再次点击当前激活徽标收起画布（toggle）', () => {
    useUIStore.setState({ activeCanvas: 'conflicts' });
    renderWithProviders(<CanvasRail meetingId="m1" />);
    fireEvent.click(screen.getByLabelText('冲突与证据'));
    expect(useUIStore.getState().activeCanvas).toBeNull();
  });

  it('点击其他徽标替换当前画布（单焦点互斥）', () => {
    useUIStore.setState({ activeCanvas: 'conflicts' });
    renderWithProviders(<CanvasRail meetingId="m1" />);
    fireEvent.click(screen.getByLabelText('操作回放'));
    expect(useUIStore.getState().activeCanvas).toBe('replay');
  });

  it('冲突徽标显示数量角标（冲突条目 + 支撑边）', async () => {
    mockDetail.mockReturnValue({
      data: { conflicts: [{ summary: 'a' }, { summary: 'b' }] },
      isLoading: false,
    });
    mockGraphOverview.mockResolvedValue({
      edges: [{ type: 'supports' }, { type: 'contradicts' }],
    });
    renderWithProviders(<CanvasRail meetingId="m1" />);
    // 2 条冲突 + 1 条支撑边 = 3（contradicts 不计入）
    await waitFor(() => {
      expect(screen.getByText('3')).toBeDefined();
    });
  });

  it('无冲突数据时不渲染数量角标（边界）', async () => {
    mockDetail.mockReturnValue({ data: { conflicts: [] }, isLoading: false });
    mockGraphOverview.mockResolvedValue({ edges: [] });
    renderWithProviders(<CanvasRail meetingId="m1" />);
    await waitFor(() => {
      expect(mockGraphOverview).toHaveBeenCalled();
    });
    expect(screen.queryByText('0')).toBeNull();
  });
});
