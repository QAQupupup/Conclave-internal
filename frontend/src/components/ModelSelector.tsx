// LLM 模型选择器：厂商选择 + 模型分类列表 + API Key 输入 + 余额查询 + 定价显示
// 两种模式：
//   1. inline 模式（CreateMeeting 表单中）：通过 value/onChange 受控，不直接调 API
//   2. panel 模式（会议中浮窗）：传入 meetingId，直接调 setMeetingModel 切换
import { useState, useEffect, useCallback, useRef } from 'react'
import type { FC } from 'react'
import {
  listLLMProviders,
  listLLMModels,
  getLLMBalance,
  setMeetingModel as apiSetMeetingModel,
  getMeetingModel as apiGetMeetingModel,
  type LLMProvider,
  type LLMModel,
  type LLMModelsResponse,
  type LLMBalanceResponse,
  type MeetingModelConfig,
} from '../lib/api.ts'
import {
  getApiKey,
  setApiKey as saveApiKey,
  getDefaultSelection,
  loadPreferences,
  setDefaultSelection,
} from '../lib/llmPreferences.ts'

// ============================================================================
// 类型定义
// ============================================================================

/** 选中的模型配置（用于表单受控） */
export interface ModelSelection {
  provider_id: string
  model: string
  api_key: string
  base_url: string
}

/** 默认选择（硅基流动 + DeepSeek-V3.2） */
export const DEFAULT_SELECTION: ModelSelection = {
  provider_id: 'siliconflow',
  model: 'deepseek-ai/DeepSeek-V3.2',
  api_key: '',
  base_url: '',
}

// 分类标签中文映射
const CATEGORY_LABELS: Record<string, string> = {
  recommended: '推荐模型',
  free: '免费模型',
  reasoning: '推理模型',
  vision: '多模态/视觉',
  embedding: '向量/嵌入',
  chat: '对话模型',
}

// tier 中文标签和样式
const TIER_STYLES: Record<string, { label: string; cls: string }> = {
  free: { label: '免费', cls: 'tier-free' },
  cheap: { label: '便宜', cls: 'tier-cheap' },
  fast: { label: '快速', cls: 'tier-fast' },
  standard: { label: '标准', cls: 'tier-standard' },
  pro: { label: '专享', cls: 'tier-pro' },
  reasoning: { label: '推理', cls: 'tier-reasoning' },
}

// ============================================================================
// 工具函数
// ============================================================================

function formatPrice(p: number, currency: string): string {
  if (p === 0) return '免费'
  const sym = currency === 'CNY' ? '¥' : currency === 'USD' ? '$' : ''
  return `${sym}${p}/M`
}

function formatBalance(b: number | null, currency: string): string {
  if (b === null || b === undefined) return '—'
  const sym = currency === 'CNY' ? '¥' : currency === 'USD' ? '$' : ''
  return `${sym}${b.toFixed(2)}`
}

// ============================================================================
// 子组件：余额徽章
// ============================================================================

function BalanceBadge({
  balance,
  loading,
  error,
}: {
  balance: LLMBalanceResponse | null
  loading: boolean
  error: string | null
}) {
  if (loading) {
    return <span className="balance-badge loading">查询余额中…</span>
  }
  if (error) {
    return <span className="balance-badge error" title={error}>余额查询失败</span>
  }
  if (!balance || !balance.supported) {
    return <span className="balance-badge na">余额查询不可用</span>
  }
  const low = balance.balance !== null && balance.balance < 1
  return (
    <span className={`balance-badge${low ? ' low' : ''}`}>
      余额：{formatBalance(balance.balance, balance.currency)}
    </span>
  )
}

// ============================================================================
// 子组件：模型选项行
// ============================================================================

function ModelOption({
  model,
  selected,
  onClick,
}: {
  model: LLMModel
  selected: boolean
  onClick: () => void
}) {
  const p = model.pricing
  const tier = p?.tier || 'standard'
  const tierInfo = TIER_STYLES[tier] || TIER_STYLES.standard
  return (
    <button
      type="button"
      className={`model-option${selected ? ' selected' : ''}`}
      onClick={onClick}
    >
      <div className="model-option-main">
        <span className="model-option-id" title={model.id}>{model.id}</span>
        <span className={`model-tier ${tierInfo.cls}`}>{tierInfo.label}</span>
      </div>
      {p && (
        <div className="model-option-pricing">
          <span>入 {formatPrice(p.input, p.currency)}</span>
          <span>出 {formatPrice(p.output, p.currency)}</span>
        </div>
      )}
    </button>
  )
}

