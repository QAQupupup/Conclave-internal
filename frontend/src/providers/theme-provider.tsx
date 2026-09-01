import * as React from 'react';
import { useUIStore } from '@/stores/ui-slice';
import { ThemeContext, type Theme } from './theme-context';

function getSystemTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(resolved: 'light' | 'dark') {
  const root = document.documentElement;
  root.classList.remove('light', 'dark');
  root.classList.add(resolved);
  root.style.colorScheme = resolved;
}

interface ThemeProviderProps {
  children: React.ReactNode;
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  // 从 useUIStore 读取和设置 theme，不再使用独立的 localStorage
  const storeTheme = useUIStore((s) => s.theme);
  const setStoreTheme = useUIStore((s) => s.setTheme);

  const [resolvedTheme, setResolvedTheme] = React.useState<'light' | 'dark'>(
    () => (storeTheme === 'system' ? getSystemTheme() : storeTheme),
  );

  // 解析并应用主题到 DOM
  React.useEffect(() => {
    const resolved = storeTheme === 'system' ? getSystemTheme() : storeTheme;
    setResolvedTheme(resolved);
    applyTheme(resolved);
  }, [storeTheme]);

  // 监听系统主题变化（仅在 theme === 'system' 时生效）
  React.useEffect(() => {
    if (storeTheme !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => {
      const resolved = getSystemTheme();
      setResolvedTheme(resolved);
      applyTheme(resolved);
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [storeTheme]);

  const setTheme = React.useCallback(
    (t: Theme) => {
      setStoreTheme(t);
    },
    [setStoreTheme],
  );

  const value = React.useMemo(
    () => ({ theme: storeTheme, setTheme, resolvedTheme }),
    [storeTheme, setTheme, resolvedTheme],
  );

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
}