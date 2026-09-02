import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useAuthStore } from '@/stores/auth-slice';
import { api, ApiError } from '@/lib/api';
import {
  CpuIcon,
  SearchIcon,
  SpinnerIcon,
  ServerIcon,
  DatabaseIcon,
  CheckIcon,
  AlertCircleIcon,
} from '@/components/ui/svg-icons';

// ===== 类型定义 =====

interface EffectiveConfig {
  llm_model?: string;
  llm_base_url?: string;
  llm_api_key?: string;
  embed_model?: string;
  embed_base_url?: string;
  embed_api_key?: string;
  rerank_model?: string;
  rerank_base_url?: string;
  rerank_api_key?: string;
  default_temperature?: number;
  [key: string]: unknown;
}

interface ApiKeyItem {
  id: number;
  provider: string;
  name: string;
  key_masked: string;
  base_url: string;
  is_default: boolean;
  scope: string;
  created_at?: string;
  updated_at?: string;
}

interface ApiKeysResponse {
  items: ApiKeyItem[];
}

interface SystemConfigResponse {
  settings: Record<string, unknown>;
  overridable_keys: string[];
}

// ===== 静态模型目录 =====

type ModelCategory = 'chat' | 'reasoning' | 'embedding';

interface CatalogModel {
  id: string;
  name: string;
  provider: string;
  cat: ModelCategory;
  recommended: boolean;
}

