import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type Theme = 'light' | 'dark' | 'system';

interface UIState {
  theme: Theme;
  timelineWidth: number;
  thoughtTreeWidth: number;
  timelineCollapsed: boolean;
  thoughtTreeCollapsed: boolean;
  commandPaletteOpen: boolean;
  setTheme: (theme: Theme) => void;
  setTimelineWidth: (w: number) => void;
  setThoughtTreeWidth: (w: number) => void;
  toggleTimeline: () => void;
  toggleThoughtTree: () => void;
  setTimelineCollapsed: (collapsed: boolean) => void;
  setThoughtTreeCollapsed: (collapsed: boolean) => void;
  openCommandPalette: () => void;
  closeCommandPalette: () => void;
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
      setTheme: (theme) => set({ theme }),
      setTimelineWidth: (timelineWidth) => set({ timelineWidth }),
      setThoughtTreeWidth: (thoughtTreeWidth) => set({ thoughtTreeWidth }),
      toggleTimeline: () => set({ timelineCollapsed: !get().timelineCollapsed }),
      toggleThoughtTree: () => set({ thoughtTreeCollapsed: !get().thoughtTreeCollapsed }),
      setTimelineCollapsed: (collapsed) => set({ timelineCollapsed: collapsed }),
      setThoughtTreeCollapsed: (collapsed) => set({ thoughtTreeCollapsed: collapsed }),
      openCommandPalette: () => set({ commandPaletteOpen: true }),
      closeCommandPalette: () => set({ commandPaletteOpen: false }),
    }),
    {
      name: 'conclave:ui:layout',
      version: 1,
      partialize: (state) => ({
        theme: state.theme,
        timelineWidth: state.timelineWidth,
        thoughtTreeWidth: state.thoughtTreeWidth,
        timelineCollapsed: state.timelineCollapsed,
        thoughtTreeCollapsed: state.thoughtTreeCollapsed,
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
        // Version 0 → 1: fill missing fields with defaults
        if (version < 1) {
          const s = persistedState as Record<string, unknown> | undefined;
          return {
            theme: (s?.theme as Theme) ?? 'system',
            timelineWidth: (s?.timelineWidth as number) ?? DEFAULT_TIMELINE_WIDTH,
            thoughtTreeWidth: (s?.thoughtTreeWidth as number) ?? DEFAULT_THOUGHT_TREE_WIDTH,
            timelineCollapsed: (s?.timelineCollapsed as boolean) ?? true,
            thoughtTreeCollapsed: (s?.thoughtTreeCollapsed as boolean) ?? true,
          };
        }
        return persistedState;
      },
    }
  )
);
