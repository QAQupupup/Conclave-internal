/**
 * Ant Design 主题桥接配置
 *
 * 将 personal-style-guide 中的设计 token 映射到 Ant Design 的 Design Token 体系。
 * 亮/暗双主题，与 ThemeContext 联动。
 *
 * 设计来源：personal-style-guide.html
 *   --accent: #4f46e5  → colorPrimary
 *   --bg:     #ffffff  → colorBgContainer
 *   --rule:   #e5e7eb  → colorBorder
 *   语义色 S3 低饱和糖果色块
 */
import { theme } from 'antd'
import type { ThemeConfig } from 'antd'

const { defaultAlgorithm, darkAlgorithm } = theme

// ===== 亮色 token =====
const lightTokens: ThemeConfig['token'] = {
  // 色彩
  colorPrimary: '#4f46e5',
  colorPrimaryHover: '#4338ca',
  colorPrimaryActive: '#3730a3',
  colorBgContainer: '#ffffff',
  colorBgLayout: '#fafafa',
  colorBgElevated: '#ffffff',
  colorBorder: '#e5e7eb',
  colorBorderSecondary: '#f3f4f6',
  colorText: '#111827',
  colorTextSecondary: '#6b7280',
  colorTextTertiary: '#9ca3af',
  colorTextQuaternary: '#c2c9d1',

  // 语义色
  colorSuccess: '#059669',
  colorWarning: '#d97706',
  colorError: '#dc2626',
  colorInfo: '#4f46e5',

  // 语义色背景（S3 色块）
  colorSuccessBg: '#ecfdf5',
  colorWarningBg: '#fffbeb',
  colorErrorBg: '#fef2f2',

  // 形状
  borderRadius: 6,
  borderRadiusSM: 4,
  borderRadiusLG: 8,

  // 字体
  fontFamily:
    '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  fontFamilyCode:
    '"JetBrains Mono", "SF Mono", "Cascadia Code", Consolas, monospace',
  fontSize: 14,
  fontSizeSM: 12,
  fontSizeLG: 16,

  // 间距 & 尺寸
  controlHeight: 36,
  padding: 16,
  paddingSM: 12,
  paddingLG: 24,
  paddingXS: 8,

  // 动效：克制、快速
  motion: true,
  motionDurationMid: '150ms',
  motionDurationSlow: '200ms',
  motionEaseInOut: 'cubic-bezier(0.16, 1, 0.3, 1)',

  // 线框模式（细线条风格）
  wireframe: false,

  // 阴影：极轻
  boxShadow: '0 1px 2px rgba(17, 24, 39, 0.04)',
  boxShadowSecondary: '0 1px 3px rgba(17, 24, 39, 0.06)',
}

// ===== 暗色 token =====
const darkTokens: ThemeConfig['token'] = {
  colorPrimary: '#818cf8',
  colorPrimaryHover: '#a5b4fc',
  colorPrimaryActive: '#c7d2fe',
  colorBgContainer: '#161b22',
  colorBgLayout: '#0d1117',
  colorBgElevated: '#161b22',
  colorBorder: '#30363d',
  colorBorderSecondary: '#21262d',
  colorText: '#e6edf3',
  colorTextSecondary: '#9da7b3',
  colorTextTertiary: '#768390',
  colorTextQuaternary: '#4a5158',

  colorSuccess: '#34d399',
  colorWarning: '#fbbf24',
  colorError: '#f87171',
  colorInfo: '#818cf8',

  colorSuccessBg: 'rgba(52, 211, 153, 0.10)',
  colorWarningBg: 'rgba(251, 191, 36, 0.10)',
  colorErrorBg: 'rgba(248, 113, 113, 0.10)',

  boxShadow: '0 1px 2px rgba(0, 0, 0, 0.3)',
  boxShadowSecondary: '0 1px 3px rgba(0, 0, 0, 0.4)',
}

// ===== 组件级覆盖 =====
const componentOverrides: ThemeConfig['components'] = {
  Button: {
    borderRadius: 6,
    controlHeight: 36,
    fontWeight: 500,
  },
  Card: {
    borderRadiusLG: 8,
    paddingLG: 20,
    // 无阴影卡片，用边框区分
    boxShadowTertiary: 'none',
  },
  Table: {
    borderRadius: 8,
    headerBg: '#fafafa',
    headerColor: '#6b7280',
    borderColor: '#f3f4f6',
    fontSize: 13,
  },
  Tag: {
    borderRadiusSM: 4,
    defaultBg: 'transparent',
  },
  Input: {
    borderRadius: 6,
    controlHeight: 36,
  },
  Select: {
    borderRadius: 6,
    controlHeight: 36,
  },
  Modal: {
    borderRadiusLG: 12,
    titleFontSize: 16,
  },
  Drawer: {
    paddingLG: 24,
  },
  Menu: {
    itemBorderRadius: 6,
    itemMarginBlock: 2,
    itemMarginInline: 4,
  },
  Layout: {
    headerBg: 'transparent',
    siderBg: 'transparent',
    bodyBg: 'transparent',
  },
  Tabs: {
    itemColor: '#6b7280',
    itemSelectedColor: '#4f46e5',
    inkBarColor: '#4f46e5',
  },
}

// ===== 暗色组件覆盖 =====
const darkComponentOverrides: ThemeConfig['components'] = {
  Table: {
    headerBg: '#1c2128',
    headerColor: '#9da7b3',
    borderColor: '#21262d',
  },
}

/**
 * 根据当前主题模式生成 Ant Design ThemeConfig
 */
export function getAntdTheme(mode: 'light' | 'dark'): ThemeConfig {
  const isDark = mode === 'dark'
  return {
    algorithm: isDark ? darkAlgorithm : defaultAlgorithm,
    token: isDark ? darkTokens : lightTokens,
    components: isDark
      ? { ...componentOverrides, ...darkComponentOverrides }
      : componentOverrides,
  }
}

/**
 * 从 AntD token 同步到 CSS 自定义属性（可选，供非 AntD 组件使用）
 * 在 App 组件中调用，保持 CSS 变量与 AntD token 一致
 */
export function syncCssVarsToAntd(mode: 'light' | 'dark'): Record<string, string> {
  const isDark = mode === 'dark'
  return {
    '--accent': isDark ? '#818cf8' : '#4f46e5',
    '--accent-hover': isDark ? '#a5b4fc' : '#4338ca',
  }
}