const MODEL_CATALOG: CatalogModel[] = [
  { id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash', provider: 'deepseek', cat: 'chat', recommended: true },
  { id: 'deepseek-v4-pro', name: 'DeepSeek V4 Pro', provider: 'deepseek', cat: 'reasoning', recommended: true },
  { id: 'deepseek-ai/DeepSeek-V4-Flash', name: 'DeepSeek V4 Flash (硅基)', provider: 'siliconflow', cat: 'chat', recommended: true },
  { id: 'deepseek-ai/DeepSeek-V3.2', name: 'DeepSeek V3.2 (硅基)', provider: 'siliconflow', cat: 'chat', recommended: false },
  { id: 'qwen-plus', name: 'Qwen Plus', provider: 'qwen', cat: 'chat', recommended: true },
  { id: 'qwen-max', name: 'Qwen Max', provider: 'qwen', cat: 'chat', recommended: false },
  { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', cat: 'chat', recommended: true },
  { id: 'gpt-4o-mini', name: 'GPT-4o mini', provider: 'openai', cat: 'chat', recommended: false },
  { id: 'doubao-seed-2-0-code', name: 'Doubao Seed 2.0 Code', provider: 'doubao', cat: 'chat', recommended: true },
  { id: 'BAAI/bge-m3', name: 'BGE-M3', provider: 'local', cat: 'embedding', recommended: true },
  { id: 'BAAI/bge-large-zh-v1.5', name: 'BGE-Large-ZH', provider: 'local', cat: 'embedding', recommended: false },
  { id: 'text-embedding-v3', name: 'Text Embedding V3', provider: 'qwen', cat: 'embedding', recommended: true },
];

// ===== Provider 显示名称映射 =====

const PROVIDER_LABELS: Record<string, string> = {
  deepseek: 'DeepSeek',
  siliconflow: '硅基流动 (SiliconFlow)',
  doubao: '豆包 (火山引擎)',
  qwen: '通义千问 (DashScope)',
  openai: 'OpenAI',
  local: '本地模型',
  custom: '自定义 (OpenAI 兼容)',
};

function getProviderLabel(provider: string): string {
  return PROVIDER_LABELS[provider] || provider;
}

// ===== 阶段定义 =====

interface StageDef {
  key: string;
  label: string;
  description: string;
  defaultTemp: string;
}

const STAGES: StageDef[] = [
  { key: 'clarify', label: '澄清阶段', description: '理解并拆解用户问题', defaultTemp: '0.0' },
  { key: 'intra_team', label: '团队内讨论', description: 'Agent 在各自团队内探索', defaultTemp: '0.3' },
  { key: 'cross_team', label: '跨团队讨论', description: '跨团队交换观点与论据', defaultTemp: '0.0' },
  { key: 'evidence_check', label: '证据核查', description: '验证论点的事实依据', defaultTemp: '0.0' },
  { key: 'arbitrate', label: '仲裁阶段', description: '综合各方观点形成结论', defaultTemp: '0.0' },
  { key: 'produce', label: '产出阶段', description: '生成最终交付物', defaultTemp: '0.1' },
];

// ===== 分类筛选选项 =====

type FilterChip = 'all' | 'recommended' | 'reasoning' | 'embedding';

const FILTER_CHIPS: { value: FilterChip; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'recommended', label: '推荐' },
  { value: 'reasoning', label: '推理' },
  { value: 'embedding', label: '向量' },
];

const CATEGORY_LABELS: Record<ModelCategory, string> = {
  chat: '对话',
  reasoning: '推理',
  embedding: '向量',
};

// ===== 错误处理 =====

function getErrorDisplay(err: unknown, endpoint: string): { title: string; hint: string } {
  if (err instanceof ApiError) {
    if (err.status === 401) return { title: '登录已过期', hint: '正在跳转到登录页...' };
    if (err.status === 403) return { title: '权限不足', hint: '仅系统管理员可执行此操作' };
    if (err.status === 404) return { title: '接口暂未实现', hint: `后端尚未提供 ${endpoint} 端点` };
    if (err.status >= 500) return { title: '服务器错误', hint: `服务暂不可用（${err.status}）` };
    return { title: '请求失败', hint: err.message || `HTTP ${err.status}` };
  }
  if (err instanceof TypeError) return { title: '无法连接服务器', hint: '请确认后端服务已启动' };
  return { title: '加载失败', hint: endpoint ? `后端尚未提供 ${endpoint} 端点` : '未知错误' };
}

// ===== 主组件 =====

export default function ModelsPage() {
  const { toast } = useToast();
  const user = useAuthStore((s) => s.user);
  const qc = useQueryClient();

  const isAdmin =
    user?.system_role === 'system_owner' ||
    user?.system_role === 'system_admin' ||
    user?.system_role === 'admin' ||
    user?.role === 'admin' ||
    user?.role === 'owner';

  // ===== 查询：有效配置 =====
  const {
    data: config,
    isLoading: configLoading,
    error: configError,
  } = useQuery({
    queryKey: ['models', 'effective-config'],
    queryFn: () => api.get<EffectiveConfig>('/api/config/effective'),
    retry: false,
  });

  // ===== 查询：API Keys =====
  const {
    data: keysData,
    isLoading: keysLoading,
    error: keysError,
  } = useQuery({
    queryKey: ['models', 'api-keys'],
    queryFn: () => api.get<ApiKeysResponse>('/api/keys?scope=all'),
    retry: false,
  });

  // ===== 查询：系统配置（仅管理员，用于读取 stage_model_* 值） =====
  const {
    data: sysConfigData,
    isLoading: sysConfigLoading,
  } = useQuery({
    queryKey: ['models', 'system-config'],
    queryFn: () => api.get<SystemConfigResponse>('/api/config/system'),
    enabled: isAdmin,
    retry: false,
  });

  // ===== 阶段模型状态 =====
  const [stageModels, setStageModels] = React.useState<Record<string, string>>({});
  const [stageModelsDirty, setStageModelsDirty] = React.useState(false);

  // 从系统配置或有效配置中初始化阶段模型
  React.useEffect(() => {
    const source = sysConfigData?.settings ?? config ?? {};
    const next: Record<string, string> = {};
    for (const stage of STAGES) {
      const key = `stage_model_${stage.key}`;
      const val = source[key];
      if (typeof val === 'string' && val) {
        next[stage.key] = val;
      } else if (typeof val === 'number') {
        next[stage.key] = String(val);
      }
    }
    setStageModels(next);
    setStageModelsDirty(false);
  }, [sysConfigData, config]);

  // ===== 保存阶段模型配置 =====
  const saveStageModels = useMutation({
    mutationFn: async (models: Record<string, string>) => {
      const entries = Object.entries(models).filter(([, v]) => v);
      // 逐个调用 PUT /api/config/system/{key}
      await Promise.all(
        entries.map(([stageKey, modelId]) =>
          api.put(`/api/config/system/stage_model_${stageKey}`, { value: modelId })
        )
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['models', 'system-config'] });
      qc.invalidateQueries({ queryKey: ['models', 'effective-config'] });
      setStageModelsDirty(false);
      toast({ title: '阶段模型配置已保存', description: '各阶段模型分配已更新' });
    },
    onError: (err: unknown) => {
      const info = getErrorDisplay(err, 'PUT /api/config/system/stage_model_*');
      toast({
        title: info.title,
        description: info.hint,
        variant: 'destructive',
      });
    },
  });

  const handleStageModelChange = (stageKey: string, modelId: string) => {
    setStageModels((prev) => ({ ...prev, [stageKey]: modelId }));
    setStageModelsDirty(true);
  };

  const handleSaveStageModels = () => {
    saveStageModels.mutate(stageModels);
  };

  // ===== 模型目录搜索与筛选 =====
  const [searchQuery, setSearchQuery] = React.useState('');
  const [filterChip, setFilterChip] = React.useState<FilterChip>('all');

  const filteredModels = React.useMemo(() => {
    let result = MODEL_CATALOG;
    if (filterChip === 'recommended') {
      result = result.filter((m) => m.recommended);
    } else if (filterChip === 'reasoning') {
      result = result.filter((m) => m.cat === 'reasoning');
    } else if (filterChip === 'embedding') {
      result = result.filter((m) => m.cat === 'embedding');
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter(
        (m) =>
          m.name.toLowerCase().includes(q) ||
          m.id.toLowerCase().includes(q) ||
          m.provider.toLowerCase().includes(q)
      );
    }
    return result;
  }, [searchQuery, filterChip]);

  // ===== 可选模型列表（用于阶段下拉，排除 embedding） =====
  const selectableModels = React.useMemo(
    () => MODEL_CATALOG.filter((m) => m.cat === 'chat' || m.cat === 'reasoning'),
    []
  );

  // ===== 当前 LLM 模型是否在目录中 =====
  const currentLlmModel = config?.llm_model || '';
  const currentLlmInCatalog = selectableModels.some((m) => m.id === currentLlmModel);

  // ===== 渲染 =====

  return (
    <div className="mx-auto max-w-4xl pt-6 px-8 pb-8">
      {/* 页面标题 */}
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-500">
          <CpuIcon size={20} />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">模型中心</h1>
          <p className="text-sm text-text-secondary">
            管理模型提供商、查看模型目录、配置各阶段模型分配
          </p>
        </div>
      </div>

      {/* ===== 1. Provider 列表卡片 ===== */}
      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ServerIcon size={16} />
            提供商与模型配置
          </CardTitle>
          <CardDescription>当前生效的 LLM、Embedding 和 Rerank 模型配置</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {configLoading ? (
            <div className="flex items-center gap-2 text-sm text-text-tertiary">
              <SpinnerIcon size={14} />
              加载配置中...
            </div>
          ) : configError ? (
            <ErrorInline err={configError} endpoint="/api/config/effective" />
          ) : config ? (
            <>
              {/* LLM 配置 */}
              <ProviderRow
                icon={<CpuIcon size={16} />}
                label="LLM 模型"
                provider={inferProviderFromUrl(config.llm_base_url || '', config.llm_model || '')}
                baseUrl={config.llm_base_url || ''}
                apiKeyConfigured={config.llm_api_key === 'configured'}
                currentModel={config.llm_model || ''}
              />

              {/* Embedding 配置 */}
              <ProviderRow
                icon={<DatabaseIcon size={16} />}
                label="Embedding 模型"
                provider={inferProviderFromUrl(config.embed_base_url || '', config.embed_model || '')}
                baseUrl={config.embed_base_url || '本地'}
                apiKeyConfigured={config.embed_api_key === 'configured'}
                currentModel={config.embed_model || ''}
              />

              {/* Rerank 配置 */}
              {config.rerank_model && (
                <ProviderRow
                  icon={<DatabaseIcon size={16} />}
                  label="Rerank 模型"
                  provider={inferProviderFromUrl(config.rerank_base_url || '', config.rerank_model || '')}
                  baseUrl={config.rerank_base_url || '本地'}
                  apiKeyConfigured={config.rerank_api_key === 'configured'}
                  currentModel={config.rerank_model}
                />
              )}

              {/* 默认温度 */}
              {config.default_temperature !== undefined && (
                <div className="flex items-center justify-between rounded-md border border-border-soft bg-bg-tertiary px-3 py-2">
                  <span className="text-sm text-text-secondary">默认温度</span>
                  <Badge variant="secondary">{String(config.default_temperature)}</Badge>
                </div>
              )}
            </>
          ) : null}

          {/* API Key 列表 */}
          <div className="pt-2">
            <div className="mb-2 text-sm font-medium text-text-primary">已配置的 API Key</div>
            {keysLoading ? (
              <div className="flex items-center gap-2 text-sm text-text-tertiary">
                <SpinnerIcon size={14} />
                加载中...
              </div>
            ) : keysError ? (
              <div className="text-xs text-text-tertiary">无法加载 API Key 列表</div>
            ) : keysData?.items?.length ? (
              <div className="space-y-2">
                {keysData.items.map((key) => (
                  <div
                    key={key.id}
                    className="flex items-center justify-between rounded-md border border-border-soft bg-bg-primary px-3 py-2"
                  >
                    <div className="flex items-center gap-3">
                      <div>
                        <div className="text-sm font-medium text-text-primary">
                          {getProviderLabel(key.provider)}
                          {key.is_default && (
                            <Badge variant="default" className="ml-2">
                              默认
                            </Badge>
                          )}
                        </div>
                        <div className="text-xs text-text-tertiary">
                          {key.base_url || '无 Base URL'} · {key.key_masked}
                        </div>
                      </div>
                    </div>
                    <Badge variant="success">已配置</Badge>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-border-default bg-bg-tertiary px-3 py-4 text-center text-sm text-text-tertiary">
                暂未配置任何 API Key
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ===== 2. 模型目录卡片 ===== */}
      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DatabaseIcon size={16} />
            模型目录
          </CardTitle>
          <CardDescription>可选模型列表，包含对话、推理和向量模型</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* 搜索栏 */}
          <div className="relative">
            <SearchIcon
              size={14}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary"
            />
            <Input
              placeholder="搜索模型名称或 ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>

          {/* 分类筛选 */}
          <div className="flex flex-wrap gap-2">
            {FILTER_CHIPS.map((chip) => (
              <button
                key={chip.value}
                type="button"
                onClick={() => setFilterChip(chip.value)}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition-all duration-(--duration-hover) ease-(--ease-standard) ${
                  filterChip === chip.value
                    ? 'border-brand-500 bg-brand-500/5 text-brand-600'
                    : 'border-border-default bg-bg-primary text-text-secondary hover:bg-bg-tertiary'
                }`}
              >
                {chip.label}
              </button>
            ))}
          </div>

          {/* 模型表格 */}
          <div className="overflow-hidden rounded-md border border-border-default">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-default bg-bg-tertiary text-left">
                  <th className="px-3 py-2 font-medium text-text-secondary">模型名称</th>
                  <th className="px-3 py-2 font-medium text-text-secondary">提供商</th>
                  <th className="px-3 py-2 font-medium text-text-secondary">类别</th>
                  <th className="px-3 py-2 font-medium text-text-secondary">推荐</th>
                  <th className="px-3 py-2 font-medium text-text-secondary">当前使用</th>
                </tr>
              </thead>
              <tbody>
                {filteredModels.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-text-tertiary">
                      未找到匹配的模型
                    </td>
                  </tr>
                ) : (
                  filteredModels.map((model) => {
                    const isCurrent =
                      model.id === currentLlmModel ||
                      model.id === config?.embed_model;
                    return (
                      <tr
                        key={model.id}
                        className="border-b border-border-soft transition-colors last:border-0 hover:bg-bg-tertiary"
                      >
                        <td className="px-3 py-2">
                          <div className="font-medium text-text-primary">{model.name}</div>
                          <div className="text-xs text-text-tertiary">{model.id}</div>
                        </td>
                        <td className="px-3 py-2 text-text-secondary">
                          {getProviderLabel(model.provider)}
                        </td>
                        <td className="px-3 py-2">
                          <Badge variant="secondary">{CATEGORY_LABELS[model.cat]}</Badge>
                        </td>
                        <td className="px-3 py-2">
                          {model.recommended ? (
                            <Badge variant="success">推荐</Badge>
                          ) : (
                            <span className="text-text-tertiary">-</span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {isCurrent ? (
                            <span className="flex items-center gap-1 text-brand-600">
                              <CheckIcon size={12} />
                              使用中
                            </span>
                          ) : (
                            <span className="text-text-tertiary">-</span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* ===== 3. 阶段模型分配卡片（仅管理员） ===== */}
      {isAdmin && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CpuIcon size={16} />
              阶段模型分配
            </CardTitle>
            <CardDescription>
              为会议流水线的各阶段指定模型。未指定时使用全局默认模型。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {sysConfigLoading ? (
              <div className="flex items-center gap-2 text-sm text-text-tertiary">
                <SpinnerIcon size={14} />
                加载系统配置中...
              </div>
            ) : (
              <>
                <div className="space-y-3">
                  {STAGES.map((stage) => (
                    <div
                      key={stage.key}
                      className="flex flex-col gap-2 rounded-md border border-border-soft bg-bg-primary p-3 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-brand-500/10 text-xs font-semibold text-brand-600">
                          {stage.label.charAt(0)}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <Label className="text-sm font-medium">{stage.label}</Label>
                            <Badge variant="outline" className="text-[10px]">
                              {stage.defaultTemp}
                            </Badge>
                          </div>
                          <div className="text-xs text-text-tertiary">{stage.description}</div>
                        </div>
                      </div>
                      <div className="sm:w-64">
                        <Select
                          value={stageModels[stage.key] || '__default__'}
                          onValueChange={(v) =>
                            handleStageModelChange(stage.key, v === '__default__' ? '' : v)
                          }
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="使用全局默认" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__default__">使用全局默认</SelectItem>
                            {selectableModels.map((model) => (
                              <SelectItem key={model.id} value={model.id}>
                                {model.name}
                                {model.recommended ? ' (推荐)' : ''}
                              </SelectItem>
                            ))}
                            {/* 如果当前模型不在目录中，额外显示 */}
                            {currentLlmModel &&
                              !currentLlmInCatalog &&
                              !selectableModels.some((m) => m.id === currentLlmModel) && (
                                <SelectItem value={currentLlmModel}>
                                  {currentLlmModel} (当前)
                                </SelectItem>
                              )}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex items-center justify-between pt-2">
                  <div className="text-xs text-text-tertiary">
                    配置键：stage_model_{'{stage}'}，保存后立即生效
                  </div>
                  <Button
                    onClick={handleSaveStageModels}
                    disabled={saveStageModels.isPending || !stageModelsDirty}
                  >
                    {saveStageModels.isPending && <SpinnerIcon size={14} />}
                    保存配置
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ===== 子组件：Provider 行 =====

function ProviderRow({
  icon,
  label,
  provider,
  baseUrl,
  apiKeyConfigured,
  currentModel,
}: {
  icon: React.ReactNode;
  label: string;
  provider: string;
  baseUrl: string;
  apiKeyConfigured: boolean;
  currentModel: string;
}) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border-soft bg-bg-primary px-3 py-2">
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-bg-tertiary text-text-secondary">
          {icon}
        </div>
        <div>
          <div className="text-sm font-medium text-text-primary">{label}</div>
          <div className="text-xs text-text-tertiary">
            {getProviderLabel(provider)} · {baseUrl}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {currentModel && (
          <div className="text-right">
            <div className="text-sm text-text-primary">{currentModel}</div>
          </div>
        )}
        {apiKeyConfigured ? (
          <Badge variant="success">已配置</Badge>
        ) : (
          <Badge variant="destructive">未配置</Badge>
        )}
      </div>
    </div>
  );
}

// ===== 子组件：错误内联显示 =====

function ErrorInline({ err, endpoint }: { err: unknown; endpoint: string }) {
  const info = getErrorDisplay(err, endpoint);
  return (
    <div className="flex items-center gap-2 rounded-md border border-danger/20 bg-danger/5 px-3 py-2 text-sm">
      <AlertCircleIcon size={14} className="text-danger" />
      <div>
        <div className="font-medium text-danger">{info.title}</div>
        <div className="text-xs text-text-tertiary">{info.hint}</div>
      </div>
    </div>
  );
}

// ===== 工具函数：从 base_url 推断 provider =====

function inferProviderFromUrl(baseUrl: string, model: string): string {
  // 先从 model id 推断
  if (model.startsWith('deepseek-ai/') || model.startsWith('Qwen/') || model.startsWith('BAAI/')) {
    if (model.startsWith('BAAI/')) return 'local';
    return 'siliconflow';
  }
  if (model.startsWith('deepseek-')) return 'deepseek';
  if (model.startsWith('qwen-')) return 'qwen';
  if (model.startsWith('gpt-')) return 'openai';
  if (model.startsWith('doubao-')) return 'doubao';
  if (model.startsWith('text-embedding-')) return 'qwen';

  // 从 base_url 推断
  const url = baseUrl.toLowerCase();
  if (url.includes('deepseek.com')) return 'deepseek';
  if (url.includes('siliconflow')) return 'siliconflow';
  if (url.includes('volces.com') || url.includes('ark.cn-beijing')) return 'doubao';
  if (url.includes('dashscope') || url.includes('aliyuncs')) return 'qwen';
  if (url.includes('openai.com')) return 'openai';
  if (!url || url === '本地') return 'local';
  return 'custom';
}
