// LLM 本地偏好存储：基于 localStorage，无需后端/登录
// 存储用户默认模型选择、各厂商 API Key、默认厂商等
// 所有 Key 仅存在用户浏览器中，不会上传到服务器（会议级 Key 仅在该次 API 调用时使用）

import type { ModelSelection } from '../components/ModelSelector.tsx'

const STORAGE_KEY = 'conclave.llm_preferences'
const STORAGE_VERSION = 1

/** 本地偏好数据结构（内存中所有 Key 为明文） */
export interface LLMPreferences {
  version: number
  /** 默认厂商ID */
  default_provider_id: string
  /** 默认模型ID */
  default_model: string
  /** 各厂商保存的 API Key（provider_id -> 明文key，仅内存中明文，存储时混淆） */
  api_keys: Record<string, string>
  /** 自定义厂商的 Base URL */
  custom_base_url: string
  /** 是否在会议中切换模型时自动保存为默认 */
  auto_save_model: boolean
}

const DEFAULT_PREFERENCES: LLMPreferences = {
  version: STORAGE_VERSION,
  default_provider_id: 'siliconflow',
  default_model: 'deepseek-ai/DeepSeek-V3.2',
  api_keys: {},
  custom_base_url: '',
  auto_save_model: false,
}

/** 简单的 XOR 混淆（不是真正加密，仅防止 Key 在 localStorage 中明文可见）
 *  注意：这不是安全加密，只是避免开发者工具中一眼看到明文。
 *  真正安全需要后端加密，但这是纯前端方案，Key 本身是用户自己的。
 */
function obfuscate(key: string): string {
  if (!key) return ''
  const mask = 'conclave-llm-key-mask-v1'
  let result = ''
  for (let i = 0; i < key.length; i++) {
    result += String.fromCharCode(key.charCodeAt(i) ^ mask.charCodeAt(i % mask.length))
  }
  return btoa(unescape(encodeURIComponent(result)))
}

function deobfuscate(encoded: string): string {
  if (!encoded) return ''
  try {
    const mask = 'conclave-llm-key-mask-v1'
    const decoded = decodeURIComponent(escape(atob(encoded)))
    let result = ''
    for (let i = 0; i < decoded.length; i++) {
      result += String.fromCharCode(decoded.charCodeAt(i) ^ mask.charCodeAt(i % mask.length))
    }
    return result
  } catch {
    return ''
  }
}

/** 内存缓存（避免每次都读 localStorage + 反混淆） */
let _cache: LLMPreferences | null = null

/** 加载偏好（从 localStorage，返回明文 Key） */
export function loadPreferences(): LLMPreferences {
  if (_cache) return { ..._cache, api_keys: { ..._cache.api_keys } }
  if (typeof localStorage === 'undefined') return { ...DEFAULT_PREFERENCES, api_keys: {} }
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      _cache = { ...DEFAULT_PREFERENCES, api_keys: {} }
      return { ..._cache }
    }
    const parsed = JSON.parse(raw)
    // 反混淆 API Keys（存储时混淆，加载时还原）
    const plainKeys: Record<string, string> = {}
    if (parsed.api_keys && typeof parsed.api_keys === 'object') {
      for (const [k, v] of Object.entries(parsed.api_keys)) {
        if (typeof v === 'string') plainKeys[k] = deobfuscate(v)
      }
    }
    const merged: LLMPreferences = {
      ...DEFAULT_PREFERENCES,
      ...parsed,
      api_keys: plainKeys,
      version: STORAGE_VERSION,
      custom_base_url: typeof parsed.custom_base_url === 'string' ? parsed.custom_base_url : DEFAULT_PREFERENCES.custom_base_url,
      auto_save_model: typeof parsed.auto_save_model === 'boolean' ? parsed.auto_save_model : DEFAULT_PREFERENCES.auto_save_model,
      default_provider_id: typeof parsed.default_provider_id === 'string' ? parsed.default_provider_id : DEFAULT_PREFERENCES.default_provider_id,
      default_model: typeof parsed.default_model === 'string' ? parsed.default_model : DEFAULT_PREFERENCES.default_model,
    }
    _cache = merged
    return { ..._cache }
  } catch {
    _cache = { ...DEFAULT_PREFERENCES, api_keys: {} }
    return { ..._cache }
  }
}

/** 保存偏好（到 localStorage，Key 会被混淆存储） */
export function savePreferences(prefs: LLMPreferences): void {
  if (typeof localStorage === 'undefined') return
  _cache = { ...prefs, api_keys: { ...prefs.api_keys } }
  // 混淆 API Keys 后存储
  const obfuscatedKeys: Record<string, string> = {}
  for (const [k, v] of Object.entries(prefs.api_keys)) {
    obfuscatedKeys[k] = obfuscate(v)
  }
  const toStore = { ...prefs, api_keys: obfuscatedKeys }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(toStore))
  // 触发存储事件（同页面其他组件可监听）
  window.dispatchEvent(new CustomEvent('llm-prefs-changed'))
}

/** 获取某个厂商保存的 API Key（明文） */
export function getApiKey(providerId: string): string {
  const prefs = loadPreferences()
  return prefs.api_keys[providerId] || ''
}

/** 保存某个厂商的 API Key */
export function setApiKey(providerId: string, key: string): void {
  const prefs = loadPreferences()
  if (key) {
    prefs.api_keys[providerId] = key
  } else {
    delete prefs.api_keys[providerId]
  }
  savePreferences(prefs)
}

/** 获取默认模型选择（用于创建会议时预填） */
export function getDefaultSelection(): ModelSelection {
  const prefs = loadPreferences()
  return {
    provider_id: prefs.default_provider_id,
    model: prefs.default_model,
    api_key: prefs.api_keys[prefs.default_provider_id] || '',
    base_url: prefs.default_provider_id === 'custom' ? prefs.custom_base_url : '',
  }
}

/** 设置默认模型选择 */
export function setDefaultSelection(sel: Partial<ModelSelection>): void {
  const prefs = loadPreferences()
  if (sel.provider_id) prefs.default_provider_id = sel.provider_id
  if (sel.model) prefs.default_model = sel.model
  if (sel.provider_id === 'custom' && sel.base_url !== undefined) {
    prefs.custom_base_url = sel.base_url
  }
  // 如果传入了 api_key，保存到对应厂商
  if (sel.api_key !== undefined && sel.provider_id) {
    if (sel.api_key) {
      prefs.api_keys[sel.provider_id] = sel.api_key
    }
  }
  savePreferences(prefs)
}

/** 清除所有偏好（重置） */
export function resetPreferences(): void {
  if (typeof localStorage === 'undefined') return
  localStorage.removeItem(STORAGE_KEY)
  _cache = null
}

/** 导出偏好为 JSON（用于备份，不含 Key 明文） */
export function exportPreferences(): string {
  const prefs = loadPreferences()
  return JSON.stringify(
    {
      default_provider_id: prefs.default_provider_id,
      default_model: prefs.default_model,
      custom_base_url: prefs.custom_base_url,
      auto_save_model: prefs.auto_save_model,
      saved_key_providers: Object.keys(prefs.api_keys).filter(k => prefs.api_keys[k]),
    },
    null,
    2,
  )
}

/** 监听偏好变化 */
export function onPreferencesChanged(callback: () => void): () => void {
  const handler = () => callback()
  window.addEventListener('llm-prefs-changed', handler)
  window.addEventListener('storage', (e) => {
    if (e.key === STORAGE_KEY) {
      _cache = null // 清除缓存，下次读取时重新加载
      callback()
    }
  })
  return () => {
    window.removeEventListener('llm-prefs-changed', handler)
  }
}
