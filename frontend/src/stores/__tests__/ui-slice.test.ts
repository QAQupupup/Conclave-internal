/**
 * ui-slice 悬浮画布状态测试
 *
 * 覆盖场景：
 * 1. openCanvas 设置当前展开画布
 * 2. 打开另一个画布自动替换当前画布（单焦点互斥）
 * 3. closeCanvas 收起画布
 * 4. 无画布展开时 closeCanvas 幂等（边界）
 * 5. upgradeInsightsCanvas M → L 升档
 * 6. 已为 L 档时升档幂等，无降档路径（边界）
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useUIStore } from '@/stores/ui-slice';

describe('ui-slice 悬浮画布状态', () => {
  beforeEach(() => {
    useUIStore.setState({ activeCanvas: null, insightsCanvasSize: 'M' });
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

  it('upgradeInsightsCanvas 将洞察画布从 M 升到 L', () => {
    useUIStore.getState().upgradeInsightsCanvas();
    expect(useUIStore.getState().insightsCanvasSize).toBe('L');
  });

  it('已为 L 档时 upgradeInsightsCanvas 保持 L（无降档，幂等）', () => {
    useUIStore.setState({ insightsCanvasSize: 'L' });
    useUIStore.getState().upgradeInsightsCanvas();
    expect(useUIStore.getState().insightsCanvasSize).toBe('L');
  });
});
