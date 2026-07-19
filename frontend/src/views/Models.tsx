import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../state/AppContext';
import { apiGetProviders, apiGetModels } from '../lib/api';
import { PROVIDERS as MOCK_PROVIDERS, MODEL_CATALOG as MOCK_CATALOG } from '../data/mock';

interface Provider {
  id: string;
  name: string;
  hasKey?: boolean;
  balance?: string;
  currency?: string;
  baseUrl?: string;
  models?: number;
  pricingNote?: string;
}

interface ModelCatalogItem {
  id: string;
  name: string;
  provider: string;
  desc?: string;
  input?: number;
  output?: number;
  recommended?: boolean;
  cat?: string;
  score?: number;
  tier?: string;
}

// 基础 Provider 列表（配置性质，仅用于初始展示结构，实际数据从 API 覆盖）
const BASE_PROVIDERS: Provider[] = [
  { id: 'siliconflow', name: '硅基流动', baseUrl: 'https://api.siliconflow.cn/v1' },
  { id: 'deepseek', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1' },
  { id: 'openai', name: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
  { id: 'qwen', name: '通义千问', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { id: 'zhipu', name: '智谱 AI', baseUrl: 'https://open.bigmodel.cn/api/paas/v4' },
];

const PAGE_SIZE = 10;

type FilterCat = 'all' | 'recommended' | 'free' | 'reasoning' | 'embedding';

const FILTER_CHIPS: { key: FilterCat; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'recommended', label: '推荐' },
  { key: 'free', label: '免费' },
  { key: 'reasoning', label: '推理' },
  { key: 'embedding', label: '向量' },
];

// 阶段定义（配置常量，非业务数据）
const STAGES = [
  { key: 'clarify', name: '澄清', en: 'clarify' },
  { key: 'intra', name: '团队内讨论', en: 'intra_team' },
  { key: 'cross', name: '跨组辩论', en: 'cross_team' },
  { key: 'evidence', name: '证据校验', en: 'evidence_check' },
  { key: 'arbitrate', name: '仲裁', en: 'arbitrate' },
  { key: 'produce', name: '产出', en: 'produce' },
];

export default function Models() {
  const { toast, demoMode } = useApp();
  const navigate = useNavigate();

  const [providers, setProviders] = useState<Provider[]>(BASE_PROVIDERS);
  const [catalog, setCatalog] = useState<ModelCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [currentProvider, setCurrentProvider] = useState<string>('');
  const [modelSearch, setModelSearch] = useState('');
  const [modelFilter, setModelFilter] = useState<FilterCat>('all');
  const [modelPage, setModelPage] = useState(1);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);

      // 演示模式：使用 mock 数据
      if (demoMode) {
        const mockProviders: Provider[] = MOCK_PROVIDERS.map((p: any) => ({
          id: p.id, name: p.name, hasKey: true, balance: '演示', currency: 'CNY',
          baseUrl: p.base_url || '', models: MOCK_CATALOG.filter((m: any) => m.provider === p.id).length,
          pricingNote: '演示数据',
        }));
        const mockCatalog: ModelCatalogItem[] = MOCK_CATALOG.map((m: any) => ({
          id: m.id, name: m.name, provider: m.provider, desc: m.desc || '',
          input: m.input || 0, output: m.output || 0, recommended: !!m.recommended,
          cat: m.cat || 'all', score: m.score, tier: m.tier || '',
        }));
        if (!cancelled) {
          setProviders(mockProviders);
          setCatalog(mockCatalog);
          if (!currentProvider && mockProviders[0]) setCurrentProvider(mockProviders[0].id);
          setLoading(false);
        }
        return;
      }

      const errors: string[] = [];

      try {
        const data = await apiGetProviders(false);
        const list = Array.isArray(data) ? data : (data as any)?.providers;
        if (!cancelled && Array.isArray(list) && list.length) {
          // 合并基础信息
          const merged = list.map((p: any) => ({
            id: p.id,
            name: p.name || p.id,
            hasKey: !!p.has_key || !!p.hasKey,
            balance: p.balance,
            currency: p.currency || 'CNY',
            baseUrl: p.base_url || p.baseUrl,
            models: p.model_count || p.models || 0,
            pricingNote: p.pricing_note || '',
          }));
          setProviders(merged);
          if (!currentProvider && merged[0]) setCurrentProvider(merged[0].id);
        }
      } catch (e: any) {
        errors.push(`Provider: ${e.message}`);
      }

      try {
        const data = await apiGetModels(false);
        const list = Array.isArray(data) ? data : (data as any)?.models;
        if (!cancelled && Array.isArray(list) && list.length) {
          setCatalog(list.map((m: any) => ({
            id: m.id,
            name: m.name || m.id,
            provider: m.provider,
            desc: m.desc || '',
            input: m.input_price ?? m.input ?? 0,
            output: m.output_price ?? m.output ?? 0,
            recommended: !!m.recommended,
            cat: m.cat || m.category || 'all',
            score: m.score,
            tier: m.tier || '',
          })));
        }
      } catch (e: any) {
        errors.push(`模型列表: ${e.message}`);
      }

      if (!cancelled) {
        if (errors.length) {
          setError(errors.join('; '));
          toast('模型数据加载失败: ' + errors.join('; '), 'error', 5000);
        }
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
     
  }, [demoMode]);

  const activeProvider = providers.find((p) => p.id === currentProvider) || providers[0];

  const filteredModels = useMemo(() => {
    let models = catalog.filter((m) => m.provider === currentProvider);
    if (modelFilter !== 'all') {
      models = models.filter((m) => {
        if (modelFilter === 'recommended') return !!m.recommended;
        if (modelFilter === 'free') return (m.input ?? 0) === 0 && (m.output ?? 0) === 0;
        return m.cat === modelFilter;
      });
    }
    if (modelSearch.trim()) {
      const q = modelSearch.toLowerCase();
      models = models.filter(
        (m) => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q),
      );
    }
    return models;
  }, [catalog, currentProvider, modelFilter, modelSearch]);

  const totalPages = Math.max(1, Math.ceil(filteredModels.length / PAGE_SIZE));
  const currentPage = Math.min(modelPage, totalPages);
  const start = (currentPage - 1) * PAGE_SIZE;
  const pageItems = filteredModels.slice(start, start + PAGE_SIZE);

  function selectProvider(id: string) {
    setCurrentProvider(id);
    setModelPage(1);
  }

  function onSearch(v: string) {
    setModelSearch(v);
    setModelPage(1);
  }

  function setFilter(cat: FilterCat) {
    setModelFilter(cat);
    setModelPage(1);
  }

  // 从真实模型列表计算各阶段推荐模型（简单策略：推荐标记 > 价格最低）
  const stageModelRows = useMemo(() => {
    return STAGES.map(stage => {
      // 优先取 recommended 标记的模型
      const recommended = catalog.find(m => m.recommended && m.cat !== 'embedding');
      const byProvider = catalog.filter(m => m.provider === currentProvider);
      const selected = recommended || byProvider[0] || null;
      return {
        ...stage,
        model: selected ? selected.name : '未配置',
        score: selected?.score ?? '-',
        cost: selected ? `¥${selected.input ?? 0}/¥${selected.output ?? 0}` : '-',
        reason: selected ? (selected.desc || '') : '请先配置 Provider 和 API Key',
      };
    });
  }, [catalog, currentProvider]);

  return (
    <div className="view active" id="view-models">
      <div className="page-title" style={{ marginBottom: 8 }}>模型中心</div>
      <div style={{ fontSize: 13, color: 'var(--text-3)', marginBottom: error ? 12 : 32 }}>
        接入 OpenAI 兼容接口，检索可用模型并配置阶段分配
      </div>

      {error && (
        <div style={{
          padding: '10px 14px', background: 'var(--bg-elevated)', borderRadius: 6,
          border: '1px solid var(--error, #e74c3c)', color: 'var(--error, #e74c3c)',
          fontSize: 12, marginBottom: 20,
        }}>
          数据加载失败: {error}
        </div>
      )}

      {/* Provider tabs */}
      <div className="provider-tabs" id="provider-tabs">
        {providers.map((p) => (
          <span
            key={p.id}
            className={`provider-tab${p.id === currentProvider ? ' active' : ''}`}
            onClick={() => selectProvider(p.id)}
          >
            <span
              className="provider-tab-dot"
              style={{ background: p.hasKey ? 'var(--dot-done)' : 'var(--text-3)' }}
            />
            {p.name}
          </span>
        ))}
      </div>

      {/* Balance + key */}
      <div id="provider-detail">
        {activeProvider && (
          <div className="provider-detail">
            <div className="provider-balance">
              <span className="balance-label">账户余额</span>
              <span className="balance-value">
                {activeProvider.balance != null ? activeProvider.balance : '--'}
                {activeProvider.currency && (
                  <span className="balance-currency"> {activeProvider.currency}</span>
                )}
              </span>
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-3)' }}>
              <div>
                Base URL{' '}
                <span style={{ fontFamily: 'var(--mono)', color: 'var(--text-2)' }}>
                  {activeProvider.baseUrl || '--'}
                </span>
              </div>
              <div style={{ marginTop: 2 }}>
                可用模型{' '}
                <span style={{ fontFamily: 'var(--mono)', color: 'var(--text)' }}>
                  {activeProvider.models ?? '--'}
                </span>{' '}
                个
              </div>
            </div>
            <div className="provider-key-status">
              <span className={`status-dot ${activeProvider.hasKey ? 'done' : 'paused'}`} />
              {activeProvider.hasKey ? 'API Key 已配置' : '未配置 Key'}
              <span
                className="provider-key-btn"
                onClick={() => navigate(`/settings?provider=${activeProvider.id}`)}
              >
                {activeProvider.hasKey ? '更换 Key' : '配置 Key'}
              </span>
            </div>
            <div
              style={{
                marginLeft: 'auto',
                fontSize: 12,
                color: 'var(--text-3)',
                maxWidth: 200,
                textAlign: 'right',
              }}
            >
              {activeProvider.pricingNote || ''}
            </div>
          </div>
        )}
      </div>

      {/* Model search + filter */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 32, marginBottom: 16 }}>
        <div className="board-search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round"><circle cx="10.5" cy="10.5" r="6.5" /><line x1="15.5" y1="15.5" x2="21" y2="21" /></svg>
          <input
            type="text"
            placeholder="检索模型…"
            value={modelSearch}
            onChange={(e) => onSearch(e.target.value)}
            id="model-search-input"
          />
        </div>
        <div className="model-filter-chips" id="model-filter-chips">
          {FILTER_CHIPS.map((c) => (
            <span
              key={c.key}
              className={`filter-chip${modelFilter === c.key ? ' active' : ''}`}
              onClick={() => setFilter(c.key)}
            >
              {c.label}
            </span>
          ))}
        </div>
      </div>

      {/* Model list */}
      <div id="model-list">
        {loading && pageItems.length === 0 ? (
          <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 14 }}>
            加载模型列表...
          </div>
        ) : pageItems.length === 0 ? (
          <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 14 }}>
            {catalog.length === 0 ? '暂无模型数据，请先配置 API Key' : '该Provider下未找到匹配模型'}
          </div>
        ) : (
          pageItems.map((m) => {
            const isFree = (m.input ?? 0) === 0 && (m.output ?? 0) === 0;
            const priceStr = isFree ? (
              <span className="free">免费</span>
            ) : (
              `¥${m.input} / ¥${m.output}`
            );
            return (
              <div className="model-item" key={m.id}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="model-item-name">
                    {m.name}{' '}
                    {m.recommended && (
                      <span
                        style={{
                          fontSize: 10,
                          color: 'var(--accent)',
                          border: '1px solid var(--accent)',
                          padding: '1px 5px',
                          borderRadius: 3,
                          marginLeft: 6,
                        }}
                      >
                        推荐
                      </span>
                    )}
                  </div>
                  <div className="model-item-id">{m.id}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>{m.desc}</div>
                </div>
                {m.score ? <span className="stage-model-score">均分 {m.score}</span> : null}
                <span className="model-item-price">
                  {priceStr}
                  <span style={{ color: 'var(--text-3)', fontSize: 10 }}> /M</span>
                </span>
                <span className={`model-item-tier${m.recommended ? ' recommended' : ''}`}>
                  {m.tier || '-'}
                </span>
              </div>
            );
          })
        )}
      </div>

      {/* Pagination */}
      <div className="pagination" id="model-pagination">
        {totalPages <= 1 ? (
          <>
            <div />
            <div className="page-size">共 {filteredModels.length} 个模型</div>
          </>
        ) : (
          <>
            <div className="page-nums">
              <span className="page-arrow" onClick={() => { if (currentPage > 1) setModelPage(currentPage - 1); }}>‹</span>
              {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
                <span
                  key={n}
                  className={`page-num${n === currentPage ? ' active' : ''}`}
                  onClick={() => setModelPage(n)}
                >
                  {n}
                </span>
              ))}
              <span className="page-arrow" onClick={() => { if (currentPage < totalPages) setModelPage(currentPage + 1); }}>›</span>
            </div>
            <div className="page-size">{PAGE_SIZE}个/页 · 共{filteredModels.length}个</div>
          </>
        )}
      </div>

      {/* Stage config */}
      <div style={{ marginTop: 48 }}>
        <div className="page-title" style={{ fontSize: 16, marginBottom: 4 }}>阶段模型分配</div>
        <div style={{ fontSize: 13, color: 'var(--text-3)', marginBottom: 20 }}>
          会议管线各阶段使用的模型（从已配置 Provider 的模型列表中选取）
        </div>
        <div id="stage-model-config">
          {stageModelRows.map((s) => (
            <div className="stage-model-row" key={s.key}>
              <div>
                <div className="stage-model-label">{s.name}</div>
                <div className="stage-model-label-en">@{s.en}</div>
              </div>
              <div className="stage-model-select">{s.model}</div>
              <span className="stage-model-score">{s.score}分</span>
              <span className="stage-model-cost">{s.cost}/M</span>
              <div style={{ fontSize: 11, color: 'var(--text-3)', minWidth: 160, textAlign: 'right' }}>
                {s.reason}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
