/**
 * ThemeContext：主题管理（亮/暗切换 + Token 级覆盖 + 后端同步）
 *
 * 职责：
 * 1. 亮/暗主题切换，通过 document.documentElement.setAttribute('data-theme', ...) 生效
 * 2. Token 级覆盖：用户可逐项调整任意 CSS 变量（主色、圆角、字号等）
 * 3. 后端同步：启动时 GET /preferences/ 拉取，变更时 PUT /preferences/{key} 回写
 * 4. 本地 localStorage 即时生效，后端异步同步（离线可用）
 *
 * 设计原则：
 * - 默认主题在 index.css :root 中定义，此处只做覆盖（override）
 * - 覆盖通过 document.documentElement.style.setProperty('--token', value) 注入
 * - 重置时 removeProperty 恢复 :root 默认值
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { usePersistentState } from '../hooks/usePersistentState'
import { getPreferences, setPreference } from '../lib/api'

// ========== 类型定义 ==========

type ThemeMode = 'light' | 'dark'

/** 可覆盖的 token 定义，key 为 CSS 变量名（不含 --），value 为用户设定的值 */
type TokenOverrides = Record<string, string>

interface ThemeContextValue {
  /** 当前主题模式 */
  mode: ThemeMode
  /** 切换亮/暗 */
  toggleMode: () => void
  /** 设置主题模式 */
  setMode: (mode: ThemeMode) => void
  /** 当前 token 覆盖 */
  overrides: TokenOverrides
  /** 设置单个 token 覆盖 */
  setTokenOverride: (token: string, value: string) => void
  /** 重置单个 token 到默认 */
  resetToken: (token: string) => void
  /** 重置所有 token */
  resetAllTokens: () => void
  /** 后端同步状态 */
  syncStatus: 'idle' | 'syncing' | 'synced' | 'error'
}

// ========== 常量 ==========

const STORAGE_KEY_MODE = 'conclave-theme-mode'
const STORAGE_KEY_OVERRIDES = 'conclave-theme-overrides'

/** 白名单：允许用户覆盖的 token（防止注入任意 CSS 变量） */
export const OVERRIDABLE_TOKENS: Record<string, { label: string; type: 'color' | 'size' | 'font'; group: string }> = {
  'accent': { label: '主色', type: 'color', group: '色彩' },
  'accent-hover': { label: '主色悬停', type: 'color', group: '色彩' },
  'bg': { label: '主背景', type: 'color', group: '色彩' },
  'bg-secondary': { label: '次级背景', type: 'color', group: '色彩' },
  'text': { label: '主文字', type: 'color', group: '色彩' },
  'text-secondary': { label: '次级文字', type: 'color', group: '色彩' },
  'border': { label: '边框', type: 'color', group: '色彩' },
  'success': { label: '成功色', type: 'color', group: '语义色' },
  'warn': { label: '警告色', type: 'color', group: '语义色' },
  'danger': { label: '危险色', type: 'color', group: '语义色' },
  'radius': { label: '基础圆角', type: 'size', group: '形状' },
  'radius-md': { label: '卡片圆角', type: 'size', group: '形状' },
  'radius-lg': { label: '大圆角', type: 'size', group: '形状' },
  'font-sans': { label: '正文字体', type: 'font', group: '字体' },
  'font-mono': { label: '等宽字体', type: 'font', group: '字体' },
}

// ========== Context ==========

const ThemeContext = createContext<ThemeContextValue | null>(null)

// ========== Provider ==========

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = usePersistentState<ThemeMode>(STORAGE_KEY_MODE, 'light')
  const [overrides, setOverrides] = usePersistentState<TokenOverrides>(STORAGE_KEY_OVERRIDES, {})
  const [syncStatus, setSyncStatus] = useState<'idle' | 'syncing' | 'synced' | 'error'>('idle')
  const syncTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 应用主题模式到 <html data-theme="...">
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode)
  }, [mode])

  // 应用 token 覆盖到 :root
  useEffect(() => {
    const root = document.documentElement
    // 先清除所有旧覆盖，再应用新的
    Object.keys(OVERRIDABLE_TOKENS).forEach(token => {
      root.style.removeProperty(`--${token}`)
    })
    Object.entries(overrides).forEach(([token, value]) => {
      if (OVERRIDABLE_TOKENS[token]) {
        root.style.setProperty(`--${token}`, value)
      }
    })
  }, [overrides])

  // 启动时从后端拉取偏好（静默，不覆盖本地已有的）
  useEffect(() => {
    let cancelled = false
    async function fetchPreferences() {
      try {
        setSyncStatus('syncing')
        const data = await getPreferences()
        if (cancelled) return

        // 后端的 theme-mode 覆盖本地（仅在本地为默认值时）
        if (data['theme-mode'] && data['theme-mode'] !== mode) {
          setModeState(data['theme-mode'] as ThemeMode)
        }
        // 后端的 token 覆盖（merge，本地优先）
        if (data['token-overrides']) {
          try {
            const remoteOverrides = JSON.parse(data['token-overrides'])
            setOverrides(prev => ({ ...remoteOverrides, ...prev }))
          } catch { /* ignore malformed JSON */ }
        }
        setSyncStatus('synced')
      } catch {
        if (!cancelled) setSyncStatus('error')
      }
    }
    fetchPreferences()
    return () => { cancelled = true }
  }, [])

  // 同步 theme-mode 到后端（debounce）
  const syncModeToBackend = useCallback((newMode: ThemeMode) => {
    if (syncTimer.current) clearTimeout(syncTimer.current)
    syncTimer.current = setTimeout(async () => {
      try {
        await setPreference('theme-mode', newMode)
        setSyncStatus('synced')
      } catch {
        setSyncStatus('error')
      }
    }, 500)
  }, [])

  // 同步 token-overrides 到后端（debounce）
  const syncOverridesToBackend = useCallback((newOverrides: TokenOverrides) => {
    if (syncTimer.current) clearTimeout(syncTimer.current)
    syncTimer.current = setTimeout(async () => {
      try {
        await setPreference('token-overrides', JSON.stringify(newOverrides))
        setSyncStatus('synced')
      } catch {
        setSyncStatus('error')
      }
    }, 800)
  }, [])

  const setMode = useCallback((newMode: ThemeMode) => {
    setModeState(newMode)
    syncModeToBackend(newMode)
  }, [setModeState, syncModeToBackend])

  const toggleMode = useCallback(() => {
    setMode(mode === 'light' ? 'dark' : 'light')
  }, [mode, setMode])

  const setTokenOverride = useCallback((token: string, value: string) => {
    setOverrides(prev => {
      const next = { ...prev, [token]: value }
      syncOverridesToBackend(next)
      return next
    })
  }, [setOverrides, syncOverridesToBackend])

  const resetToken = useCallback((token: string) => {
    setOverrides(prev => {
      const next = { ...prev }
      delete next[token]
      syncOverridesToBackend(next)
      return next
    })
  }, [setOverrides, syncOverridesToBackend])

  const resetAllTokens = useCallback(() => {
    setOverrides({})
    syncOverridesToBackend({})
  }, [setOverrides, syncOverridesToBackend])

  const value: ThemeContextValue = {
    mode,
    toggleMode,
    setMode,
    overrides,
    setTokenOverride,
    resetToken,
    resetAllTokens,
    syncStatus,
  }

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// ========== Hook ==========

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
