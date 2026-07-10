// 设置面板：管理 LLM 默认模型、API Key 等本地偏好
// 类似 ThemeSettings 的弹窗模态，从工具栏⚙️按钮打开
import { useState, useEffect, useCallback } from 'react'
import type { FC } from 'react'
import { ModelSelector, type ModelSelection } from './ModelSelector.tsx'
import {
  loadPreferences,
  savePreferences,
  resetPreferences,
  exportPreferences,
  onPreferencesChanged,
  type LLMPreferences,
} from '../lib/llmPreferences.ts'

interface Props {
  onClose: () => void
}

export const SettingsPanel: FC<Props> = ({ onClose }) => {
  const [prefs, setPrefs] = useState<LLMPreferences>(() => loadPreferences())
  const [sel, setSel] = useState<ModelSelection>(() => {
    const p = loadPreferences()
    return {
      provider_id: p.default_provider_id,
      model: p.default_model,
      api_key: p.api_keys[p.default_provider_id] || '',
      base_url: p.default_provider_id === 'custom' ? p.custom_base_url : '',
    }
  })
  const [savedMsg, setSavedMsg] = useState<string | null>(null)
  const [showResetConfirm, setShowResetConfirm] = useState(false)

  // 监听外部偏好变化（如其他组件修改了偏好）
  useEffect(() => {
    return onPreferencesChanged(() => {
      setPrefs(loadPreferences())
    })
  }, [])

  // 保存默认模型设置
  const handleSaveDefault = useCallback(() => {
    const newPrefs: LLMPreferences = {
      ...prefs,
      default_provider_id: sel.provider_id,
      default_model: sel.model,
      custom_base_url: sel.provider_id === 'custom' ? sel.base_url : prefs.custom_base_url,
    }
    // 保存 API Key（如果输入了）
    if (sel.api_key) {
      newPrefs.api_keys = { ...prefs.api_keys, [sel.provider_id]: sel.api_key }
    }
    savePreferences(newPrefs)
    setPrefs(newPrefs)
    setSavedMsg('已保存默认设置')
    setTimeout(() => setSavedMsg(null), 2000)
  }, [prefs, sel])

  // 删除某个厂商的 Key
  const handleRemoveKey = (providerId: string) => {
    const newPrefs = { ...prefs, api_keys: { ...prefs.api_keys } }
    delete newPrefs.api_keys[providerId]
    savePreferences(newPrefs)
    setPrefs(newPrefs)
    if (sel.provider_id === providerId) {
      setSel(s => ({ ...s, api_key: '' }))
    }
  }

  // 自动保存开关
  const handleToggleAutoSave = () => {
    const newPrefs = { ...prefs, auto_save_model: !prefs.auto_save_model }
    savePreferences(newPrefs)
    setPrefs(newPrefs)
  }

  // 重置所有偏好
  const handleReset = () => {
    resetPreferences()
    const fresh = loadPreferences()
    setPrefs(fresh)
    setSel({
      provider_id: fresh.default_provider_id,
      model: fresh.default_model,
      api_key: '',
      base_url: '',
    })
    setShowResetConfirm(false)
    setSavedMsg('已重置为默认设置')
    setTimeout(() => setSavedMsg(null), 2000)
  }

  // 已保存 Key 的厂商列表
  const savedKeyProviders = Object.entries(prefs.api_keys).filter(([, v]) => v)

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={e => e.stopPropagation()}>
        {/* 头部 */}
        <div className="ts-header">
          <div className="ts-title-row">
            <h2 className="ts-title">设置</h2>
          </div>
          <p className="ts-subtitle">LLM 模型和 API Key 偏好保存在浏览器本地，不会上传到服务器</p>
        </div>

        <div className="ts-body">
          {/* 默认模型选择 */}
          <div className="ts-section">
            <div className="ts-section-label">默认模型</div>
            <p className="ts-section-desc">新创建的会议将默认使用此模型。会议中可随时切换。</p>
            <div className="settings-model-box">
              <ModelSelector
                value={sel}
                onChange={setSel}
                showHeader={false}
              />
            </div>
            <div className="settings-save-row">
              {savedMsg && <span className="settings-saved-msg">{savedMsg}</span>}
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleSaveDefault}
                disabled={!sel.model}
              >
                保存为默认
              </button>
            </div>
          </div>

          {/* 自动保存开关 */}
          <div className="ts-section">
            <div className="ts-section-label">会议中切换</div>
            <label className="settings-toggle-row">
              <input
                type="checkbox"
                checked={prefs.auto_save_model}
                onChange={handleToggleAutoSave}
              />
              <span>会议中切换模型时自动保存为默认</span>
            </label>
          </div>

          {/* 已保存的 API Keys */}
          <div className="ts-section">
            <div className="ts-section-label">已保存的 API Key</div>
            {savedKeyProviders.length === 0 ? (
              <p className="ts-section-desc">暂无保存的 Key。在上方选择厂商并输入 Key 后点"保存为默认"即可保存。</p>
            ) : (
              <div className="settings-keys-list">
                {savedKeyProviders.map(([pid, key]) => (
                  <div key={pid} className="settings-key-row">
                    <span className="settings-key-provider">{pid}</span>
                    <span className="settings-key-mask">{key.slice(0, 6)}...{key.slice(-4)}</span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      onClick={() => handleRemoveKey(pid)}
                    >
                      删除
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 偏好导出 */}
          <div className="ts-section">
            <div className="ts-section-label">数据管理</div>
            <p className="ts-section-desc">
              设置存储在浏览器 localStorage 中，清除浏览器数据会丢失。
              当前配置：{exportPreferences().length > 10 ? '已配置默认模型' : '未配置'}
              {savedKeyProviders.length > 0 && `，${savedKeyProviders.length} 个 Key`}
            </p>
          </div>
        </div>

        {/* 底部 */}
        <div className="ts-footer">
          {showResetConfirm ? (
            <>
              <span className="settings-confirm-text">确定重置所有设置？</span>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowResetConfirm(false)}>
                取消
              </button>
              <button className="btn btn-danger btn-sm" onClick={handleReset}>
                确认重置
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowResetConfirm(true)}>
                重置全部
              </button>
              <button className="btn btn-primary btn-sm" onClick={onClose}>
                完成
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
