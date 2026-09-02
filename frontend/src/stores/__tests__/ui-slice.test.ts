/**
 * ui-slice 悬浮画布状态测试
 *
 * 覆盖场景：
 * 1. openCanvas 设置当前展开画布
 * 2. 打开另一个画布自动替换当前画布（单焦点互斥）
 * 3. closeCanvas 收起画布
 * 4. 无画布展开时 closeCanvas 幂等（边界）
 * 5. setInsightsCanvasSize 双向切换（M→XL 升档 / XL→M 降档）
 * 6. setReplayCanvasSize 默认 L 档且可切换（边界）
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useUIStore } from '@/stores/ui-slice';

describe('ui-slice 悬浮画布状态', () => {
  beforeEach(() => {
    useUIStore.setState({ activeCanvas: null, insightsCanvasSize: 'M', replayCanvasSize: 'L' });
  });

  it('openCanvas 设置当前展开的画布', () => {
    useUIStore.getState().openCanvas('conflicts');
    expect(useUIStore.getState().activeCanvas).toBe('conflicts');
  });

  it('打开另一个画布自动替换当前画布（单焦点互斥）', () => {
    const { openCanvas } = useUIStore.getState();
    openCanvas('conflicts');
    openCanvas('replay');
    expect(useUIStore.getState().activeCanvas).toBe('replay');
  });

  it('closeCanvas 收起当前画布', () => {
    useUIStore.getState().openCanvas('related');
    useUIStore.getState().closeCanvas();
    expect(useUIStore.getState().activeCanvas).toBeNull();
  });

  it('无画布展开时 closeCanvas 保持 null（幂等边界）', () => {
    useUIStore.getState().closeCanvas();
    expect(useUIStore.getState().activeCanvas).toBeNull();
  });

  it('setInsightsCanvasSize 支持双向切换（升档与降档）', () => {
    const { setInsightsCanvasSize } = useUIStore.getState();
    // 升档：M → L → XL
    setInsightsCanvasSize('L');
    expect(useUIStore.getState().insightsCanvasSize).toBe('L');
    setInsightsCanvasSize('XL');
    expect(useUIStore.getState().insightsCanvasSize).toBe('XL');
    // 降档：XL → M
    setInsightsCanvasSize('M');
    expect(useUIStore.getState().insightsCanvasSize).toBe('M');
  });

  it('replayCanvasSize 默认 L 档，setReplayCanvasSize 可切换（边界）', () => {
    expect(useUIStore.getState().replayCanvasSize).toBe('L');
    useUIStore.getState().setReplayCanvasSize('XL');
    expect(useUIStore.getState().replayCanvasSize).toBe('XL');
  });
});
