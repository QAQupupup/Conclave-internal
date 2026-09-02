/**
 * 悬浮画布档位纯逻辑测试（floating-panel-sizing.ts）
 *
 * 覆盖场景：
 * 1. snapWidthToSize 就近吸附（常规值）
 * 2. snapWidthToSize 边界：极小/极大宽度
 * 3. snapWidthToSize 两档中点确定性（严格小于才换档）
 * 4. readTierWidths CSS 变量缺失时回退兜底常量（异常路径）
 * 5. readTierWidths rem 单位按根字号换算
 * 6. readTierWidths 非法值（负数/无法解析）回退兜底常量
 */
import { describe, it, expect, afterEach } from 'vitest';
import {
  snapWidthToSize,
  readTierWidths,
  FALLBACK_TIER_WIDTHS,
  SIZE_ORDER,
} from '@/components/ui/floating-panel-sizing';

describe('snapWidthToSize（拖拽宽度吸附）', () => {
  /* 与兜底档位宽度一致：M=448 L=720 XL=992 */
  const tiers = { M: 448, L: 720, XL: 992 };

  it('就近吸附到档位', () => {
    expect(snapWidthToSize(460, tiers)).toBe('M');
    expect(snapWidthToSize(700, tiers)).toBe('L');
    expect(snapWidthToSize(950, tiers)).toBe('XL');
  });

  it('边界：极小宽度吸附 M，极大宽度吸附 XL', () => {
    expect(snapWidthToSize(320, tiers)).toBe('M');
    expect(snapWidthToSize(2000, tiers)).toBe('XL');
  });

  it('两档中点偏向较小档（严格小于才换档，保证确定性）', () => {
    // M/L 中点 = 584：恰在中点时距离相等，取先遍历到的 M
    expect(snapWidthToSize(584, tiers)).toBe('M');
    expect(snapWidthToSize(585, tiers)).toBe('L');
  });
});

describe('readTierWidths（CSS 变量读取）', () => {
  const rootStyle = document.documentElement.style;

  afterEach(() => {
    // 清理用例对根节点内联样式的修改，避免跨用例污染
    rootStyle.removeProperty('--panel-width-m');
    rootStyle.removeProperty('--panel-width-l');
    rootStyle.removeProperty('--panel-width-xl');
  });

  it('CSS 变量缺失时回退兜底常量（异常路径）', () => {
    // jsdom 环境未加载 app.css，三个变量均未定义
    expect(readTierWidths()).toEqual(FALLBACK_TIER_WIDTHS);
  });

  it('rem 单位按根字号换算为像素', () => {
    // jsdom 默认根字号 16px：30rem = 480px
    rootStyle.setProperty('--panel-width-m', '30rem');
    expect(readTierWidths().M).toBe(480);
    // 未设置的档位仍走兜底
    expect(readTierWidths().L).toBe(FALLBACK_TIER_WIDTHS.L);
  });

  it('px 单位直接取值', () => {
    rootStyle.setProperty('--panel-width-l', '800px');
    expect(readTierWidths().L).toBe(800);
  });

  it('非法值（负数/无法解析）回退兜底常量', () => {
    rootStyle.setProperty('--panel-width-m', '-10px');
    rootStyle.setProperty('--panel-width-xl', 'abc');
    expect(readTierWidths().M).toBe(FALLBACK_TIER_WIDTHS.M);
    expect(readTierWidths().XL).toBe(FALLBACK_TIER_WIDTHS.XL);
  });

  it('SIZE_ORDER 覆盖全部档位且升序排列', () => {
    expect(SIZE_ORDER).toEqual(['M', 'L', 'XL']);
  });
});
