/**
 * 悬浮画布档位纯逻辑层 —— 档位定义、像素宽度读取、拖拽吸附。
 *
 * 从 floating-panel.tsx 抽出的原因：组件文件只允许导出组件
 * （react-refresh/only-export-components），常量与纯函数必须独立成文件。
 * 本文件不依赖 React，可在任意环境单测。
 */

export type FloatingPanelSize = 'M' | 'L' | 'XL';

/** 档位顺序（从小到大）：档位切换器与吸附遍历共用 */
export const SIZE_ORDER: readonly FloatingPanelSize[] = ['M', 'L', 'XL'];

/** CSS 变量缺失时的档位像素兜底值（与 app.css --panel-width-* 一致） */
export const FALLBACK_TIER_WIDTHS: Record<FloatingPanelSize, number> = { M: 448, L: 720, XL: 992 };

/** 读取根字号（rem → px 换算用），jsdom/异常环境退回 16 */
function readRootFontSize(): number {
  try {
    const px = parseFloat(getComputedStyle(document.documentElement).fontSize);
    return Number.isFinite(px) && px > 0 ? px : 16;
  } catch {
    return 16;
  }
}

/** 从 CSS 变量读取三档实际像素宽度，缺失时用兜底常量 */
export function readTierWidths(): Record<FloatingPanelSize, number> {
  if (typeof window === 'undefined') return FALLBACK_TIER_WIDTHS;
  const style = getComputedStyle(document.documentElement);
  const rootFont = readRootFontSize();
  const read = (varName: string, fallback: number): number => {
    const raw = style.getPropertyValue(varName).trim();
    const num = parseFloat(raw);
    if (!Number.isFinite(num) || num <= 0) return fallback;
    if (raw.endsWith('rem')) return num * rootFont;
    if (raw.endsWith('px')) return num;
    return fallback;
  };
  return {
    M: read('--panel-width-m', FALLBACK_TIER_WIDTHS.M),
    L: read('--panel-width-l', FALLBACK_TIER_WIDTHS.L),
    XL: read('--panel-width-xl', FALLBACK_TIER_WIDTHS.XL),
  };
}

/**
 * 拖拽宽度吸附：返回与给定宽度最接近的档位。
 * 纯函数，抽出便于单测（拖拽链路本身依赖布局尺寸，不做集成测试）。
 */
export function snapWidthToSize(
  widthPx: number,
  tierWidths: Record<FloatingPanelSize, number>,
): FloatingPanelSize {
  let best: FloatingPanelSize = 'M';
  let bestDist = Infinity;
  for (const s of SIZE_ORDER) {
    const dist = Math.abs(widthPx - tierWidths[s]);
    if (dist < bestDist) {
      bestDist = dist;
      best = s;
    }
  }
  return best;
}
