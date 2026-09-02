import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { FloatingPanelSize } from '@/components/ui/floating-panel-sizing';

type Theme = 'light' | 'dark' | 'system';

/**
 * 悬浮画布类别（单焦点：同一时刻最多展开一个画布）。
 * conflicts/related/observability 共用 M 档洞察画布（tab 即画布），replay 为独立 L 档画布。
 */
export type CanvasKind = 'conflicts' | 'related' | 'observability' | 'replay';

interface UIState {
  theme: Theme;
  timelineWidth: number;
  thoughtTreeWidth: number;
  timelineCollapsed: boolean;
  thoughtTreeCollapsed: boolean;
  commandPaletteOpen: boolean;
  /** 当前展开的悬浮画布；null 表示全部收起 */
  activeCanvas: CanvasKind | null;
  /** 洞察画布档位记忆（M/L/XL 双向切换 + 拖拽吸附） */
  insightsCanvasSize: FloatingPanelSize;
  /** 操作回放画布档位记忆（默认 L 档） */
  replayCanvasSize: FloatingPanelSize;
  setTheme: (theme: Theme) => void;
  setTimelineWidth: (w: number) => void;
  setThoughtTreeWidth: (w: number) => void;
  toggleTimeline: () => void;
  toggleThoughtTree: () => void;
  setTimelineCollapsed: (collapsed: boolean) => void;
  setThoughtTreeCollapsed: (collapsed: boolean) => void;
  openCommandPalette: () => void;
  closeCommandPalette: () => void;
  /** 打开画布（单焦点互斥：自动替换当前展开的画布） */
  openCanvas: (kind: CanvasKind) => void;
  closeCanvas: () => void;
  /** 洞察画布档位切换（可升可降，拖拽吸附与档位切换器共用） */
  setInsightsCanvasSize: (size: FloatingPanelSize) => void;
  /** 操作回放画布档位切换 */
  setReplayCanvasSize: (size: FloatingPanelSize) => void;
}

const DEFAULT_TIMELINE_WIDTH = 260;
const DEFAULT_THOUGHT_TREE_WIDTH = 340;

// 旧版本 theme-provider 使用的 localStorage key，用于迁移
const LEGACY_THEME_KEY = 'conclave:ui:theme';

export const useUIStore = create<UIState>()(
  persist(
    (set, get) => ({
      theme: 'system',
      timelineWidth: DEFAULT_TIMELINE_WIDTH,
      thoughtTreeWidth: DEFAULT_THOUGHT_TREE_WIDTH,
      timelineCollapsed: true,
      thoughtTreeCollapsed: true,
      commandPaletteOpen: false,
      activeCanvas: null,
      insightsCanvasSize: 'M',
      replayCanvasSize: 'L',
      setTheme: (theme) => set({ theme }),
      setTimelineWidth: (timelineWidth) => set({ timelineWidth }),
      setThoughtTreeWidth: (thoughtTreeWidth) => set({ thoughtTreeWidth }),
      toggleTimeline: () => set({ timelineCollapsed: !get().timelineCollapsed }),
      toggleThoughtTree: () => set({ thoughtTreeCollapsed: !get().thoughtTreeCollapsed }),
      setTimelineCollapsed: (collapsed) => set({ timelineCollapsed: collapsed }),
      setThoughtTreeCollapsed: (collapsed) => set({ thoughtTreeCollapsed: collapsed }),
      openCommandPalette: () => set({ commandPaletteOpen: true }),
      closeCommandPalette: () => set({ commandPaletteOpen: false }),
      openCanvas: (kind) => set({ activeCanvas: kind }),
      closeCanvas: () => set({ activeCanvas: null }),
      setInsightsCanvasSize: (insightsCanvasSize) => set({ insightsCanvasSize }),
      setReplayCanvasSize: (replayCanvasSize) => set({ replayCanvasSize }),
    }),
    {
      name: 'conclave:ui:layout',
      version: 3,
      // activeCanvas 不持久化：进入页面默认全部收起，徽标轨是唯一入口
      partialize: (state) => ({
        theme: state.theme,
        timelineWidth: state.timelineWidth,
        thoughtTreeWidth: state.thoughtTreeWidth,
        timelineCollapsed: state.timelineCollapsed,
        thoughtTreeCollapsed: state.thoughtTreeCollapsed,
        insightsCanvasSize: state.insightsCanvasSize,
        replayCanvasSize: state.replayCanvasSize,
      }),
      onRehydrateStorage: () => (state) => {
        // 迁移旧版本的 theme 设置（从独立的 conclave:ui:theme key 迁移）
        if (state) {
          try {
            const legacyTheme = localStorage.getItem(LEGACY_THEME_KEY) as Theme | null;
            if (legacyTheme && ['light', 'dark', 'system'].includes(legacyTheme)) {
              // 如果存储中没有 theme 值（首次迁移），使用旧值
              if (state.theme === 'system') {
                state.setTheme(legacyTheme);
              }
              // 清理旧 key
              localStorage.removeItem(LEGACY_THEME_KEY);
            }
          } catch {
            // 忽略 localStorage 访问错误
          }
        }
      },
      migrate: (persistedState: unknown, version: number) => {
        const s = persistedState as Record<string, unknown> | undefined;
        // 档位合法性校验：非法值（旧版本或脏数据）回落到指定默认档
        const validSize = (v: unknown, fallback: FloatingPanelSize): FloatingPanelSize =>
          v === 'M' || v === 'L' || v === 'XL' ? v : fallback;
        // Version 0 → 1: fill missing fields with defaults
        if (version < 1) {
          return {
            theme: (s?.theme as Theme) ?? 'system',
            timelineWidth: (s?.timelineWidth as number) ?? DEFAULT_TIMELINE_WIDTH,
            thoughtTreeWidth: (s?.thoughtTreeWidth as number) ?? DEFAULT_THOUGHT_TREE_WIDTH,
            timelineCollapsed: (s?.timelineCollapsed as boolean) ?? true,
            thoughtTreeCollapsed: (s?.thoughtTreeCollapsed as boolean) ?? true,
            insightsCanvasSize: 'M',
            replayCanvasSize: 'L',
          };
        }
        // Version 1 → 2: 新增悬浮画布档位记忆
        if (version < 2) {
          return { ...s, insightsCanvasSize: validSize(s?.insightsCanvasSize, 'M'), replayCanvasSize: 'L' };
        }
        // Version 2 → 3: 档位扩展 XL + 回放画布档位记忆
        if (version < 3) {
          return {
            ...s,
            insightsCanvasSize: validSize(s?.insightsCanvasSize, 'M'),
            replayCanvasSize: validSize(s?.replayCanvasSize, 'L'),
          };
        }
        return persistedState;
      },
    }
  )
);
