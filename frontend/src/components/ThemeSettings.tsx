/**
 * ThemeSettings：主题设置面板（亮暗切换 + Token 级覆盖）
 *
 * 形态：弹窗模态框，分三个区块
 * 1. 主题模式：亮/暗切换
 * 2. Token 覆盖：按 group 分组（色彩/语义色/形状/字体），每项可编辑 + 重置
 * 3. 同步状态 + 全部重置
 *
 * 风格：遵循《个人签单风格与逻辑规范 v1.0》——纯白底、靛蓝主色、S3 色块标签、1px 边框
 */
import { useState } from 'react'
import { OVERRIDABLE_TOKENS, useTheme } from '../store/ThemeContext'

interface Props {
  onClose: () => void
}

export function ThemeSettings({ onClose }: Props) {
  const { mode, setMode, overrides, setTokenOverride, resetToken, resetAllTokens, syncStatus } = useTheme()
  const [expandedGroup, setExpandedGroup] = useState<string>('色彩')

  // 按 group 分组
  type Entry = [string, { label: string; type: string; group: string }]
  const grouped: Record<string, Entry[]> = {}
  for (const [token, meta] of Object.entries(OVERRIDABLE_TOKENS)) {
    if (!grouped[meta.group]) grouped[meta.group] = []
    grouped[meta.group].push([token, meta])
  }

  const syncLabel = {
    idle: '未同步',
    syncing: '同步中…',
    synced: '已同步',
    error: '同步失败',
  }[syncStatus]

  return (
    <div className="theme-settings-overlay" onClick={onClose}>
      <div className="theme-settings-modal" onClick={e => e.stopPropagation()}>
        {/* 头部 */}
        <div className="ts-header">
          <div className="ts-title-row">
            <h2 className="ts-title">主题设置</h2>
            <span className={`ts-sync ts-sync-${syncStatus}`}>{syncLabel}</span>
          </div>
          <p className="ts-subtitle">默认规则基于《个人签单风格与逻辑规范 v1.0》，此处可覆盖</p>
        </div>

        {/* 主题模式 */}
        <div className="ts-section">
          <div className="ts-section-label">主题模式</div>
          <div className="ts-mode-toggle">
            <button
              className={`ts-mode-btn ${mode === 'light' ? 'active' : ''}`}
              onClick={() => setMode('light')}
            >
              亮色
            </button>
            <button
              className={`ts-mode-btn ${mode === 'dark' ? 'active' : ''}`}
              onClick={() => setMode('dark')}
            >
              暗色
            </button>
          </div>
        </div>

        {/* Token 覆盖 */}
        <div className="ts-section">
          <div className="ts-section-label">Token 覆盖</div>
          {Object.entries(grouped).map(([group, tokens]) => (
            <div key={group} className="ts-group">
              <button
                className={`ts-group-header ${expandedGroup === group ? 'expanded' : ''}`}
                onClick={() => setExpandedGroup(expandedGroup === group ? '' : group)}
              >
                <span>{group}</span>
                <span className="ts-group-count">{tokens.length}</span>
              </button>
              {expandedGroup === group && (
                <div className="ts-token-list">
                  {tokens.map(([token, meta]) => (
                    <div key={token} className="ts-token-row">
                      <div className="ts-token-label">
                        <span className="ts-token-name">{meta.label}</span>
                        <code className="ts-token-key">--{token}</code>
                      </div>
                      <div className="ts-token-control">
                        {meta.type === 'color' && (
                          <input
                            type="color"
                            className="ts-color-picker"
                            value={overrides[token] || getComputedStyle(document.documentElement).getPropertyValue(`--${token}`).trim() || '#000000'}
                            onChange={e => setTokenOverride(token, e.target.value)}
                          />
                        )}
                        {meta.type === 'size' && (
                          <input
                            type="text"
                            className="ts-text-input"
                            placeholder="如 6px"
                            value={overrides[token] || ''}
                            onChange={e => setTokenOverride(token, e.target.value)}
                          />
                        )}
                        {meta.type === 'font' && (
                          <input
                            type="text"
                            className="ts-text-input ts-font-input"
                            placeholder="字体栈"
                            value={overrides[token] || ''}
                            onChange={e => setTokenOverride(token, e.target.value)}
                          />
                        )}
                        {overrides[token] && (
                          <button
                            className="ts-reset-btn"
                            onClick={() => resetToken(token)}
                            title="重置为默认"
                          >
                            重置
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* 底部操作 */}
        <div className="ts-footer">
          <button className="ts-reset-all" onClick={resetAllTokens}>
            重置全部 Token
          </button>
          <button className="ts-close-btn" onClick={onClose}>
            完成
          </button>
        </div>
      </div>
    </div>
  )
}
