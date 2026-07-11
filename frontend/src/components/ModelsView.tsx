// 模型管理独立页面：参考硅基流动分类方式，左侧筛选 + 右侧模型卡片列表
// 路由 /models，通过 DrawerMenu 第三项进入
import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import {
  Card, Input, Button, Tag, Typography, Space, Alert, Spin, Tooltip,
} from 'antd'
import {
  ReloadOutlined, CheckOutlined, SearchOutlined,
  CloudServerOutlined, KeyOutlined, DollarOutlined, ThunderboltOutlined,
  StarOutlined, SafetyCertificateOutlined, InfoCircleOutlined,
  AppstoreOutlined, EyeOutlined, CodeOutlined, DatabaseOutlined,
  FilterOutlined,
} from '@ant-design/icons'
import {
  listLLMProviders,
  listLLMModels,
  getLLMBalance,
  type LLMProvider,
  type LLMModel,
  type LLMModelsResponse,
  type LLMBalanceResponse,
} from '../lib/api.ts'
import {
  getApiKey,
  setApiKey as saveApiKey,
  getDefaultSelection,
  setDefaultSelection,
  onPreferencesChanged,
} from '../lib/llmPreferences.ts'
import type { ModelSelection } from './ModelSelector.tsx'

const { Text } = Typography

// ============================================================================
// 常量与辅助函数
// ============================================================================

const TIER_COLORS: Record<string, string> = {
  free: 'green', cheap: 'cyan', fast: 'blue', standard: 'default', pro: 'purple', reasoning: 'orange',
}
const TIER_LABELS: Record<string, string> = {
  free: '免费', cheap: '经济', fast: '快速', standard: '标准', pro: '专业', reasoning: '推理',
}

// 模型系列 → 显示名 + 颜色
const SERIES_CONFIG: Record<string, { label: string; color: string }> = {
  'Qwen': { label: 'Qwen 通义', color: '#6366f1' },
  'DeepSeek': { label: 'DeepSeek', color: '#2563eb' },
  'GLM': { label: 'GLM 智谱', color: '#059669' },
  'Kimi': { label: 'Kimi 月之暗面', color: '#7c3aed' },
  'MiniMax': { label: 'MiniMax', color: '#ea580c' },
  'LongCat': { label: 'LongCat 美团', color: '#16a34a' },
  'Hunyuan': { label: '混元 腾讯', color: '#0891b2' },
  'Nex': { label: 'Nex', color: '#9333ea' },
  'ERNIE': { label: 'ERNIE 百度', color: '#dc2626' },
  'bge': { label: 'BGE 向量', color: '#64748b' },
  'Z-Image': { label: 'Z-Image 通义', color: '#db2777' },
}

// 从模型 ID 提取系列
function extractSeries(modelId: string): string {
  const id = modelId.split('/').pop() || modelId
  for (const key of Object.keys(SERIES_CONFIG)) {
    if (id.toLowerCase().includes(key.toLowerCase())) return key
  }
  const vendor = modelId.split('/')[0]
  if (vendor && vendor !== modelId) {
    return vendor.split('-').map(s => s.charAt(0).toUpperCase() + s.slice(1)).join(' ')
  }
  return 'Other'
}

// 从模型 ID 提取参数规模
function extractSize(modelId: string): string {
  const id = modelId.split('/').pop() || modelId
  const match = id.match(/(\d+\.?\d*)\s*B/i)
  if (match) {
    const n = parseFloat(match[1])
    if (n >= 1000) return `${(n / 1000).toFixed(1)}T`
    return `${n}B`
  }
  return ''
}

// 模型类型分类
const TYPE_CONFIG: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  chat: { label: '对话', icon: <AppstoreOutlined />, color: '#3b82f6' },
  reasoning: { label: '推理', icon: <CodeOutlined />, color: '#f59e0b' },
  vision: { label: '多模态', icon: <EyeOutlined />, color: '#8b5cf6' },
  embedding: { label: '向量', icon: <DatabaseOutlined />, color: '#6b7280' },
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