// ============================================================================
// 主组件
// ============================================================================

interface ModelSelectorProps {
  /** 受控值 */
  value?: ModelSelection
  /** 值变化回调 */
  onChange?: (sel: ModelSelection) => void
  /** 会议ID（panel模式下传入，支持直接切换） */
  meetingId?: string | null
  /** 是否显示标题和描述（表单模式用 false，panel模式用 true） */
  showHeader?: boolean
  /** 禁用状态 */
  disabled?: boolean
}

export const ModelSelector: FC<ModelSelectorProps> = ({
  value,
  onChange,
  meetingId = null,
  showHeader = false,
  disabled = false,
}) => {
  // 本地状态（受控/非受控兼容）
  // 初始值优先使用 value，否则从本地偏好读取默认值
  const [internalValue, setInternalValue] = useState<ModelSelection>(() => {
    if (value) return value
    const def = getDefaultSelection()
    return {
      provider_id: def.provider_id,
      model: def.model,
      api_key: getApiKey(def.provider_id) || '',
      base_url: def.base_url,
    }
  })
  const sel = value ?? internalValue
  const updateSel = useCallback((next: Partial<ModelSelection>) => {
    const merged = { ...sel, ...next }
    if (!value) setInternalValue(merged)
    onChange?.(merged)
  }, [sel, value, onChange])

  // 厂商列表
  const [providers, setProviders] = useState<LLMProvider[]>([])
  const [providersLoading, setProvidersLoading] = useState(true)

  // 模型列表
  const [modelsData, setModelsData] = useState<LLMModelsResponse | null>(null)
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const modelsCache = useRef<Map<string, LLMModelsResponse>>(new Map())

  // 余额
  const [balance, setBalance] = useState<LLMBalanceResponse | null>(null)
  const [balanceLoading, setBalanceLoading] = useState(false)
  const [balanceError, setBalanceError] = useState<string | null>(null)

  // 展开的分类
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set(['recommended', 'free']))

  // panel 模式下的当前配置和切换状态
  const [currentConfig, setCurrentConfig] = useState<MeetingModelConfig | null>(null)
  const [switchLoading, setSwitchLoading] = useState(false)
  const [switchMsg, setSwitchMsg] = useState<string | null>(null)

  // 初始化：加载厂商列表
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await listLLMProviders()
        if (!cancelled) setProviders(res.providers)
      } catch (e) {
        if (!cancelled) {
          // 静默失败：组件仍可使用，只是厂商列表不全
        }
      } finally {
        if (!cancelled) setProvidersLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  // panel 模式：加载当前会议模型配置
  useEffect(() => {
    if (!meetingId) return
    let cancelled = false
    void (async () => {
      try {
        const cfg = await apiGetMeetingModel(meetingId)
        if (!cancelled) {
          setCurrentConfig(cfg)
          // 同步到选择器
          updateSel({
            provider_id: cfg.provider_id,
            model: cfg.model,
            api_key: '', // 不回显 API Key
            base_url: cfg.base_url || '',
          })
        }
      } catch {
        // 静默
      }
    })()
    return () => { cancelled = true }
  }, [meetingId])

  // 当前选中的 provider 对象
  const currentProvider = providers.find(p => p.id === sel.provider_id) || null

  // 切换厂商时加载模型列表
  useEffect(() => {
    if (!sel.provider_id || providers.length === 0) return
    const cacheKey = `${sel.provider_id}:${sel.api_key}:${sel.base_url}`
    const cached = modelsCache.current.get(cacheKey)
    if (cached) {
      setModelsData(cached)
      setModelsError(null)
      return
    }
    let cancelled = false
    setModelsLoading(true)
    setModelsError(null)
    void (async () => {
      try {
        const data = await listLLMModels({
          provider: sel.provider_id,
          api_key: sel.api_key || undefined,
          base_url: sel.base_url || undefined,
        })
        if (!cancelled) {
          modelsCache.current.set(cacheKey, data)
          setModelsData(data)
        }
      } catch (e) {
        if (!cancelled) {
          setModelsError(e instanceof Error ? e.message : String(e))
        }
      } finally {
        if (!cancelled) setModelsLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [sel.provider_id, sel.api_key, sel.base_url, providers.length])

  // 查询余额（debounced）
  const balanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (balanceTimer.current) clearTimeout(balanceTimer.current)
    // 需要厂商支持余额查询，且有 API Key（或厂商有默认 key）
    if (!currentProvider?.supports_balance) {
      setBalance(null)
      setBalanceError(null)
      return
    }
    balanceTimer.current = setTimeout(() => {
      let cancelled = false
      setBalanceLoading(true)
      setBalanceError(null)
      void (async () => {
        try {
          const data = await getLLMBalance({
            provider: sel.provider_id,
            api_key: sel.api_key || undefined,
            base_url: sel.base_url || undefined,
          })
          if (!cancelled) setBalance(data)
        } catch (e) {
          if (!cancelled) {
            setBalanceError(e instanceof Error ? e.message : String(e))
          }
        } finally {
          if (!cancelled) setBalanceLoading(false)
        }
      })()
      return () => { cancelled = true }
    }, 500)
    return () => {
      if (balanceTimer.current) clearTimeout(balanceTimer.current)
    }
  }, [sel.provider_id, sel.api_key, sel.base_url, currentProvider?.supports_balance])

  // 选择厂商
  const handleProviderChange = (providerId: string) => {
    const provider = providers.find(p => p.id === providerId)
    // 切换厂商时重置 model/api_key/base_url，但自动填充已保存的该厂商 Key
    const savedKey = getApiKey(providerId)
    const next: Partial<ModelSelection> = {
      provider_id: providerId,
      model: '',
      api_key: savedKey,
      base_url: providerId === 'custom' ? loadPreferences().custom_base_url : (provider?.base_url || ''),
    }
    // 如果有推荐模型，默认选第一个
    if (modelsData?.recommended?.length) {
      next.model = modelsData.recommended[0].id
    }
    updateSel(next)
    setSwitchMsg(null)
  }

  // 刷新模型列表
  const handleRefreshModels = () => {
    const cacheKey = `${sel.provider_id}:${sel.api_key}:${sel.base_url}`
    modelsCache.current.delete(cacheKey)
    // 触发重新加载
    const pid = sel.provider_id
    updateSel({ provider_id: '' })
    setTimeout(() => updateSel({ provider_id: pid }), 0)
  }

  // 切换分类展开
  const toggleCat = (cat: string) => {
    setExpandedCats(prev => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  // panel 模式：应用模型切换
  const handleApply = async () => {
    if (!meetingId) return
    setSwitchLoading(true)
    setSwitchMsg(null)
    try {
      const cfg = await apiSetMeetingModel(meetingId, {
        provider_id: sel.provider_id,
        model: sel.model,
        api_key: sel.api_key || undefined,
        base_url: sel.base_url || undefined,
      })
      setCurrentConfig(cfg)
      // 如果用户输入了 API Key，自动保存到本地偏好
      if (sel.api_key) {
        saveApiKey(sel.provider_id, sel.api_key)
      }
      // 如果开启了自动保存，将当前模型设置为默认
      const prefs = loadPreferences()
      if (prefs.auto_save_model) {
        setDefaultSelection({
          provider_id: sel.provider_id,
          model: sel.model,
          base_url: sel.base_url,
        })
      }
      setSwitchMsg(`已切换到 ${cfg.model}`)
    } catch (e) {
      setSwitchMsg(`切换失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSwitchLoading(false)
    }
  }

  // 渲染分类区块
  const renderCategory = (catKey: string, models: LLMModel[]) => {
    if (!models || models.length === 0) return null
    const expanded = expandedCats.has(catKey)
    const label = CATEGORY_LABELS[catKey] || catKey
    return (
      <div className="model-cat">
        <button
          type="button"
          className="model-cat-header"
          onClick={() => toggleCat(catKey)}
        >
          <span className="model-cat-arrow">{expanded ? '▾' : '▸'}</span>
          <span className="model-cat-label">{label}</span>
          <span className="model-cat-count">{models.length}</span>
        </button>
        {expanded && (
          <div className="model-cat-body">
            {models.map(m => (
              <ModelOption
                key={m.id}
                model={m}
                selected={sel.model === m.id}
                onClick={() => {
                  updateSel({ model: m.id })
                  setSwitchMsg(null)
                }}
              />
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={`model-selector${disabled ? ' disabled' : ''}`}>
      {showHeader && (
        <div className="model-selector-header">
          <div className="model-selector-title">模型设置</div>
          {currentConfig && (
            <div className="model-current-info">
              当前：<code>{currentConfig.model}</code>
              {currentConfig.has_custom_key && <span className="custom-key-badge">自定义Key</span>}
            </div>
          )}
        </div>
      )}

      {/* 厂商选择 */}
      <div className="form-row">
        <span className="field-label">LLM 厂商</span>
        <select
          className="ms-provider-select"
          value={sel.provider_id}
          onChange={(e) => handleProviderChange(e.target.value)}
          disabled={disabled || providersLoading}
        >
          {providersLoading && <option value="">加载中…</option>}
          {providers.map(p => (
            <option key={p.id} value={p.id}>
              {p.name}{p.has_key ? '（已配置Key）' : ''}
            </option>
          ))}
        </select>
        {currentProvider?.pricing_note && (
          <span className="field-hint">{currentProvider.pricing_note}</span>
        )}
      </div>

      {/* 自定义 Base URL（仅 custom 厂商显示） */}
      {sel.provider_id === 'custom' && (
        <div className="form-row">
          <span className="field-label">API Base URL</span>
          <input
            type="text"
            className="ms-input"
            placeholder="https://api.example.com/v1"
            value={sel.base_url}
            onChange={(e) => updateSel({ base_url: e.target.value })}
            disabled={disabled}
          />
          <span className="field-hint">OpenAI 兼容接口地址</span>
        </div>
      )}

      {/* 自定义 API Key */}
      {currentProvider?.supports_custom_key && (
        <div className="form-row">
          <span className="field-label">API Key（可选）</span>
          <input
            type="password"
            className="ms-input"
            placeholder={currentProvider.has_key ? '留空使用系统默认Key' : '输入你的 API Key（sk-...）'}
            value={sel.api_key}
            onChange={(e) => updateSel({ api_key: e.target.value })}
            disabled={disabled}
            autoComplete="off"
          />
          <span className="field-hint">
            {currentProvider.has_key
              ? '填入你自己的Key可单独计费，不消耗系统额度'
              : '此厂商需要提供你自己的API Key'}
          </span>
        </div>
      )}

      {/* 余额显示 */}
      {currentProvider?.supports_balance && (
        <div className="ms-balance-row">
          <BalanceBadge balance={balance} loading={balanceLoading} error={balanceError} />
        </div>
      )}

      {/* 模型列表 */}
      <div className="form-row">
        <div className="ms-models-header">
          <span className="field-label">选择模型</span>
          <button
            type="button"
            className="btn btn-ghost btn-xs"
            onClick={handleRefreshModels}
            disabled={modelsLoading || disabled}
          >
            {modelsLoading ? '加载中…' : '刷新'}
          </button>
        </div>
        {modelsError && (
          <div className="ms-error">加载模型失败：{modelsError}</div>
        )}
        {modelsLoading && !modelsData && (
          <div className="ms-loading">加载模型列表…</div>
        )}
        {modelsData && (
          <div className="ms-models-list">
            {/* 已选中模型（不在任何分类里也显示） */}
            {sel.model && !modelsData.models.some(m => m.id === sel.model) && (
              <div className="model-option selected">
                <div className="model-option-main">
                  <span className="model-option-id">{sel.model}</span>
                </div>
              </div>
            )}
            {/* 按分类渲染 */}
            {modelsData.categories && Object.entries(modelsData.categories).map(([key, models]) =>
              renderCategory(key, models || [])
            )}
          </div>
        )}
      </div>

      {/* panel 模式：应用按钮 */}
      {meetingId && (
        <div className="ms-actions">
          {switchMsg && (
            <span className={`ms-msg${switchMsg.includes('失败') ? ' error' : ' success'}`}>
              {switchMsg}
            </span>
          )}
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleApply}
            disabled={switchLoading || !sel.model || disabled}
          >
            {switchLoading ? '切换中…' : '应用模型'}
          </button>
        </div>
      )}
    </div>
  )
}

/** 便捷 hook：获取/管理模型选择状态 */
export function useModelSelection(initial?: Partial<ModelSelection>) {
  const [sel, setSel] = useState<ModelSelection>({ ...DEFAULT_SELECTION, ...initial })
  return { selection: sel, setSelection: setSel }
}
