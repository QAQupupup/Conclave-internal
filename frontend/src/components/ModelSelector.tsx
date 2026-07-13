// LLM 模型选择器：厂商选择 + 模型分类列表 + API Key 输入 + 余额查询 + 定价显示
// 使用 AntD Select + Input + Card + Collapse + Tag + Button + Typography + Alert + Space
import { useState, useEffect, useCallback, useRef } from 'react'
import type { FC } from 'react'
import { Select, Input, Card, Collapse, Tag, Button, Typography, Alert, Space, Spin } from 'antd'
import { ReloadOutlined, CheckOutlined } from '@ant-design/icons'
import {
  listLLMProviders,
  listLLMModels,
  getLLMBalance,
  setMeetingModel as apiSetMeetingModel,
  getMeetingModel as apiGetMeetingModel,
  type LLMProvider,
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

const { Text } = Typography

// ============================================================================
// 类型定义
// ============================================================================

export interface ModelSelection {
  provider_id: string
  model: string
  api_key: string
  base_url: string
}

export const DEFAULT_SELECTION: ModelSelection = {
  provider_id: 'siliconflow',
  model: 'Qwen/Qwen3-8B',
  api_key: '',
  base_url: '',
}

const CATEGORY_LABELS: Record<string, string> = {
  recommended: '推荐模型',
  free: '免费模型',
  reasoning: '推理模型',
  vision: '多模态/视觉',
  embedding: '向量/嵌入',
  chat: '对话模型',
}

const TIER_COLORS: Record<string, string> = {
  free: 'green',
  cheap: 'cyan',
  fast: 'blue',
  standard: 'default',
  pro: 'purple',
  reasoning: 'orange',
}

const TIER_LABELS: Record<string, string> = {
  free: '免费',
  cheap: '便宜',
  fast: '快速',
  standard: '标准',
  pro: '专享',
  reasoning: '推理',
}

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
// 主组件
// ============================================================================

interface ModelSelectorProps {
  value?: ModelSelection
  onChange?: (sel: ModelSelection) => void
  meetingId?: string | null
  showHeader?: boolean
  disabled?: boolean
}

export const ModelSelector: FC<ModelSelectorProps> = ({
  value,
  onChange,
  meetingId = null,
  showHeader = false,
  disabled = false,
}) => {
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

  const [providers, setProviders] = useState<LLMProvider[]>([])
  const [providersLoading, setProvidersLoading] = useState(true)

  const [modelsData, setModelsData] = useState<LLMModelsResponse | null>(null)
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const modelsCache = useRef<Map<string, LLMModelsResponse>>(new Map())

  const [balance, setBalance] = useState<LLMBalanceResponse | null>(null)
  const [balanceLoading, setBalanceLoading] = useState(false)
  const [balanceError, setBalanceError] = useState<string | null>(null)

  const [expandedCats, setExpandedCats] = useState<string[]>(['recommended', 'free'])

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
      } catch { /* silent */ }
      finally { if (!cancelled) setProvidersLoading(false) }
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
          updateSel({
            provider_id: cfg.provider_id,
            model: cfg.model,
            api_key: '',
            base_url: cfg.base_url || '',
          })
        }
      } catch { /* silent */ }
    })()
    return () => { cancelled = true }
  }, [meetingId])

  const currentProvider = providers.find(p => p.id === sel.provider_id) || null

  // 切换厂商时加载模型列表
  useEffect(() => {
    if (!sel.provider_id || providers.length === 0) return
    const cacheKey = `${sel.provider_id}:${sel.api_key}:${sel.base_url}`
    const cached = modelsCache.current.get(cacheKey)
    if (cached) { setModelsData(cached); setModelsError(null); return }
    let cancelled = false
    setModelsLoading(true); setModelsError(null)
    void (async () => {
      try {
        const data = await listLLMModels({
          provider: sel.provider_id,
          api_key: sel.api_key || undefined,
          base_url: sel.base_url || undefined,
        })
        if (!cancelled) { modelsCache.current.set(cacheKey, data); setModelsData(data) }
      } catch (e) { if (!cancelled) setModelsError(e instanceof Error ? e.message : String(e)) }
      finally { if (!cancelled) setModelsLoading(false) }
    })()
    return () => { cancelled = true }
  }, [sel.provider_id, sel.api_key, sel.base_url, providers.length])

  // 查询余额
  const balanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (balanceTimer.current) clearTimeout(balanceTimer.current)
    if (!currentProvider?.supports_balance) { setBalance(null); setBalanceError(null); return }
    balanceTimer.current = setTimeout(() => {
      let cancelled = false
      setBalanceLoading(true); setBalanceError(null)
      void (async () => {
        try {
          const data = await getLLMBalance({
            provider: sel.provider_id,
            api_key: sel.api_key || undefined,
            base_url: sel.base_url || undefined,
          })
          if (!cancelled) setBalance(data)
        } catch (e) { if (!cancelled) setBalanceError(e instanceof Error ? e.message : String(e)) }
        finally { if (!cancelled) setBalanceLoading(false) }
      })()
      return () => { cancelled = true }
    }, 500)
    return () => { if (balanceTimer.current) clearTimeout(balanceTimer.current) }
  }, [sel.provider_id, sel.api_key, sel.base_url, currentProvider?.supports_balance])

  const handleProviderChange = (providerId: string) => {
    const provider = providers.find(p => p.id === providerId)
    const savedKey = getApiKey(providerId)
    const next: Partial<ModelSelection> = {
      provider_id: providerId,
      model: '',
      api_key: savedKey,
      base_url: providerId === 'custom' ? loadPreferences().custom_base_url : (provider?.base_url || ''),
    }
    if (modelsData?.recommended?.length) next.model = modelsData.recommended[0].id
    updateSel(next)
    setSwitchMsg(null)
  }

  const handleRefreshModels = () => {
    const cacheKey = `${sel.provider_id}:${sel.api_key}:${sel.base_url}`
    modelsCache.current.delete(cacheKey)
    const pid = sel.provider_id
    updateSel({ provider_id: '' })
    setTimeout(() => updateSel({ provider_id: pid }), 0)
  }

  const handleApply = async () => {
    if (!meetingId) return
    setSwitchLoading(true); setSwitchMsg(null)
    try {
      const cfg = await apiSetMeetingModel(meetingId, {
        provider_id: sel.provider_id, model: sel.model,
        api_key: sel.api_key || undefined, base_url: sel.base_url || undefined,
      })
      setCurrentConfig(cfg)
      if (sel.api_key) saveApiKey(sel.provider_id, sel.api_key)
      const prefs = loadPreferences()
      if (prefs.auto_save_model) setDefaultSelection({ provider_id: sel.provider_id, model: sel.model, base_url: sel.base_url })
      setSwitchMsg(`已切换到 ${cfg.model}`)
    } catch (e) { setSwitchMsg(`切换失败：${e instanceof Error ? e.message : String(e)}`) }
    finally { setSwitchLoading(false) }
  }

  const providerOptions = providers.map(p => ({
    value: p.id,
    label: `${p.name}${p.has_key ? '（已配置Key）' : ''}`,
  }))

  // 渲染分类
  const collapseItems = modelsData?.categories
    ? Object.entries(modelsData.categories).map(([key, models]) => {
        if (!models || models.length === 0) return null
        return {
          key,
          label: (
            <Space>
              <Text>{CATEGORY_LABELS[key] || key}</Text>
              <Tag>{models.length}</Tag>
            </Space>
          ),
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {models.map(m => {
                const tier = m.pricing?.tier || 'standard'
                return (
                  <Card
                    key={m.id}
                    size="small"
                    hoverable
                    style={{
                      cursor: 'pointer',
                      borderColor: sel.model === m.id ? 'var(--accent-color, #4f46e5)' : undefined,
                      background: sel.model === m.id ? 'var(--accent-bg, #eef2ff)' : undefined,
                    }}
                    onClick={() => { updateSel({ model: m.id }); setSwitchMsg(null) }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Space>
                        {sel.model === m.id && <CheckOutlined style={{ color: 'var(--accent-color, #4f46e5)' }} />}
                        <Text strong style={{ fontSize: 13 }}>{m.id}</Text>
                        <Tag color={TIER_COLORS[tier] ?? 'default'}>{TIER_LABELS[tier] ?? tier}</Tag>
                      </Space>
                      {m.pricing && (
                        <Space size={12}>
                          <Text type="secondary" style={{ fontSize: 11 }}>入 {formatPrice(m.pricing.input, m.pricing.currency)}</Text>
                          <Text type="secondary" style={{ fontSize: 11 }}>出 {formatPrice(m.pricing.output, m.pricing.currency)}</Text>
                        </Space>
                      )}
                    </div>
                  </Card>
                )
              })}
            </div>
          ),
        }
      }).filter(Boolean) as any[]
    : []

  return (
    <div className={`model-selector${disabled ? ' disabled' : ''}`}>
      {showHeader && (
        <div style={{ marginBottom: 16 }}>
          <Text strong>模型设置</Text>
          {currentConfig && (
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                当前：<code>{currentConfig.model}</code>
                {currentConfig.has_custom_key && <Tag color="purple" style={{ marginInlineStart: 4 }}>自定义Key</Tag>}
              </Text>
            </div>
          )}
        </div>
      )}

      {/* 厂商选择 */}
      <div style={{ marginBottom: 12 }}>
        <Text strong style={{ display: 'block', marginBottom: 4 }}>LLM 厂商</Text>
        <Select
          value={sel.provider_id || undefined}
          onChange={handleProviderChange}
          options={providerOptions}
          loading={providersLoading}
          disabled={disabled || providersLoading}
          style={{ width: '100%' }}
          placeholder="选择厂商"
        />
        {currentProvider?.pricing_note && (
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
            {currentProvider.pricing_note}
          </Text>
        )}
      </div>

      {/* 自定义 Base URL */}
      {sel.provider_id === 'custom' && (
        <div style={{ marginBottom: 12 }}>
          <Text strong style={{ display: 'block', marginBottom: 4 }}>API Base URL</Text>
          <Input
            placeholder="https://api.example.com/v1"
            value={sel.base_url}
            onChange={(e) => updateSel({ base_url: e.target.value })}
            disabled={disabled}
          />
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>OpenAI 兼容接口地址</Text>
        </div>
      )}

      {/* 自定义 API Key：始终展示输入框，方便用户配置；仅当后端声明 supports_custom_key=false 时禁用输入 */}
      {sel.provider_id && (
        <div style={{ marginBottom: 12 }}>
          <Text strong style={{ display: 'block', marginBottom: 4 }}>
            API Key（可选）
            {currentProvider && !currentProvider.supports_custom_key && (
              <Tag color="orange" style={{ marginInlineStart: 8, fontSize: 11 }}>该厂商不建议自定义</Tag>
            )}
          </Text>
          <Input.Password
            placeholder={currentProvider?.has_key ? '留空使用系统默认Key' : '输入你的 API Key（sk-...）'}
            value={sel.api_key}
            onChange={(e) => updateSel({ api_key: e.target.value })}
            disabled={disabled || (!!currentProvider && !currentProvider.supports_custom_key)}
            autoComplete="off"
          />
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
            {currentProvider?.has_key
              ? '填入你自己的Key可单独计费，不消耗系统额度'
              : '此厂商需要提供你自己的API Key；留空则尝试使用系统默认Key'}
          </Text>
        </div>
      )}

      {/* 余额显示 */}
      {currentProvider?.supports_balance && (
        <div style={{ marginBottom: 12 }}>
          {balanceLoading && <Text type="secondary">查询余额中…</Text>}
          {balanceError && <Text type="danger">余额查询失败</Text>}
          {!balanceLoading && !balanceError && balance?.supported && (
            <Text type={balance.balance !== null && balance.balance < 1 ? 'danger' : 'secondary'}>
              余额：{formatBalance(balance.balance, balance.currency)}
            </Text>
          )}
        </div>
      )}

      {/* 模型列表 */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Text strong>选择模型</Text>
          <Button type="text" size="small" icon={<ReloadOutlined />} onClick={handleRefreshModels} disabled={modelsLoading || disabled}>
            {modelsLoading ? '加载中…' : '刷新'}
          </Button>
        </div>
        {modelsError && <Alert message={`加载模型失败：${modelsError}`} type="error" showIcon style={{ marginBottom: 8 }} />}
        {modelsLoading && !modelsData && <Spin style={{ display: 'block', textAlign: 'center', padding: 16 }} />}
        {modelsData && (
          <>
            {sel.model && !modelsData.models.some(m => m.id === sel.model) && (
              <Tag color="blue" style={{ marginBottom: 8 }}>{sel.model}</Tag>
            )}
            <Collapse
              activeKey={expandedCats}
              onChange={(keys) => setExpandedCats(Array.isArray(keys) ? keys : [keys])}
              items={collapseItems}
              size="small"
            />
          </>
        )}
      </div>

      {/* panel 模式：应用按钮 */}
      {meetingId && (
        <div>
          {switchMsg && (
            <Alert
              message={switchMsg}
              type={switchMsg.includes('失败') ? 'error' : 'success'}
              showIcon
              style={{ marginBottom: 8 }}
            />
          )}
          <Button
            type="primary"
            onClick={handleApply}
            loading={switchLoading}
            disabled={!sel.model || disabled}
          >
            应用模型
          </Button>
        </div>
      )}
    </div>
  )
}

export function useModelSelection(initial?: Partial<ModelSelection>) {
  const [sel, setSel] = useState<ModelSelection>({ ...DEFAULT_SELECTION, ...initial })
  return { selection: sel, setSelection: setSel }
}