const PROVIDER_ICONS: Record<string, React.ReactNode> = {
  siliconflow: <ThunderboltOutlined />,
  openai: <StarOutlined />,
  deepseek: <SafetyCertificateOutlined />,
  openrouter: <CloudServerOutlined />,
  custom: <CloudServerOutlined />,
}

// ============================================================================
// 扩展模型类型（包含解析后的元数据）
// ============================================================================

interface EnrichedModel extends LLMModel {
  series: string
  seriesLabel: string
  seriesColor: string
  size: string
  type: string
  typeLabel: string
}

// ============================================================================
// 主组件
// ============================================================================

export function ModelsView() {
  const [providers, setProviders] = useState<LLMProvider[]>([])
  const [providersLoading, setProvidersLoading] = useState(true)
  const [selectedProvider, setSelectedProvider] = useState('')
  const [apiKey, setApiKey] = useState('')

  const [modelsData, setModelsData] = useState<LLMModelsResponse | null>(null)
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const modelsCache = useRef<Map<string, LLMModelsResponse>>(new Map())

  const [searchQuery, setSearchQuery] = useState('')
  const [seriesFilter, setSeriesFilter] = useState<string>('')
  const [tierFilter, setTierFilter] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('')

  const [balance, setBalance] = useState<LLMBalanceResponse | null>(null)
  const [balanceLoading, setBalanceLoading] = useState(false)
  const [balanceError, setBalanceError] = useState<string | null>(null)

  const [defaultModel, setDefaultModel] = useState<ModelSelection>(() => getDefaultSelection())
  const [saveMsg, setSaveMsg] = useState<string | null>(null)

  // ---- 加载厂商列表 ----
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await listLLMProviders()
        if (!cancelled) {
          setProviders(res.providers)
          const def = getDefaultSelection()
          setSelectedProvider(def.provider_id)
          setApiKey(getApiKey(def.provider_id))
        }
      } catch { /* silent */ }
      finally { if (!cancelled) setProvidersLoading(false) }
    })()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    return onPreferencesChanged(() => setDefaultModel(getDefaultSelection()))
  }, [])

  const currentProvider = providers.find(p => p.id === selectedProvider) || null

  // ---- 切换厂商时加载模型列表 ----
  useEffect(() => {
    if (!selectedProvider || providers.length === 0) return
    const cacheKey = `${selectedProvider}:${apiKey}`
    const cached = modelsCache.current.get(cacheKey)
    if (cached) { setModelsData(cached); setModelsError(null); return }

    let cancelled = false
    setModelsLoading(true); setModelsError(null)
    void (async () => {
      try {
        const data = await listLLMModels({
          provider: selectedProvider,
          api_key: apiKey || undefined,
          base_url: currentProvider?.base_url || undefined,
          refresh: false,
        })
        if (!cancelled) { modelsCache.current.set(cacheKey, data); setModelsData(data) }
      } catch (e) {
        if (!cancelled) setModelsError(e instanceof Error ? e.message : String(e))
      } finally { if (!cancelled) setModelsLoading(false) }
    })()
    return () => { cancelled = true }
  }, [selectedProvider, apiKey, providers.length])

  // ---- 余额 ----
  const fetchBalance = useCallback(async () => {
    if (!currentProvider?.supports_balance) return
    setBalanceLoading(true); setBalanceError(null)
    try {
      const data = await getLLMBalance({
        provider: selectedProvider,
        api_key: apiKey || undefined,
        base_url: currentProvider.base_url || undefined,
      })
      setBalance(data)
    } catch (e) {
      setBalanceError(e instanceof Error ? e.message : String(e))
    } finally { setBalanceLoading(false) }
  }, [selectedProvider, apiKey, currentProvider])

  useEffect(() => {
    if (currentProvider?.supports_balance) {
      const t = setTimeout(fetchBalance, 300)
      return () => clearTimeout(t)
    } else { setBalance(null); setBalanceError(null) }
  }, [selectedProvider, apiKey, currentProvider?.supports_balance])

  const handleRefreshModels = async () => {
    const cacheKey = `${selectedProvider}:${apiKey}`
    modelsCache.current.delete(cacheKey)
    setModelsLoading(true); setModelsError(null)
    try {
      const data = await listLLMModels({
        provider: selectedProvider,
        api_key: apiKey || undefined,
        base_url: currentProvider?.base_url || undefined,
        refresh: true,
      })
      modelsCache.current.set(cacheKey, data)
      setModelsData(data)
    } catch (e) {
      setModelsError(e instanceof Error ? e.message : String(e))
    } finally { setModelsLoading(false) }
  }

  const handleSaveDefault = (modelId: string) => {
    setDefaultSelection({ provider_id: selectedProvider, model: modelId })
    if (apiKey) saveApiKey(selectedProvider, apiKey)
    setDefaultModel(getDefaultSelection())
    setSaveMsg(`已设为默认: ${selectedProvider} / ${modelId}`)
    setTimeout(() => setSaveMsg(null), 3000)
  }

  // ---- 构建富模型列表（从 categories 获取 pricing + type） ----
  const enrichedModels = useMemo((): EnrichedModel[] => {
    if (!modelsData) return []
    const modelTypeMap = new Map<string, string>()
    const typeOrder = ['recommended', 'reasoning', 'vision', 'embedding', 'chat', 'free']
    for (const type of typeOrder) {
      const items = modelsData.categories[type]
      if (items) {
        for (const m of items) {
          if (!modelTypeMap.has(m.id)) {
            // 推荐模型保持原始 type，其他按分类
            if (type === 'recommended' || type === 'free') {
              // 推荐的免费/推理/视觉模型保留其更精确的类型
              const isReasoning = m.id.match(/R1|r1|reason/i)
              const isVision = m.id.match(/VL|vision|image|ocr/i)
              const isEmbedding = m.id.match(/embed|bge|rerank/i)
              modelTypeMap.set(m.id, isEmbedding ? 'embedding' : isVision ? 'vision' : isReasoning ? 'reasoning' : 'chat')
            } else {
              modelTypeMap.set(m.id, type)
            }
          }
        }
      }
    }
    // 补充 raw models
    if (modelsData.models) {
      for (const m of modelsData.models) {
        if (!modelTypeMap.has(m.id)) {
          const isEmbedding = m.id.match(/embed|bge|rerank/i)
          const isVision = m.id.match(/VL|vision|image|ocr/i)
          const isReasoning = m.id.match(/R1|r1|reason/i)
          modelTypeMap.set(m.id, isEmbedding ? 'embedding' : isVision ? 'vision' : isReasoning ? 'reasoning' : 'chat')
        }
      }
    }

    // 从 categories 中合并 pricing
    const pricingMap = new Map<string, LLMModel['pricing']>()
    for (const type of typeOrder) {
      const items = modelsData.categories[type]
      if (items) {
        for (const m of items) {
          if (m.pricing && !pricingMap.has(m.id)) {
            pricingMap.set(m.id, m.pricing)
          }
        }
      }
    }

    const seen = new Set<string>()
    const result: EnrichedModel[] = []
    const allModels = [
      ...(modelsData.categories.recommended || []),
      ...(modelsData.categories.reasoning || []),
      ...(modelsData.categories.vision || []),
      ...(modelsData.categories.chat || []),
      ...(modelsData.categories.free || []),
      ...(modelsData.categories.embedding || []),
      ...(modelsData.models || []),
    ]

    for (const m of allModels) {
      if (seen.has(m.id)) continue
      seen.add(m.id)
      const series = extractSeries(m.id)
      const seriesCfg = SERIES_CONFIG[series]
      const type = modelTypeMap.get(m.id) || 'chat'
      const typeCfg = TYPE_CONFIG[type] || TYPE_CONFIG.chat

      result.push({
        ...m,
        pricing: pricingMap.get(m.id) || m.pricing,
        series,
        seriesLabel: seriesCfg?.label || series,
        seriesColor: seriesCfg?.color || '#6b7280',
        size: extractSize(m.id),
        type,
        typeLabel: typeCfg.label,
      })
    }

    // 排序：推荐 > 推理 > 对话 > 多模态 > 向量
    const typePriority: Record<string, number> = { reasoning: 1, chat: 2, vision: 3, embedding: 4 }
    result.sort((a, b) => (typePriority[a.type] ?? 5) - (typePriority[b.type] ?? 5))

    return result
  }, [modelsData])

  // ---- 可用系列列表 ----
  const availableSeries = useMemo(() => {
    const s = new Map<string, number>()
    enrichedModels.forEach(m => s.set(m.series, (s.get(m.series) || 0) + 1))
    return Array.from(s.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([key, count]) => ({ key, count, config: SERIES_CONFIG[key] }))
  }, [enrichedModels])

  // ---- 可用 tier ----
  const availableTiers = useMemo(() => {
    const tiers = new Set<string>()
    enrichedModels.forEach(m => tiers.add(m.pricing?.tier || 'standard'))
    const order = ['free', 'cheap', 'fast', 'standard', 'pro', 'reasoning']
    return Array.from(tiers).sort((a, b) => order.indexOf(a) - order.indexOf(b))
  }, [enrichedModels])

  // ---- 可用类型 ----
  const availableTypes = useMemo(() => {
    const t = new Map<string, number>()
    enrichedModels.forEach(m => t.set(m.type, (t.get(m.type) || 0) + 1))
    return Array.from(t.entries())
      .map(([key, count]) => ({ key, count, config: TYPE_CONFIG[key] || TYPE_CONFIG.chat }))
      .sort((a, b) => b.count - a.count)
  }, [enrichedModels])

  // ---- 筛选后的模型 ----
  const filteredModels = useMemo(() => {
    let list = enrichedModels
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      list = list.filter(m => m.id.toLowerCase().includes(q))
    }
    if (seriesFilter) {
      list = list.filter(m => m.series === seriesFilter)
    }
    if (tierFilter) {
      list = list.filter(m => (m.pricing?.tier || 'standard') === tierFilter)
    }
    if (typeFilter) {
      list = list.filter(m => m.type === typeFilter)
    }
    return list
  }, [enrichedModels, searchQuery, seriesFilter, tierFilter, typeFilter])

  const isDefault = (providerId: string, modelId: string) =>
    providerId === defaultModel.provider_id && modelId === defaultModel.model

  const needsApiKey = currentProvider && !currentProvider.has_key && !apiKey && modelsData?.total === 0

  // ---- 清除所有筛选 ----
  const clearFilters = () => { setSeriesFilter(''); setTierFilter(''); setTypeFilter('') }
  const hasFilters = seriesFilter || tierFilter || typeFilter

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 1400, margin: '0 auto' }}>
      {/* ---- 当前默认模型（顶部横幅） ---- */}
      <Card
        size="small"
        style={{
          borderRadius: 10,
          border: '1px solid var(--accent-color, #4f46e5)',
          background: 'linear-gradient(135deg, var(--accent-bg, #eef2ff) 0%, var(--bg, #fff) 100%)',
          boxShadow: '0 1px 4px rgba(79,70,229,0.08)',
        }}
        styles={{ body: { padding: '14px 20px' } }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 8, flexShrink: 0,
              background: 'var(--accent-color, #4f46e5)', color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16,
            }}>
              <StarOutlined />
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 11, color: 'var(--text-secondary, #888)', marginBottom: 2 }}>当前默认模型</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <Tag color="blue" style={{ margin: 0, borderRadius: 4 }}>{defaultModel.provider_id}</Tag>
                <Text strong style={{ fontSize: 15, fontFamily: 'Consolas, monospace' }} ellipsis>
                  {defaultModel.model || '（未选择）'}
                </Text>
              </div>
            </div>
          </div>
          <Text type="secondary" style={{ fontSize: 12, flexShrink: 0 }}>
            创建新会议时使用此模型
          </Text>
        </div>
      </Card>

      {saveMsg && (
        <Alert message={saveMsg} type="success" showIcon closable onClose={() => setSaveMsg(null)} />
      )}

      {/* ---- 厂商选择 + API Key + 余额（整合为一行卡片） ---- */}
      <Card
        size="small"
        style={{ borderRadius: 10 }}
        styles={{ body: { padding: '16px 20px' } }}
        title={
          <span style={{ fontSize: 14, fontWeight: 600 }}>
            <ThunderboltOutlined style={{ marginRight: 6, color: '#6366f1' }} />
            LLM 厂商配置
          </span>
        }
        extra={
          <Tooltip title="刷新厂商列表">
            <Button type="text" size="small" icon={<ReloadOutlined spin={providersLoading} />}
              onClick={() => {
                setProvidersLoading(true)
                listLLMProviders().then(r => { setProviders(r.providers); setProvidersLoading(false) }).catch(() => setProvidersLoading(false))
              }} />
          </Tooltip>
        }
      >
        {providersLoading ? (
          <div style={{ textAlign: 'center', padding: 20 }}><Spin /></div>
        ) : (
          <>
            {/* 厂商卡片横向排列 */}
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
              {providers.map(p => {
                const isActive = p.id === selectedProvider
                return (
                  <Card key={p.id} hoverable size="small"
                    style={{
                      width: 180, cursor: 'pointer', borderRadius: 8,
                      borderColor: isActive ? 'var(--accent-color, #4f46e5)' : 'var(--border, #e5e7eb)',
                      borderWidth: isActive ? 2 : 1,
                      background: isActive ? 'var(--accent-bg, #eef2ff)' : 'var(--bg, #fff)',
                      transition: 'all 0.2s',
                    }}
                    styles={{ body: { padding: '10px 14px' } }}
                    onClick={() => { setSelectedProvider(p.id); setApiKey(getApiKey(p.id)); setBalance(null) }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span style={{ fontSize: 18, color: isActive ? 'var(--accent-color, #4f46e5)' : '#888' }}>
                        {PROVIDER_ICONS[p.id] || <CloudServerOutlined />}
                      </span>
                      <Text strong style={{ fontSize: 13 }}>{p.name}</Text>
                    </div>
                    <Space size={4} wrap>
                      {p.has_key && <Tag color="green" style={{ fontSize: 10, margin: 0 }}>已配置</Tag>}
                      {p.supports_balance && <Tag color="cyan" style={{ fontSize: 10, margin: 0 }}>余额查询</Tag>}
                      {p.supports_custom_key && <Tag style={{ fontSize: 10, margin: 0 }}>自定义Key</Tag>}
                    </Space>
                  </Card>
                )
              })}
            </div>

            {/* API Key 输入 + 余额显示 */}
            {currentProvider && (
              <div style={{
                display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap',
                padding: '12px 16px', borderRadius: 8,
                background: 'var(--bg-secondary, #f8f9fb)',
                border: '1px solid var(--border, #e5e7eb)',
              }}>
                {currentProvider.supports_custom_key && (
                  <div style={{ flex: '1 1 400px', minWidth: 280, maxWidth: 560 }}>
                    <Input.Password
                      placeholder={currentProvider.has_key ? '留空使用系统默认 Key' : '输入 API Key（sk-...）'}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      autoComplete="off"
                      prefix={<KeyOutlined style={{ color: '#8c8c8c' }} />}
                      size="large"
                      style={{ borderRadius: 6 }}
                    />
                  </div>
                )}
                {currentProvider.supports_balance && (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '8px 16px', borderRadius: 8,
                    background: 'var(--bg, #fff)',
                    border: '1px solid var(--border, #e5e7eb)',
                  }}>
                    <DollarOutlined style={{ fontSize: 18, color: '#52c41a' }} />
                    <div>
                      <div style={{ fontSize: 10, color: 'var(--text-secondary, #888)' }}>账户余额</div>
                      <div>
                        {balanceLoading ? <Spin size="small" /> : balanceError ? (
                          <Text type="danger" style={{ fontSize: 14 }}>查询失败</Text>
                        ) : balance?.supported ? (
                          <Text strong style={{
                            fontSize: 18,
                            color: balance.balance !== null && balance.balance < 1 ? '#ff4d4f' : '#52c41a',
                          }}>
                            {formatBalance(balance.balance, balance.currency)}
                          </Text>
                        ) : <Text type="secondary" style={{ fontSize: 13 }}>不支持</Text>}
                      </div>
                    </div>
                    <Tooltip title="刷新余额">
                      <Button type="text" size="small" icon={<ReloadOutlined spin={balanceLoading} />} onClick={fetchBalance} />
                    </Tooltip>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </Card>

      {/* ---- 无 API Key 提示 ---- */}
      {needsApiKey && (
        <Alert type="info" showIcon icon={<InfoCircleOutlined />}
          message={`${currentProvider!.name} 尚未配置 API Key`}
          description={`在上方输入你的 API Key 后即可查看该厂商的可用模型列表。`}
        />
      )}

      {/* ---- 主内容区：筛选 + 模型列表 ---- */}
      {modelsData && !needsApiKey && (
        <Card
          style={{ borderRadius: 10, flex: 1, minHeight: 0 }}
          styles={{ body: { padding: 0, display: 'flex', flexDirection: 'column', height: '100%' } }}
        >
          <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>

            {/* 左侧筛选栏 */}
            <div style={{
              width: 220, flexShrink: 0, overflowY: 'auto',
              borderRight: '1px solid var(--border, #e5e7eb)',
              padding: '16px 16px 16px 20px',
              background: 'var(--bg-secondary, #fafbfc)',
              borderTopLeftRadius: 10,
              borderBottomLeftRadius: 10,
            }}>
              {/* 搜索 */}
              <Input
                placeholder="搜索模型..."
                prefix={<SearchOutlined />}
                allowClear
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ marginBottom: 16 }}
                size="middle"
              />

              {/* 类型筛选 */}
              <div style={{ marginBottom: 16 }}>
                <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 8, color: 'var(--text-secondary, #888)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  类型
                </Text>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {availableTypes.map(({ key, count, config }) => (
                    <Button
                      key={key}
                      type={typeFilter === key ? 'primary' : 'default'}
                      size="small"
                      icon={config.icon}
                      onClick={() => setTypeFilter(typeFilter === key ? '' : key)}
                    >
                      {config.label} <Text type="secondary" style={{ fontSize: 10 }}>({count})</Text>
                    </Button>
                  ))}
                </div>
              </div>

              {/* 系列筛选 */}
              <div style={{ marginBottom: 16 }}>
                <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 8, color: 'var(--text-secondary, #888)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  系列
                </Text>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {availableSeries.map(({ key, count, config }) => (
                    <div
                      key={key}
                      onClick={() => setSeriesFilter(seriesFilter === key ? '' : key)}
                      style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '6px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 13,
                        background: seriesFilter === key ? 'var(--accent-bg, #eef2ff)' : 'transparent',
                        borderLeft: seriesFilter === key ? `3px solid ${config?.color || '#6b7280'}` : '3px solid transparent',
                        transition: 'all 0.15s',
                      }}
                    >
                      <span style={{ color: seriesFilter === key ? (config?.color || '#333') : 'var(--text, #333)', fontWeight: seriesFilter === key ? 600 : 400 }}>
                        {config?.label || key}
                      </span>
                      <Text type="secondary" style={{ fontSize: 11 }}>{count}</Text>
                    </div>
                  ))}
                </div>
              </div>

              {/* 层级筛选 */}
              {availableTiers.length > 1 && (
                <div style={{ marginBottom: 16 }}>
                  <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 8, color: 'var(--text-secondary, #888)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    层级
                  </Text>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {availableTiers.map(t => (
                      <Tag
                        key={t}
                        color={tierFilter === t ? TIER_COLORS[t] : undefined}
                        style={{ cursor: 'pointer', fontSize: 12, padding: '2px 8px', borderRadius: 4 }}
                        onClick={() => setTierFilter(tierFilter === t ? '' : t)}
                      >
                        {TIER_LABELS[t] ?? t}
                      </Tag>
                    ))}
                  </div>
                </div>
              )}

              {/* 清除筛选 */}
              {hasFilters && (
                <Button type="link" size="small" icon={<FilterOutlined />} onClick={clearFilters} style={{ fontSize: 12, padding: 0 }}>
                  清除所有筛选
                </Button>
              )}
            </div>

            {/* 右侧模型列表 */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', padding: '16px 20px', minHeight: 400 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexShrink: 0 }}>
                <Space size={8}>
                  <Text strong style={{ fontSize: 14 }}>可用模型</Text>
                  <Tag color="blue" style={{ margin: 0 }}>{filteredModels.length} 个</Tag>
                  {searchQuery && <Text type="secondary" style={{ fontSize: 12 }}>搜索: "{searchQuery}"</Text>}
                </Space>
                <Tooltip title="刷新模型列表">
                  <Button type="text" size="small" icon={<ReloadOutlined spin={modelsLoading} />} onClick={handleRefreshModels} disabled={modelsLoading} />
                </Tooltip>
              </div>

              {modelsError && <Alert message={`加载失败：${modelsError}`} type="error" showIcon style={{ marginBottom: 12 }} />}

              <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', paddingRight: 4 }}>
                {filteredModels.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-secondary, #999)' }}>
                    <SearchOutlined style={{ fontSize: 32, marginBottom: 8, display: 'block' }} />
                    {searchQuery || hasFilters ? '无匹配模型，试试调整筛选条件' : '暂无可用模型'}
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {filteredModels.map((m) => {
                      const tier = m.pricing?.tier || 'standard'
                      const isDef = isDefault(selectedProvider, m.id)
                      const typeCfg = TYPE_CONFIG[m.type] || TYPE_CONFIG.chat
                      return (
                        <div key={m.id} style={{
                          display: 'flex', alignItems: 'center', padding: '10px 14px', borderRadius: 8, gap: 12,
                          border: isDef ? '2px solid var(--accent-color, #4f46e5)' : '1px solid var(--border, #e5e7eb)',
                          background: isDef ? 'var(--accent-bg, #eef2ff)' : 'var(--bg, #fff)',
                          transition: 'all 0.15s',
                          cursor: 'default',
                        }}
                        onMouseEnter={(e) => {
                          if (!isDef) (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--accent-color, #4f46e5)'
                        }}
                        onMouseLeave={(e) => {
                          if (!isDef) (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border, #e5e7eb)'
                        }}
                        >
                          {/* 系列色条 */}
                          <div style={{
                            width: 4, alignSelf: 'stretch', borderRadius: 2, flexShrink: 0,
                            background: m.seriesColor,
                          }} />

                          {/* 模型信息 */}
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                              {isDef && <CheckOutlined style={{ color: 'var(--accent-color, #4f46e5)', fontSize: 14 }} />}
                              <Text strong style={{ fontSize: 13, fontFamily: 'Consolas, "JetBrains Mono", monospace' }}>
                                {m.id}
                              </Text>
                              {isDef && <Tag color="blue" style={{ fontSize: 10, lineHeight: '18px', padding: '0 6px', margin: 0, borderRadius: 4 }}>默认</Tag>}
                              {m.size && (
                                <Tag style={{ fontSize: 10, lineHeight: '18px', padding: '0 6px', margin: 0, borderRadius: 4, background: '#f0f0f0', border: 'none', color: '#666' }}>
                                  {m.size}
                                </Tag>
                              )}
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                              <Tag style={{
                                fontSize: 10, lineHeight: '18px', padding: '0 6px', margin: 0, borderRadius: 4,
                                borderColor: typeCfg.color, color: typeCfg.color, background: 'transparent',
                              }}>
                                {typeCfg.icon} {m.typeLabel}
                              </Tag>
                              <Tag color={TIER_COLORS[tier]} style={{ fontSize: 10, lineHeight: '18px', padding: '0 6px', margin: 0, borderRadius: 4 }}>
                                {TIER_LABELS[tier] ?? tier}
                              </Tag>
                              {m.pricing && m.pricing.input !== undefined && (
                                <Text type="secondary" style={{ fontSize: 11 }}>
                                  输入 {formatPrice(m.pricing.input, m.pricing.currency)} / 输出 {formatPrice(m.pricing.output, m.pricing.currency)}
                                </Text>
                              )}
                            </div>
                          </div>

                          {/* 操作按钮 */}
                          {isDef ? (
                            <Tag color="blue" icon={<CheckOutlined />} style={{ margin: 0, borderRadius: 4 }}>当前默认</Tag>
                          ) : (
                            <Button
                              type="primary"
                              size="small"
                              ghost={!isDef}
                              icon={<StarOutlined />}
                              onClick={() => handleSaveDefault(m.id)}
                              style={{ flexShrink: 0, borderRadius: 6 }}
                            >
                              设为默认
                            </Button>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
