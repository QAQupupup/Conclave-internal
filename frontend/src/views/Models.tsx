import { useEffect, useMemo, useState } from 'react';
import { useApp } from '../state/AppContext';
import { PROVIDERS, MODEL_CATALOG, STAGE_MODELS } from '../data/mock';
import { apiGetProviders, apiGetModels } from '../lib/api';

type Provider = typeof PROVIDERS[number];
type ModelCatalogItem = typeof MODEL_CATALOG[number];

const PAGE_SIZE = 10;

type FilterCat = 'all' | 'recommended' | 'free' | 'reasoning' | 'embedding';

const FILTER_CHIPS: { key: FilterCat; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'recommended', label: '推荐' },
  { key: 'free', label: '免费' },
  { key: 'reasoning', label: '推理' },
  { key: 'embedding', label: '向量' },
];

export default function Models() {
  const { appendLog } = useApp();

  // 数据：默认使用 mock，API 成功则覆盖
  const [providers, setProviders] = useState<Provider[]>(PROVIDERS);
  const [catalog, setCatalog] = useState<ModelCatalogItem[]>(MODEL_CATALOG);

  // 本地交互状态
  const [currentProvider, setCurrentProvider] = useState<string>('siliconflow');
  const [modelSearch, setModelSearch] = useState('');
  const [modelFilter, setModelFilter] = useState<FilterCat>('all');
  const [modelPage, setModelPage] = useState(1);

  // 进入视图时尝试拉取真实数据，失败回退 mock（不让请求失败导致空白）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGetProviders();
        const list = Array.isArray(data) ? data : (data as any)?.providers;
        if (!cancelled && Array.isArray(list) && list.length) {
          // 仅在返回结构可识别时覆盖，避免破坏渲染
          setProviders(list as Provider[]);
        }
      } catch (e: any) {
        // 静默回退 mock
        if (!cancelled) appendLog?.('模型 Provider 拉取失败，使用本地数据', 'debug');
      }
      try {
        const data = await apiGetModels();
        const list = Array.isArray(data) ? data : (data as any)?.models;
        if (!cancelled && Array.isArray(list) && list.length) {
          setCatalog(list as ModelCatalogItem[]);
        }
      } catch (e: any) {
        if (!cancelled) appendLog?.('模型列表拉取失败，使用本地数据', 'debug');
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeProvider = providers.find((p) => p.id === currentProvider) || providers[0];

  // 过滤 + 搜索
  const filteredModels = useMemo(() => {
    let models = catalog.filter((m) => m.provider === currentProvider);
    if (modelFilter !== 'all') {
      models = models.filter((m) => {
        if (modelFilter === 'recommended') return !!m.recommended;
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

  // 分页
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

  return (
    <div className="view active" id="view-models">
      <div className="page-title" style={{ marginBottom: 8 }}>模型中心</div>
      <div style={{ fontSize: 13, color: 'var(--text-3)', marginBottom: 32 }}>
        接入硅基流动等 OpenAI 兼容接口，检索可用模型并配置阶段分配
      </div>

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
                {activeProvider.balance}
                <span className="balance-currency"> {activeProvider.currency}</span>
              </span>
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-3)' }}>
              <div>
                Base URL{' '}
                <span style={{ fontFamily: 'var(--mono)', color: 'var(--text-2)' }}>
                  {activeProvider.baseUrl}
                </span>
              </div>
              <div style={{ marginTop: 2 }}>
                可用模型{' '}
                <span style={{ fontFamily: 'var(--mono)', color: 'var(--text)' }}>
                  {activeProvider.models}
                </span>{' '}
                个
              </div>
            </div>
            <div className="provider-key-status">
              <span className={`status-dot ${activeProvider.hasKey ? 'done' : 'paused'}`} />
              {activeProvider.hasKey ? 'API Key 已配置' : '未配置 Key'}
              <span
                className="provider-key-btn"
                onClick={() => alert('BYOK配置面板（原型）')}
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
              {activeProvider.pricingNote}
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
        {pageItems.length === 0 ? (
          <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-3)', fontSize: 14 }}>
            该Provider下未找到匹配模型
          </div>
        ) : (
          pageItems.map((m) => {
            const isFree = m.input === 0 && m.output === 0;
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
                  {m.tier}
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
          为六阶段会议管线配置默认模型，基于基准测试推荐最优组合
        </div>
        <div id="stage-model-config">
          {STAGE_MODELS.map((s, i) => (
            <div className="stage-model-row" key={s.stageEn + i}>
              <div>
                <div className="stage-model-label">{s.stage}</div>
                <div className="stage-model-label-en">@{s.stageEn}</div>
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
        <div
          style={{
            marginTop: 16,
            padding: '16px 0',
            borderTop: '1px solid var(--line)',
            display: 'flex',
            alignItems: 'center',
            gap: 24,
            fontSize: 13,
            color: 'var(--text-3)',
          }}
        >
          <span>
            预估单轮成本{' '}
            <span style={{ fontFamily: 'var(--mono)', color: 'var(--text)' }}>¥0.97</span>
          </span>
          <span>
            10轮预估{' '}
            <span style={{ fontFamily: 'var(--mono)', color: 'var(--text)' }}>¥9.70</span>
          </span>
          <span>
            对比全 GLM-5.2{' '}
            <span style={{ fontFamily: 'var(--mono)', color: 'var(--text)' }}>节省 63%</span>
          </span>
        </div>
      </div>
    </div>
  );
}
