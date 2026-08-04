import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { extractArray } from '@/lib/extract';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { ShieldIcon, UsersIcon, BuildingIcon, SettingsIcon, PlusIcon, TrashIcon, EditIcon, CheckIcon, XIcon, SpinnerIcon } from '@/components/ui/svg-icons';
import { Key as KeyIcon, Star as StarIcon } from 'lucide-react';
import { useAuthStore } from '@/stores/auth-slice';
import { isDemoMode } from '@/lib/mock-data';
import { ApiError } from '@/lib/api';

interface AdminUser { id: string; username: string; display_name: string; email: string; role: string; tenant_id: string; tenant_name: string; status: 'active' | 'disabled'; created_at: string; last_login?: string; }
interface AdminTenant { id: string; name: string; slug: string; member_count: number; meeting_count: number; status: 'active' | 'suspended'; plan: 'free' | 'pro' | 'enterprise'; created_at: string; }
interface SystemConfig { llm_provider: string; llm_model: string; llm_base_url: string; llm_api_key_configured: boolean; embed_provider: string; embed_model: string; embed_base_url: string; embed_api_key_configured: boolean; rerank_provider: string; rerank_model: string; rerank_base_url: string; rerank_api_key_configured: boolean; vector_db_provider: string; vector_db_url: string; vector_db_collection: string; max_agents: number; max_meeting_duration: number; enable_public_registration: boolean; default_temperature: number; stage_model_clarify: string; stage_model_intra_team: string; stage_model_cross_team: string; stage_model_evidence_check: string; stage_model_arbitrate: string; stage_model_produce: string; }
type ModelCapability = 'llm' | 'embedding' | 'reranker';
interface ProviderCatalogItem { value: string; label: string; baseUrl: string; capabilities: ModelCapability[]; models: Partial<Record<ModelCapability, { value: string; label: string }[]>>; needsKey: boolean; }
interface TeamItem { id: string | number; name: string; slug: string; member_count?: number; meeting_count?: number; status?: string; plan?: string; created_at?: string; }
interface MemberItem { user_id: string | number; username: string; display_name: string; email: string; is_active?: boolean; role: string; is_banned?: boolean; joined_at?: string; created_at?: string; }
interface ApiKeyItem { id: string | number; provider: string; name: string; key_masked: string; base_url: string; is_default: boolean; scope: string; created_at?: string; }

/** 统一厂商目录——每个厂商声明其能力和可用模型 */
const PROVIDER_CATALOG: ProviderCatalogItem[] = [
  { value: 'siliconflow', label: '硅基流动 (SiliconFlow)', baseUrl: 'https://api.siliconflow.cn/v1', needsKey: true, capabilities: ['llm', 'embedding', 'reranker'], models: {
    llm: [{ value: 'deepseek-ai/DeepSeek-V3.2', label: 'DeepSeek V3.2' }, { value: 'deepseek-ai/DeepSeek-V4-Flash', label: 'DeepSeek V4 Flash' }, { value: 'Qwen/Qwen2.5-72B-Instruct', label: 'Qwen2.5 72B' }],
    embedding: [{ value: 'BAAI/bge-m3', label: 'BAAI/bge-m3 (推荐)' }, { value: 'BAAI/bge-large-zh-v1.5', label: 'BAAI/bge-large-zh-v1.5' }],
    reranker: [{ value: 'BAAI/bge-reranker-v2-m3', label: 'BAAI/bge-reranker-v2-m3' }],
  } },
  { value: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com', needsKey: true, capabilities: ['llm'], models: {
    llm: [{ value: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash' }, { value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro' }],
  } },
  { value: 'doubao', label: '豆包 (火山引擎)', baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', needsKey: true, capabilities: ['llm'], models: {
    llm: [{ value: 'doubao-seed-2-0-code', label: 'Doubao Seed 2.0 Code' }],
  } },
  { value: 'qwen', label: '通义千问 (DashScope)', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', needsKey: true, capabilities: ['llm', 'embedding'], models: {
    llm: [{ value: 'qwen-plus', label: 'Qwen Plus' }, { value: 'qwen-max', label: 'Qwen Max' }],
    embedding: [{ value: 'text-embedding-v3', label: 'text-embedding-v3' }],
  } },
  { value: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', needsKey: true, capabilities: ['llm', 'embedding'], models: {
    llm: [{ value: 'gpt-4o', label: 'GPT-4o' }, { value: 'gpt-4o-mini', label: 'GPT-4o mini' }],
    embedding: [{ value: 'text-embedding-3-large', label: 'text-embedding-3-large' }, { value: 'text-embedding-3-small', label: 'text-embedding-3-small' }],
  } },
  { value: 'ollama', label: 'Ollama (本地)', baseUrl: 'http://localhost:11434/v1', needsKey: false, capabilities: ['llm', 'embedding'], models: {} },
  { value: 'custom', label: '自定义 (OpenAI 兼容)', baseUrl: '', needsKey: true, capabilities: ['llm', 'embedding', 'reranker'], models: {} },
];
const VDB_PROVIDERS = [{ value: 'qdrant', label: 'Qdrant' }, { value: 'memory', label: '内存模式（仅测试）' }];
const CAP_LABELS: Record<ModelCapability, string> = { llm: 'LLM', embedding: 'Embedding', reranker: 'Reranker' };
const STAGE_DEFS: { key: keyof SystemConfig; label: string; desc: string }[] = [
  { key: 'stage_model_clarify', label: '澄清', desc: '议题理解与分解' },
  { key: 'stage_model_intra_team', label: '组内讨论', desc: '角色独立思考' },
  { key: 'stage_model_cross_team', label: '跨组协作', desc: '角色间借调与碰撞' },
  { key: 'stage_model_evidence_check', label: '证据核查', desc: '事实校验' },
  { key: 'stage_model_arbitrate', label: '仲裁', desc: '分歧裁决' },
  { key: 'stage_model_produce', label: '产出', desc: '最终报告生成' },
];
// 系统配置中可通过 PUT /api/config/system/{key} 保存的键（对齐后端 SYSTEM_OVERRIDABLE_KEYS）
const SAVABLE_CONFIG_KEYS: (keyof SystemConfig)[] = ['llm_model', 'llm_base_url', 'llm_provider', 'embed_model', 'embed_base_url', 'embed_provider', 'rerank_model', 'rerank_base_url', 'rerank_provider', 'default_temperature', 'enable_public_registration', 'max_agents', 'max_meeting_duration', 'vector_db_provider', 'vector_db_url', 'vector_db_collection', 'stage_model_clarify', 'stage_model_intra_team', 'stage_model_cross_team', 'stage_model_evidence_check', 'stage_model_arbitrate', 'stage_model_produce'];

function getErrorDisplay(err: unknown, endpoint: string): { title: string; hint: string } {
  if (err instanceof ApiError) {
    if (err.status === 401) return { title: '登录已过期', hint: '正在跳转到登录页...' };
    if (err.status === 403) return { title: '权限不足', hint: '仅系统管理员可访问' };
    if (err.status === 404) return { title: '接口暂未实现', hint: `后端尚未提供 ${endpoint} 端点` };
    if (err.status >= 500) return { title: '服务器错误', hint: `服务暂不可用（${err.status}）` };
    return { title: '请求失败', hint: err.message || `HTTP ${err.status}` };
  }
  if (err instanceof TypeError) return { title: '无法连接服务器', hint: '请确认后端服务已启动' };
  return { title: '加载失败', hint: endpoint ? `后端尚未提供 ${endpoint} 端点` : '未知错误' };
}
const findProvider = (v: string) => PROVIDER_CATALOG.find((p) => p.value === v);
const providersWithCapability = (cap: ModelCapability) => PROVIDER_CATALOG.filter((p) => p.capabilities.includes(cap));
const inferProvider = (baseUrl: string) => { if (!baseUrl) return ''; return PROVIDER_CATALOG.find((p) => p.baseUrl && baseUrl.startsWith(p.baseUrl))?.value || ''; };

/** 将 GET /api/config/system 的响应（可能为 {settings:{...}} 包装或裸 dict）归一化为 SystemConfig。 */
function normalizeConfig(raw: unknown): SystemConfig {
  const obj = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const s = obj.settings && typeof obj.settings === 'object' ? (obj.settings as Record<string, unknown>) : obj;
  const getStr = (k: string) => (typeof s[k] === 'string' ? (s[k] as string) : s[k] != null ? String(s[k]) : '');
  const getBool = (k: string) => s[k] === true || s[k] === 'true' || s[k] === 1;
  const getNum = (k: string, d: number) => { if (s[k] == null || s[k] === '') return d; const v = Number(s[k]); return Number.isFinite(v) ? v : d; };
  const llmKey = getStr('llm_api_key');
  const embKey = getStr('embed_api_key');
  const rrKey = getStr('rerank_api_key');
  const llmBaseUrl = getStr('llm_base_url');
  const embBaseUrl = getStr('embed_base_url');
  const rrBaseUrl = getStr('rerank_base_url');
  return {
    llm_provider: getStr('llm_provider') || inferProvider(llmBaseUrl),
    llm_model: getStr('llm_model'),
    llm_base_url: llmBaseUrl,
    llm_api_key_configured: getBool('llm_api_key_configured') || (!!llmKey && llmKey !== ''),
    embed_provider: getStr('embed_provider') || inferProvider(embBaseUrl) || 'local',
    embed_model: getStr('embed_model') || 'BAAI/bge-m3',
    embed_base_url: embBaseUrl,
    embed_api_key_configured: getBool('embed_api_key_configured') || (!!embKey && embKey !== ''),
    rerank_provider: getStr('rerank_provider') || inferProvider(rrBaseUrl) || getStr('embed_provider') || '',
    rerank_model: getStr('rerank_model') || 'BAAI/bge-reranker-v2-m3',
    rerank_base_url: rrBaseUrl,
    rerank_api_key_configured: getBool('rerank_api_key_configured') || (!!rrKey && rrKey !== ''),
    vector_db_provider: getStr('vector_db_provider') || 'qdrant',
    vector_db_url: getStr('vector_db_url') || 'http://qdrant:6333',
    vector_db_collection: getStr('vector_db_collection') || 'conclave_chunks',
    max_agents: getNum('max_agents', 8),
    max_meeting_duration: getNum('max_meeting_duration', 120),
    enable_public_registration: getBool('enable_public_registration'),
    default_temperature: getNum('default_temperature', 0.1),
    stage_model_clarify: getStr('stage_model_clarify'),
    stage_model_intra_team: getStr('stage_model_intra_team'),
    stage_model_cross_team: getStr('stage_model_cross_team'),
    stage_model_evidence_check: getStr('stage_model_evidence_check'),
    stage_model_arbitrate: getStr('stage_model_arbitrate'),
    stage_model_produce: getStr('stage_model_produce'),
  };
}

function mapMemberToUser(m: MemberItem, t: TeamItem): AdminUser {
  return {
    id: String(m.user_id),
    username: m.username,
    display_name: m.display_name || m.username,
    email: m.email || '',
    role: m.role,
    tenant_id: String(t.id),
    tenant_name: t.name,
    status: m.is_banned ? 'disabled' : 'active',
    created_at: m.created_at || m.joined_at || '',
    last_login: undefined,
  };
}

const MOCK_USERS: AdminUser[] = [{ id: 'u1', username: 'admin', display_name: '系统管理员', email: 'admin@conclave.local', role: 'owner', tenant_id: 't1', tenant_name: '默认组织', status: 'active', created_at: '2026-01-01T00:00:00Z', last_login: new Date().toISOString() }];
const MOCK_TENANTS: AdminTenant[] = [{ id: 't1', name: '默认组织', slug: 'default', member_count: 1, meeting_count: 0, status: 'active', plan: 'enterprise', created_at: '2026-01-01T00:00:00Z' }];
const MOCK_CONFIG: SystemConfig = { llm_provider: 'siliconflow', llm_model: 'deepseek-ai/DeepSeek-V3.2', llm_base_url: 'https://api.siliconflow.cn/v1', llm_api_key_configured: true, embed_provider: 'siliconflow', embed_model: 'BAAI/bge-m3', embed_base_url: 'https://api.siliconflow.cn/v1', embed_api_key_configured: true, rerank_provider: 'siliconflow', rerank_model: 'BAAI/bge-reranker-v2-m3', rerank_base_url: 'https://api.siliconflow.cn/v1', rerank_api_key_configured: true, vector_db_provider: 'qdrant', vector_db_url: 'http://qdrant:6333', vector_db_collection: 'conclave_chunks', max_agents: 8, max_meeting_duration: 120, enable_public_registration: false, default_temperature: 0.1, stage_model_clarify: '', stage_model_intra_team: '', stage_model_cross_team: '', stage_model_evidence_check: '', stage_model_arbitrate: '', stage_model_produce: '' };
const MOCK_KEYS: ApiKeyItem[] = [
  { id: 'k1', provider: 'siliconflow', name: 'default', key_masked: 'sk-****1234', base_url: 'https://api.siliconflow.cn/v1', is_default: true, scope: 'system', created_at: new Date().toISOString() },
  { id: 'k2', provider: 'deepseek', name: 'default', key_masked: 'sk-****5678', base_url: 'https://api.deepseek.com', is_default: false, scope: 'team', created_at: new Date().toISOString() },
];
const ROLE_BADGE: Record<string, { className: string; label: string }> = { owner: { className: 'bg-accent-purple/15 text-accent-purple', label: '所有者' }, maintainer: { className: 'bg-brand-soft text-brand-600', label: '管理员' }, admin: { className: 'bg-brand-soft text-brand-600', label: '管理员' }, member: { className: 'bg-bg-tertiary text-text-secondary', label: '成员' }, reporter: { className: 'bg-bg-tertiary text-text-secondary', label: '访客' } };
const PLAN_BADGE: Record<string, { className: string; label: string }> = { free: { className: 'bg-bg-tertiary text-text-secondary', label: '免费版' }, pro: { className: 'bg-brand-soft text-brand-600', label: '专业版' }, enterprise: { className: 'bg-accent-purple/15 text-accent-purple', label: '企业版' } };
const SCOPE_BADGE: Record<string, { className: string; label: string }> = { system: { className: 'bg-accent-purple/15 text-accent-purple', label: '系统' }, team: { className: 'bg-brand-soft text-brand-600', label: '团队' }, personal: { className: 'bg-bg-tertiary text-text-secondary', label: '个人' } };

export default function AdminPage() {
  const { toast } = useToast();
  const currentUser = useAuthStore((s) => s.user);
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = React.useState('users');
  const [userDialogOpen, setUserDialogOpen] = React.useState(false);
  const [editingUser, setEditingUser] = React.useState<AdminUser | null>(null);
  const [userForm, setUserForm] = React.useState({ username: '', display_name: '', password: '', role: 'member', tenant_id: '' });
  const [tenantDialogOpen, setTenantDialogOpen] = React.useState(false);
  const [editingTenant, setEditingTenant] = React.useState<AdminTenant | null>(null);
  const [tenantForm, setTenantForm] = React.useState({ name: '', slug: '', plan: 'free' as AdminTenant['plan'] });
  const [config, setConfig] = React.useState<SystemConfig | null>(null);
  const configSnapshot = React.useRef<SystemConfig | null>(null);
  const [delUserTarget, setDelUserTarget] = React.useState<AdminUser | null>(null);
  const [keyDialogOpen, setKeyDialogOpen] = React.useState(false);
  const [editingKey, setEditingKey] = React.useState<ApiKeyItem | null>(null);
  const [keyForm, setKeyForm] = React.useState({ provider: PROVIDER_CATALOG[0].value, name: 'default', api_key: '', base_url: '', is_default: false, scope: 'system' });
  const [showKeyValue, setShowKeyValue] = React.useState(false);
  const [delKeyTarget, setDelKeyTarget] = React.useState<ApiKeyItem | null>(null);

  // 系统配置：GET /api/config/system
  const { data: configData, error: cfgErr, isLoading: cfgLoad } = useQuery({ queryKey: ['admin', 'config'], queryFn: async () => isDemoMode() ? MOCK_CONFIG : normalizeConfig(await api.get<unknown>('/api/config/system')), retry: false });
  React.useEffect(() => { if (configData) { setConfig(configData); configSnapshot.current = configData; } }, [configData]);

  // 组织列表：GET /api/teams
  const { data: tenants, isLoading: tenLoad, error: tenErr } = useQuery({ queryKey: ['admin', 'tenants'], queryFn: async () => isDemoMode() ? MOCK_TENANTS : extractArray<AdminTenant>(await api.get<{ items: AdminTenant[] }>('/api/teams'), ['items']), retry: false });

  // 用户列表：先取所有 Team，再聚合每个 Team 的成员（含封禁）
  const { data: users, isLoading: usersLoad, error: usersErr } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: async (): Promise<AdminUser[]> => {
      if (isDemoMode()) return MOCK_USERS;
      const tres = await api.get<{ items: TeamItem[] }>('/api/teams');
      const teams = extractArray<TeamItem>(tres, ['items']);
      if (!teams.length) return [] as AdminUser[];
      const results = await Promise.all(
        teams.map((t) => api.get<{ items: MemberItem[] }>(`/api/teams/${t.id}/members?include_banned=true&page_size=100`)
          .then((r) => ({ t, members: extractArray<MemberItem>(r, ['items']) }))
          .catch(() => ({ t, members: [] as MemberItem[] })))
      );
      const all: AdminUser[] = [];
      for (const { t, members } of results) for (const m of members) all.push(mapMemberToUser(m, t));
      return all;
    },
    retry: false,
  });

  // API Key 列表：GET /api/keys?scope=all
  const { data: apiKeys, isLoading: keysLoad, error: keysErr } = useQuery({ queryKey: ['admin', 'keys'], queryFn: async () => isDemoMode() ? MOCK_KEYS : extractArray<ApiKeyItem>(await api.get<{ items: ApiKeyItem[] }>('/api/keys?scope=all'), ['items']), retry: false });

  // 封禁/解封：POST /api/teams/{tid}/members/{uid}/(un)ban
  const toggleUser = useMutation({
    mutationFn: async (u: AdminUser) => { if (!isDemoMode()) { if (u.status === 'active') await api.post(`/api/teams/${u.tenant_id}/members/${u.id}/ban`); else await api.post(`/api/teams/${u.tenant_id}/members/${u.id}/unban`); } },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); toast({ title: '操作成功' }); },
    onError: (e) => toast({ title: getErrorDisplay(e, '/api/teams/:tid/members/:uid/ban').title, variant: 'destructive' }),
  });
  // 移除成员：DELETE /api/teams/{tid}/members/{uid}
  const delUser = useMutation({
    mutationFn: async (u: AdminUser) => { if (!isDemoMode()) await api.delete(`/api/teams/${u.tenant_id}/members/${u.id}`); },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); toast({ title: '用户已移除' }); },
    onError: (e) => toast({ title: getErrorDisplay(e, '/api/teams/:tid/members/:uid').title, variant: 'destructive' }),
  });
  const saveUser = useMutation({
    mutationFn: async () => {
      if (!userForm.username) throw new Error('请填写用户名');
      if (!editingUser && !userForm.tenant_id) throw new Error('请选择组织');
      if (isDemoMode()) return;
      if (editingUser) {
        await api.patch(`/api/teams/${editingUser.tenant_id}/members/${editingUser.id}`, { role: userForm.role });
      } else {
        await api.post(`/api/teams/${userForm.tenant_id}/members`, { username: userForm.username, display_name: userForm.display_name, password: userForm.password, role: userForm.role });
      }
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'users'] }); toast({ title: editingUser ? '用户已更新' : '成员已添加' }); setUserDialogOpen(false); setEditingUser(null); setUserForm({ username: '', display_name: '', password: '', role: 'member', tenant_id: '' }); },
    onError: (e: unknown) => { const info = getErrorDisplay(e, editingUser ? 'PATCH /api/teams/:tid/members/:uid' : 'POST /api/teams/:tid/members'); toast({ title: info.title, description: e instanceof Error ? e.message : info.hint, variant: 'destructive' }); },
  });
  const saveTenant = useMutation({
    mutationFn: async () => {
      if (!tenantForm.name || !tenantForm.slug) throw new Error('请填写组织名称和标识');
      if (isDemoMode()) return;
      if (editingTenant) await api.patch(`/api/teams/${editingTenant.id}`, { name: tenantForm.name, settings: { plan: tenantForm.plan } });
      else await api.post('/api/teams', { name: tenantForm.name, slug: tenantForm.slug, plan: tenantForm.plan });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'tenants'] }); toast({ title: editingTenant ? '组织已更新' : '组织已创建' }); setTenantDialogOpen(false); setEditingTenant(null); setTenantForm({ name: '', slug: '', plan: 'free' }); },
    onError: (e: unknown) => { const info = getErrorDisplay(e, editingTenant ? 'PATCH /api/teams/:id' : 'POST /api/teams'); toast({ title: info.title, description: e instanceof Error ? e.message : info.hint, variant: 'destructive' }); },
  });
  const saveCfg = useMutation({
    mutationFn: async () => {
      if (!config || isDemoMode()) return;
      const snap = configSnapshot.current;
      const changes: { key: string; value: string }[] = [];
      for (const f of SAVABLE_CONFIG_KEYS) { if (String(config[f] ?? '') !== String(snap?.[f] ?? '')) changes.push({ key: f, value: String(config[f] ?? '') }); }
      if (!changes.length) return;
      const results = await Promise.allSettled(changes.map((c) => api.put(`/api/config/system/${encodeURIComponent(c.key)}`, { value: c.value })));
      const failed = results.filter((r) => r.status === 'rejected');
      if (failed.length) { const fr = failed[0]; const err = fr.status === 'rejected' ? fr.reason : null; throw err instanceof Error ? err : new Error(`${failed.length} 项保存失败`); }
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'config'] }); toast({ title: '配置已保存', description: '部分设置需重启服务生效' }); },
    onError: (e: unknown) => { const info = getErrorDisplay(e, 'PUT /api/config/system/{key}'); toast({ title: info.title, description: info.hint, variant: 'destructive' }); },
  });
  // 保存/设为默认 API Key：POST /api/keys
  const saveKey = useMutation({
    mutationFn: async () => {
      if (!keyForm.provider || !keyForm.api_key) throw new Error('请填写 Provider 和 API Key');
      if (isDemoMode()) return;
      await api.post('/api/keys', { provider: keyForm.provider, name: keyForm.name || 'default', api_key: keyForm.api_key, base_url: keyForm.base_url, is_default: keyForm.is_default, scope: keyForm.scope });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'keys'] }); qc.invalidateQueries({ queryKey: ['admin', 'config'] }); toast({ title: editingKey ? 'Key 已更新' : 'Key 已保存' }); setKeyDialogOpen(false); setEditingKey(null); setKeyForm({ provider: PROVIDER_CATALOG[0].value, name: 'default', api_key: '', base_url: '', is_default: false, scope: 'system' }); setShowKeyValue(false); },
    onError: (e: unknown) => { const info = getErrorDisplay(e, 'POST /api/keys'); toast({ title: info.title, description: e instanceof Error ? e.message : info.hint, variant: 'destructive' }); },
  });
  // 一键切换默认 Key（无需重新输入 Key）
  const setDefaultKey = useMutation({
    mutationFn: async (k: ApiKeyItem) => {
      if (isDemoMode()) return;
      await api.post('/api/keys', { provider: k.provider, name: k.name, api_key: '', base_url: k.base_url || '', is_default: true, scope: k.scope });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'keys'] }); qc.invalidateQueries({ queryKey: ['admin', 'config'] }); toast({ title: '默认 Key 已切换', description: '已同步到系统配置，LLM 客户端将使用新 Key' }); },
    onError: (e: unknown) => { const info = getErrorDisplay(e, 'POST /api/keys'); toast({ title: info.title, description: e instanceof Error ? e.message : info.hint, variant: 'destructive' }); },
  });
  // 删除 API Key：DELETE /api/keys/{provider}/{name}?scope=
  const delKey = useMutation({
    mutationFn: async (k: ApiKeyItem) => { if (!isDemoMode()) await api.delete(`/api/keys/${encodeURIComponent(k.provider)}/${encodeURIComponent(k.name)}?scope=${encodeURIComponent(k.scope)}`); },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'keys'] }); toast({ title: 'Key 已删除' }); },
    onError: (e: unknown) => { const info = getErrorDisplay(e, 'DELETE /api/keys/{provider}/{name}'); toast({ title: info.title, description: info.hint, variant: 'destructive' }); },
  });

  const confirmDelUser = () => { if (delUserTarget) { delUser.mutate(delUserTarget); setDelUserTarget(null); } };
  const confirmDelKey = () => { if (delKeyTarget) { delKey.mutate(delKeyTarget); setDelKeyTarget(null); } };
  const fmtDate = (d?: string) => d ? new Date(d).toLocaleDateString('zh-CN') : '从未登录';
  const openUserDlg = (u: AdminUser | null) => {
    if (u) { setEditingUser(u); setUserForm({ username: u.username, display_name: u.display_name, password: '', role: u.role, tenant_id: u.tenant_id }); }
    else { setEditingUser(null); const dt = Array.isArray(tenants) && tenants.length > 0 ? tenants[0].id : ''; setUserForm({ username: '', display_name: '', password: '', role: 'member', tenant_id: dt }); }
    setUserDialogOpen(true);
  };
  const openTenantDlg = (t: AdminTenant | null) => {
    if (t) { setEditingTenant(t); setTenantForm({ name: t.name, slug: t.slug, plan: t.plan }); }
    else { setEditingTenant(null); setTenantForm({ name: '', slug: '', plan: 'free' }); }
    setTenantDialogOpen(true);
  };
  const openAddKey = (provider?: string) => { setEditingKey(null); const p = provider || PROVIDER_CATALOG[0].value; const dp = findProvider(p); const existing = (apiKeys || []).filter((k) => k.provider === p); setKeyForm({ provider: p, name: 'default', api_key: '', base_url: dp?.baseUrl || '', is_default: existing.length === 0, scope: 'system' }); setShowKeyValue(false); setKeyDialogOpen(true); };
  const onSaveCfg = () => {
    if (isDemoMode()) { toast({ title: '演示模式', description: '配置不可修改' }); return; }
    if (!config) return;
    const snap = configSnapshot.current;
    const hasChanges = SAVABLE_CONFIG_KEYS.some((f) => String(config[f] ?? '') !== String(snap?.[f] ?? ''));
    if (!hasChanges) { toast({ title: '无变更', description: '没有需要保存的配置项' }); return; }
    saveCfg.mutate();
  };
  const onLlmProvider = (v: string) => { if (!config) return; const p = findProvider(v); const models = p?.models?.llm || []; setConfig({ ...config, llm_provider: v, llm_base_url: p?.baseUrl || config.llm_base_url, llm_model: models[0]?.value || '' }); };
  const onEmbProvider = (v: string) => { if (!config) return; const p = findProvider(v); const models = p?.models?.embedding || []; setConfig({ ...config, embed_provider: v, embed_base_url: p?.baseUrl || '', embed_model: models[0]?.value || 'BAAI/bge-m3' }); };
  const onRrProvider = (v: string) => { if (!config) return; const p = findProvider(v); const models = p?.models?.reranker || []; setConfig({ ...config, rerank_provider: v, rerank_base_url: p?.baseUrl || '', rerank_model: models[0]?.value || '' }); };
  const llmModels = findProvider(config?.llm_provider || '')?.models?.llm || [];
  const embModels = findProvider(config?.embed_provider || '')?.models?.embedding || [];
  const rrModels = findProvider(config?.rerank_provider || '')?.models?.reranker || [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex-shrink-0 border-b border-border-soft bg-bg-primary px-6 py-4">
        <div className="flex items-center gap-2"><ShieldIcon size={20} className="text-accent-purple" /><h2 className="text-lg font-semibold text-text-primary">系统管理</h2></div>
        <p className="mt-1 text-xs text-text-tertiary">管理用户、组织和系统配置</p>
      </div>
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-1 flex-col">
        <div className="flex-shrink-0 border-b border-border-soft bg-bg-primary px-6">
          <TabsList className="h-11 gap-0 bg-transparent p-0">
            <TabsTrigger value="users" className="h-11 gap-1.5 rounded-none border-b-2 border-transparent px-4 data-[state=active]:border-brand-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none"><UsersIcon size={14} /> 用户管理<Badge className="ml-1 bg-bg-tertiary px-1 py-0 text-[10px] text-text-tertiary">{users?.length ?? 0}</Badge></TabsTrigger>
            <TabsTrigger value="tenants" className="h-11 gap-1.5 rounded-none border-b-2 border-transparent px-4 data-[state=active]:border-brand-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none"><BuildingIcon size={14} /> 组织管理<Badge className="ml-1 bg-bg-tertiary px-1 py-0 text-[10px] text-text-tertiary">{tenants?.length ?? 0}</Badge></TabsTrigger>
            <TabsTrigger value="config" className="h-11 gap-1.5 rounded-none border-b-2 border-transparent px-4 data-[state=active]:border-brand-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none"><SettingsIcon size={14} /> 系统配置</TabsTrigger>
          </TabsList>
        </div>
        <ScrollArea className="flex-1">
          <TabsContent value="users" className="m-0 p-6">
            <div className="mb-4 flex justify-end"><Button size="sm" onClick={() => openUserDlg(null)}><PlusIcon size={14} /> 添加成员</Button></div>
            {usersLoad && !users ? <div className="flex items-center justify-center gap-2 py-12 text-xs text-text-tertiary"><SpinnerIcon size={16} className="animate-spin" /> 加载用户列表...</div>
              : usersErr ? <div className="flex flex-col items-center justify-center gap-3 py-12"><div className="text-xs text-danger">{getErrorDisplay(usersErr, '/api/teams 与 /api/teams/:tid/members').title}</div><div className="text-[10px] text-text-tertiary">{getErrorDisplay(usersErr, '/api/teams 与 /api/teams/:tid/members').hint}</div></div>
              : !users?.length ? <div className="flex items-center justify-center py-12 text-xs text-text-tertiary">暂无用户数据</div>
              : <Card><CardContent className="p-0">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-border-soft bg-bg-secondary text-text-tertiary">
                    <th className="px-4 py-3 text-left font-medium">用户</th><th className="px-4 py-3 text-left font-medium">邮箱</th><th className="px-4 py-3 text-left font-medium">角色</th><th className="px-4 py-3 text-left font-medium">所属组织</th><th className="px-4 py-3 text-left font-medium">状态</th><th className="px-4 py-3 text-left font-medium">最后登录</th><th className="px-4 py-3 text-right font-medium">操作</th>
                  </tr></thead>
                  <tbody>
                    {users.map((u: AdminUser) => {
                      const rb = ROLE_BADGE[u.role] || ROLE_BADGE.member;
                      return (
                        <tr key={`${u.tenant_id}-${u.id}`} className="border-b border-border-soft last:border-0 hover:bg-bg-secondary/50">
                          <td className="px-4 py-3"><div className="flex items-center gap-3"><div className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-soft text-[11px] font-semibold text-brand-600">{u.display_name.charAt(0)}</div><div><div className="font-medium text-text-primary">{u.display_name}</div><div className="text-text-tertiary">@{u.username}</div></div></div></td>
                          <td className="px-4 py-3 text-text-secondary">{u.email}</td>
                          <td className="px-4 py-3"><Badge className={`${rb.className} px-2 py-0.5 text-[11px]`}>{rb.label}</Badge></td>
                          <td className="px-4 py-3 text-text-secondary">{u.tenant_name}</td>
                          <td className="px-4 py-3">{u.status === 'active' ? <Badge className="gap-1 bg-success/15 px-2 py-0.5 text-[11px] text-success"><CheckIcon size={10} /> 正常</Badge> : <Badge className="gap-1 bg-danger/15 px-2 py-0.5 text-[11px] text-danger"><XIcon size={10} /> 已禁用</Badge>}</td>
                          <td className="px-4 py-3 text-text-tertiary">{fmtDate(u.last_login)}</td>
                          <td className="px-4 py-3 text-right"><div className="flex items-center justify-end gap-1">
                            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openUserDlg(u)} title="编辑角色"><EditIcon size={14} /></Button>
                            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => toggleUser.mutate(u)} title={u.status === 'active' ? '封禁' : '解封'}>{u.status === 'active' ? <XIcon size={14} className="text-danger" /> : <CheckIcon size={14} className="text-success" />}</Button>
                            {u.id !== currentUser?.id && <Button variant="ghost" size="icon" className="h-8 w-8 text-danger" onClick={() => setDelUserTarget(u)} title="移除"><TrashIcon size={14} /></Button>}
                          </div></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </CardContent></Card>}
          </TabsContent>

          <TabsContent value="tenants" className="m-0 p-6">
            <div className="mb-4 flex justify-end"><Button size="sm" onClick={() => openTenantDlg(null)}><PlusIcon size={14} /> 新建组织</Button></div>
            {tenLoad && !tenants ? <div className="flex items-center justify-center gap-2 py-12 text-xs text-text-tertiary"><SpinnerIcon size={16} className="animate-spin" /> 加载组织列表...</div>
              : tenErr ? <div className="flex flex-col items-center justify-center gap-3 py-12"><div className="text-xs text-danger">{getErrorDisplay(tenErr, '/api/teams').title}</div><div className="text-[10px] text-text-tertiary">{getErrorDisplay(tenErr, '/api/teams').hint}</div></div>
              : !tenants?.length ? <div className="flex items-center justify-center py-12 text-xs text-text-tertiary">暂无组织数据</div>
              : <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {tenants.map((t: AdminTenant) => {
                  const pb = PLAN_BADGE[t.plan] || PLAN_BADGE.free;
                  return (
                    <Card key={t.id}>
                      <CardHeader className="pb-3"><div className="flex items-start justify-between"><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-soft text-brand-600"><BuildingIcon size={18} /></div><div><CardTitle className="text-sm">{t.name}</CardTitle><CardDescription className="text-xs">{t.slug}</CardDescription></div></div><Badge className={`${pb.className} px-2 py-0.5 text-[11px]`}>{pb.label}</Badge></div></CardHeader>
                      <CardContent className="pt-0">
                        <div className="mb-4 grid grid-cols-2 gap-3 text-xs"><div><div className="text-text-tertiary">成员数</div><div className="flex items-center gap-1 font-medium text-text-primary"><UsersIcon size={12} />{t.member_count ?? 0}</div></div><div><div className="text-text-tertiary">会议数</div><div className="font-medium text-text-primary">{t.meeting_count ?? 0}</div></div><div><div className="text-text-tertiary">创建时间</div><div className="text-text-secondary">{fmtDate(t.created_at)}</div></div><div><div className="text-text-tertiary">状态</div><div className={(t.status || 'active') === 'active' ? 'text-success' : 'text-danger'}>{(t.status || 'active') === 'active' ? '正常' : '已暂停'}</div></div></div>
                        <Button variant="outline" size="sm" className="h-8 w-full text-xs" onClick={() => openTenantDlg(t)}><EditIcon size={12} /> 编辑</Button>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>}
          </TabsContent>

          <TabsContent value="config" className="m-0 p-6">
            {cfgLoad && !config ? <div className="flex items-center justify-center gap-2 py-12 text-xs text-text-tertiary"><SpinnerIcon size={16} className="animate-spin" /> 加载系统配置...</div>
              : cfgErr ? <div className="flex flex-col items-center justify-center gap-3 py-12"><div className="text-xs text-danger">{getErrorDisplay(cfgErr, '/api/config/system').title}</div><div className="text-[10px] text-text-tertiary">{getErrorDisplay(cfgErr, '/api/config/system').hint}</div></div>
              : !config ? <div className="flex items-center justify-center py-12 text-xs text-text-tertiary">暂无配置数据</div>
              : <div className="mx-auto max-w-3xl space-y-5">

                <Card>
                  <CardHeader><div className="flex items-center justify-between"><div><CardTitle className="text-base">厂商管理</CardTitle><CardDescription className="text-xs">配置各 AI 厂商的接入地址和 API Key。一个厂商可添加多个 Key，在各维度中按需选用。</CardDescription></div><Button size="sm" variant="outline" onClick={() => openAddKey()}><PlusIcon size={14} /> 添加 Key</Button></div></CardHeader>
                  <CardContent>
                    {keysLoad && !apiKeys ? <div className="flex items-center justify-center gap-2 py-8 text-xs text-text-tertiary"><SpinnerIcon size={16} className="animate-spin" /> 加载 API Key 列表...</div>
                      : keysErr ? <div className="flex flex-col items-center justify-center gap-2 py-8"><div className="text-xs text-danger">{getErrorDisplay(keysErr, '/api/keys').title}</div><div className="text-[10px] text-text-tertiary">{getErrorDisplay(keysErr, '/api/keys').hint}</div></div>
                      : !apiKeys?.length ? <div className="flex items-center justify-center py-8 text-xs text-text-tertiary">暂无 API Key，点击右上角"添加 Key"创建</div>
                      : <div className="overflow-x-auto"><table className="w-full text-sm">
                        <thead><tr className="border-b border-border-soft bg-bg-secondary text-text-tertiary">
                          <th className="px-3 py-2.5 text-left font-medium">厂商</th><th className="px-3 py-2.5 text-left font-medium">能力</th><th className="px-3 py-2.5 text-left font-medium">Key</th><th className="px-3 py-2.5 text-left font-medium">Scope</th><th className="px-3 py-2.5 text-left font-medium">Base URL</th><th className="px-3 py-2.5 text-right font-medium">操作</th>
                        </tr></thead>
                        <tbody>
                          {apiKeys.map((k: ApiKeyItem) => {
                            const sb = SCOPE_BADGE[k.scope] || SCOPE_BADGE.team;
                            const pcat = findProvider(k.provider);
                            return (
                              <tr key={`${k.provider}-${k.name}-${k.id}`} className="border-b border-border-soft last:border-0 hover:bg-bg-secondary/50">
                                <td className="px-3 py-2.5 font-medium text-text-primary">{pcat?.label || k.provider}</td>
                                <td className="px-3 py-2.5"><div className="flex flex-wrap gap-1">{(pcat?.capabilities || []).map((c) => <Badge key={c} className="bg-bg-tertiary px-1.5 py-0 text-[10px] text-text-secondary">{CAP_LABELS[c]}</Badge>)}</div></td>
                                <td className="px-3 py-2.5"><div className="flex items-center gap-2"><span className="font-mono text-xs text-text-secondary">{k.key_masked}</span>{k.is_default && <Badge className="bg-success/15 px-1.5 py-0 text-[10px] text-success">默认</Badge>}</div></td>
                                <td className="px-3 py-2.5"><Badge className={`${sb.className} px-2 py-0.5 text-[11px]`}>{sb.label}</Badge></td>
                                <td className="px-3 py-2.5 font-mono text-xs text-text-tertiary">{k.base_url || '-'}</td>
                                <td className="px-3 py-2.5 text-right"><div className="flex items-center justify-end gap-1">
                                  {!k.is_default && <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setDefaultKey.mutate(k)} title="设为默认" disabled={setDefaultKey.isPending}><StarIcon size={14} /></Button>}
                                  <Button variant="ghost" size="icon" className="h-8 w-8 text-danger" onClick={() => setDelKeyTarget(k)} title="删除"><TrashIcon size={14} /></Button>
                                </div></td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table></div>}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader><CardTitle className="text-base">模型配置</CardTitle><CardDescription className="text-xs">为每个使用维度选择厂商和模型。LLM 用于对话推理，Embedding 用于文本向量化，Reranker 用于检索重排序。</CardDescription></CardHeader>
                  <CardContent className="space-y-5">

                    <div className="space-y-3">
                      <div className="flex items-center gap-2"><Badge className="bg-brand-soft px-2 py-0.5 text-[11px] text-brand-600">LLM</Badge><span className="text-sm font-medium text-text-primary">大语言模型</span></div>
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                        <div className="grid gap-1.5"><Label className="text-xs text-text-secondary">厂商</Label>
                          <Select value={config.llm_provider} onValueChange={onLlmProvider}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{providersWithCapability('llm').map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent></Select>
                        </div>
                        <div className="grid gap-1.5"><Label className="text-xs text-text-secondary">模型</Label>
                          {llmModels.length > 0 ? <Select value={config.llm_model} onValueChange={(v) => setConfig({ ...config, llm_model: v })}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{llmModels.map((m) => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}</SelectContent></Select>
                          : <Input className="h-9 text-sm" value={config.llm_model} onChange={(e) => setConfig({ ...config, llm_model: e.target.value })} placeholder="模型 ID" />}
                        </div>
                      </div>
                      {(() => { const llmKeys = (apiKeys || []).filter((k) => k.provider === config.llm_provider); const defaultKey = llmKeys.find((k) => k.is_default) || llmKeys[0]; const pcat = findProvider(config.llm_provider); if (!pcat?.needsKey) return <p className="text-[11px] text-text-tertiary">该厂商无需 API Key</p>; if (llmKeys.length === 0) return (
                        <div className="flex items-center gap-3 rounded-md border border-border-soft bg-bg-secondary/50 px-3 py-2">
                          <Badge className="bg-danger/15 px-2 py-0.5 text-[11px] text-danger">未配置</Badge>
                          <span className="text-xs text-text-tertiary">请添加 {pcat?.label || config.llm_provider} 的 API Key</span>
                          <Button type="button" variant="outline" size="sm" className="ml-auto h-7 text-xs" onClick={() => openAddKey(config.llm_provider)}><PlusIcon size={12} /> 添加 Key</Button>
                        </div>
                      ); return (
                        <div className="flex items-center gap-2">
                          <Label className="flex items-center gap-1.5 text-xs text-text-secondary"><KeyIcon size={12} /> Key</Label>
                          <Select value={String(defaultKey?.id || '')} onValueChange={(v) => { const selected = llmKeys.find((k) => String(k.id) === v); if (selected && !selected.is_default) setDefaultKey.mutate(selected); }}>
                            <SelectTrigger className="h-8 flex-1 text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>{llmKeys.map((k) => (<SelectItem key={k.id} value={String(k.id)}><span className="flex items-center gap-2">{k.name} <span className="font-mono text-xs text-text-tertiary">{k.key_masked}</span>{k.is_default && <Badge className="bg-success/15 px-1 py-0 text-[10px] text-success">默认</Badge>}</span></SelectItem>))}</SelectContent>
                          </Select>
                          <Button type="button" variant="outline" size="sm" className="h-8 text-xs" onClick={() => openAddKey(config.llm_provider)}><PlusIcon size={12} /></Button>
                        </div>
                      ); })()}
                    </div>

                    <div className="border-t border-border-soft" />

                    <div className="space-y-3">
                      <div className="flex items-center gap-2"><Badge className="bg-accent-purple/15 px-2 py-0.5 text-[11px] text-accent-purple">Embedding</Badge><span className="text-sm font-medium text-text-primary">向量化模型</span></div>
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                        <div className="grid gap-1.5"><Label className="text-xs text-text-secondary">厂商</Label>
                          <Select value={config.embed_provider} onValueChange={onEmbProvider}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{providersWithCapability('embedding').map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent></Select>
                        </div>
                        <div className="grid gap-1.5"><Label className="text-xs text-text-secondary">模型</Label>
                          {embModels.length > 0 ? <Select value={config.embed_model} onValueChange={(v) => setConfig({ ...config, embed_model: v })}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{embModels.map((m) => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}</SelectContent></Select>
                          : <Input className="h-9 text-sm" value={config.embed_model} onChange={(e) => setConfig({ ...config, embed_model: e.target.value })} placeholder="BAAI/bge-m3" />}
                        </div>
                      </div>
                      {(() => { const embKeys = (apiKeys || []).filter((k) => k.provider === config.embed_provider); const defaultKey = embKeys.find((k) => k.is_default) || embKeys[0]; const pcat = findProvider(config.embed_provider); if (!pcat?.needsKey) return <p className="text-[11px] text-text-tertiary">该厂商无需 API Key</p>; if (embKeys.length === 0) return (
                        <div className="flex items-center gap-3 rounded-md border border-border-soft bg-bg-secondary/50 px-3 py-2">
                          <Badge className="bg-danger/15 px-2 py-0.5 text-[11px] text-danger">未配置</Badge>
                          <span className="text-xs text-text-tertiary">请添加 {pcat?.label || config.embed_provider} 的 API Key</span>
                          <Button type="button" variant="outline" size="sm" className="ml-auto h-7 text-xs" onClick={() => openAddKey(config.embed_provider)}><PlusIcon size={12} /> 添加 Key</Button>
                        </div>
                      ); return (
                        <div className="flex items-center gap-2">
                          <Label className="flex items-center gap-1.5 text-xs text-text-secondary"><KeyIcon size={12} /> Key</Label>
                          <Select value={String(defaultKey?.id || '')} onValueChange={(v) => { const selected = embKeys.find((k) => String(k.id) === v); if (selected && !selected.is_default) setDefaultKey.mutate(selected); }}>
                            <SelectTrigger className="h-8 flex-1 text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>{embKeys.map((k) => (<SelectItem key={k.id} value={String(k.id)}><span className="flex items-center gap-2">{k.name} <span className="font-mono text-xs text-text-tertiary">{k.key_masked}</span>{k.is_default && <Badge className="bg-success/15 px-1 py-0 text-[10px] text-success">默认</Badge>}</span></SelectItem>))}</SelectContent>
                          </Select>
                          <Button type="button" variant="outline" size="sm" className="h-8 text-xs" onClick={() => openAddKey(config.embed_provider)}><PlusIcon size={12} /></Button>
                        </div>
                      ); })()}
                    </div>

                    <div className="border-t border-border-soft" />

                    <div className="space-y-3">
                      <div className="flex items-center gap-2"><Badge className="bg-success/15 px-2 py-0.5 text-[11px] text-success">Reranker</Badge><span className="text-sm font-medium text-text-primary">重排序模型</span></div>
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                        <div className="grid gap-1.5"><Label className="text-xs text-text-secondary">厂商</Label>
                          <Select value={config.rerank_provider} onValueChange={onRrProvider}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{providersWithCapability('reranker').map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent></Select>
                        </div>
                        <div className="grid gap-1.5"><Label className="text-xs text-text-secondary">模型</Label>
                          {rrModels.length > 0 ? <Select value={config.rerank_model} onValueChange={(v) => setConfig({ ...config, rerank_model: v })}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{rrModels.map((m) => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}</SelectContent></Select>
                          : <Input className="h-9 text-sm" value={config.rerank_model} onChange={(e) => setConfig({ ...config, rerank_model: e.target.value })} placeholder="BAAI/bge-reranker-v2-m3" />}
                        </div>
                      </div>
                      {(() => { const rrKeys = (apiKeys || []).filter((k) => k.provider === config.rerank_provider); const defaultKey = rrKeys.find((k) => k.is_default) || rrKeys[0]; const pcat = findProvider(config.rerank_provider); if (!pcat?.needsKey) return <p className="text-[11px] text-text-tertiary">该厂商无需 API Key</p>; if (rrKeys.length === 0) return (
                        <div className="flex items-center gap-3 rounded-md border border-border-soft bg-bg-secondary/50 px-3 py-2">
                          <Badge className="bg-danger/15 px-2 py-0.5 text-[11px] text-danger">未配置</Badge>
                          <span className="text-xs text-text-tertiary">请添加 {pcat?.label || config.rerank_provider} 的 API Key</span>
                          <Button type="button" variant="outline" size="sm" className="ml-auto h-7 text-xs" onClick={() => openAddKey(config.rerank_provider)}><PlusIcon size={12} /> 添加 Key</Button>
                        </div>
                      ); return (
                        <div className="flex items-center gap-2">
                          <Label className="flex items-center gap-1.5 text-xs text-text-secondary"><KeyIcon size={12} /> Key</Label>
                          <Select value={String(defaultKey?.id || '')} onValueChange={(v) => { const selected = rrKeys.find((k) => String(k.id) === v); if (selected && !selected.is_default) setDefaultKey.mutate(selected); }}>
                            <SelectTrigger className="h-8 flex-1 text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>{rrKeys.map((k) => (<SelectItem key={k.id} value={String(k.id)}><span className="flex items-center gap-2">{k.name} <span className="font-mono text-xs text-text-tertiary">{k.key_masked}</span>{k.is_default && <Badge className="bg-success/15 px-1 py-0 text-[10px] text-success">默认</Badge>}</span></SelectItem>))}</SelectContent>
                          </Select>
                          <Button type="button" variant="outline" size="sm" className="h-8 text-xs" onClick={() => openAddKey(config.rerank_provider)}><PlusIcon size={12} /></Button>
                        </div>
                      ); })()}
                    </div>

                    <div className="border-t border-border-soft" />

                    <div className="space-y-2">
                      <div className="flex items-center gap-2"><span className="text-sm font-medium text-text-primary">Agent 模型覆盖</span><Badge className="bg-bg-tertiary px-1.5 py-0 text-[10px] text-text-tertiary">可选</Badge></div>
                      <p className="text-[11px] text-text-tertiary">为不同阶段的 Agent 指定不同的 LLM。留空则跟随默认 LLM 配置。</p>
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                        {STAGE_DEFS.map((s) => (
                          <div key={s.key} className="flex items-center gap-3 rounded-md border border-border-soft px-3 py-2">
                            <div className="min-w-0 flex-shrink-0"><div className="text-xs font-medium text-text-primary">{s.label}</div><div className="text-[10px] text-text-tertiary">{s.desc}</div></div>
                            <div className="flex-1">
                              {llmModels.length > 0 ? (
                                <Select value={String(config[s.key] || '__default__')} onValueChange={(v) => setConfig({ ...config, [s.key]: v === '__default__' ? '' : v })}>
                                  <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="__default__">跟随默认</SelectItem>
                                    {llmModels.map((m) => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}
                                  </SelectContent>
                                </Select>
                              ) : (
                                <Input className="h-8 text-xs" value={String(config[s.key] || '')} onChange={(e) => setConfig({ ...config, [s.key]: e.target.value })} placeholder="跟随默认" />
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="border-t border-border-soft" />

                    <div className="space-y-2">
                      <div className="flex items-center gap-2"><span className="text-sm font-medium text-text-primary">向量数据库</span></div>
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                        <div className="grid gap-1.5"><Label className="text-xs text-text-secondary">类型</Label><Select value={config.vector_db_provider} onValueChange={(v) => setConfig({ ...config, vector_db_provider: v })}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{VDB_PROVIDERS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent></Select></div>
                        <div className="grid gap-1.5"><Label className="text-xs text-text-secondary">URL</Label><Input className="h-9 text-sm" value={config.vector_db_url} onChange={(e) => setConfig({ ...config, vector_db_url: e.target.value })} placeholder="http://qdrant:6333" disabled={config.vector_db_provider === 'memory'} /></div>
                        <div className="grid gap-1.5"><Label className="text-xs text-text-secondary">Collection</Label><Input className="h-9 text-sm" value={config.vector_db_collection} onChange={(e) => setConfig({ ...config, vector_db_collection: e.target.value })} placeholder="conclave_chunks" disabled={config.vector_db_provider === 'memory'} /></div>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader><CardTitle className="text-base">运行限制</CardTitle><CardDescription className="text-xs">配置系统运行时参数限制（部分参数需通过环境变量配置）</CardDescription></CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                      <div className="grid gap-2"><Label className="text-sm">默认温度</Label><Input type="number" step="0.1" min="0" max="1" className="h-9 text-sm" value={config.default_temperature} onChange={(e) => setConfig({ ...config, default_temperature: parseFloat(e.target.value) || 0 })} /></div>
                      <div className="grid gap-2"><Label className="text-sm">最大 Agent 数量</Label><Input type="number" min="1" max="32" className="h-9 text-sm" value={config.max_agents} onChange={(e) => setConfig({ ...config, max_agents: parseInt(e.target.value) || 8 })} /></div>
                      <div className="grid gap-2"><Label className="text-sm">最大会议时长(分钟)</Label><Input type="number" min="10" max="480" className="h-9 text-sm" value={config.max_meeting_duration} onChange={(e) => setConfig({ ...config, max_meeting_duration: parseInt(e.target.value) || 120 })} /></div>
                    </div>
                    <div className="flex items-center justify-between rounded-lg border border-border-soft p-3">
                      <div><Label className="text-sm">允许公开注册</Label><p className="mt-1 text-xs text-text-tertiary">关闭后仅管理员可在后台创建用户</p></div>
                      <button type="button" aria-label="切换公开注册" className={`relative h-6 w-11 rounded-full transition-colors ${config.enable_public_registration ? 'bg-brand-500' : 'bg-border-default'}`} onClick={() => setConfig({ ...config, enable_public_registration: !config.enable_public_registration })}>
                        <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${config.enable_public_registration ? 'left-5' : 'left-0.5'}`} />
                      </button>
                    </div>
                  </CardContent>
                </Card>
                <div className="flex justify-end pt-2"><Button size="default" onClick={onSaveCfg} disabled={saveCfg.isPending}>{saveCfg.isPending && <SpinnerIcon size={14} className="mr-2 animate-spin" />}保存配置</Button></div>
              </div>}
          </TabsContent>
        </ScrollArea>
      </Tabs>

      <Dialog open={userDialogOpen} onOpenChange={setUserDialogOpen}>
        <DialogContent className="gap-0 p-0 sm:max-w-lg">
          <DialogHeader className="px-6 pb-2 pt-6"><DialogTitle className="text-base">{editingUser ? '编辑成员角色' : '添加成员'}</DialogTitle><DialogDescription className="mt-1 text-xs">{editingUser ? '修改成员在组织中的角色' : '将已有用户添加到指定组织。请输入对方的用户名（或邮箱），创建后该用户即加入所选组织。'}</DialogDescription></DialogHeader>
          <div className="space-y-4 px-6 py-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="grid gap-2"><Label className="text-sm">用户名 <span className="text-danger">*</span></Label><Input className="h-9 text-sm" value={userForm.username} onChange={(e) => setUserForm({ ...userForm, username: e.target.value })} placeholder="username 或邮箱" disabled={!!editingUser} />{editingUser && <p className="text-[11px] text-text-tertiary">用户名不可修改</p>}</div>
              <div className="grid gap-2"><Label className="text-sm">显示名称</Label><Input className="h-9 text-sm" value={userForm.display_name} onChange={(e) => setUserForm({ ...userForm, display_name: e.target.value })} placeholder="张三" disabled={!!editingUser} />{!editingUser && <p className="text-[11px] text-text-tertiary">由用户账号信息决定，可留空</p>}</div>
            </div>
            {!editingUser && <div className="grid gap-2"><Label className="text-sm">初始密码</Label><Input className="h-9 text-sm" type="password" value={userForm.password} onChange={(e) => setUserForm({ ...userForm, password: e.target.value })} placeholder="可选，添加已有用户时无需填写" autoComplete="new-password" /></div>}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="grid gap-2"><Label className="text-sm">角色</Label><Select value={userForm.role} onValueChange={(v) => setUserForm({ ...userForm, role: v })}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="owner">所有者</SelectItem><SelectItem value="maintainer">管理员</SelectItem><SelectItem value="member">成员</SelectItem><SelectItem value="reporter">访客</SelectItem></SelectContent></Select></div>
              <div className="grid gap-2"><Label className="text-sm">所属组织</Label><Select value={userForm.tenant_id} onValueChange={(v) => setUserForm({ ...userForm, tenant_id: v })} disabled={!!editingUser}><SelectTrigger className="h-9 text-sm"><SelectValue placeholder="选择组织" /></SelectTrigger><SelectContent><SelectItem value="">未分配</SelectItem>{tenants?.map((t: AdminTenant) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}</SelectContent></Select></div>
            </div>
          </div>
          <DialogFooter className="border-t border-border-soft bg-bg-secondary/30 px-6 py-4">
            <Button variant="outline" size="sm" onClick={() => setUserDialogOpen(false)} disabled={saveUser.isPending}>取消</Button>
            <Button size="sm" onClick={() => saveUser.mutate()} disabled={saveUser.isPending}>{saveUser.isPending && <SpinnerIcon size={14} className="mr-2 animate-spin" />}{editingUser ? '保存修改' : '添加成员'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={tenantDialogOpen} onOpenChange={setTenantDialogOpen}>
        <DialogContent className="gap-0 p-0 sm:max-w-lg">
          <DialogHeader className="px-6 pb-2 pt-6"><DialogTitle className="text-base">{editingTenant ? '编辑组织' : '新建组织'}</DialogTitle><DialogDescription className="mt-1 text-xs">{editingTenant ? '修改组织名称和套餐等级' : '创建新的组织/租户。组织是资源隔离和成员管理的基本单位。'}</DialogDescription></DialogHeader>
          <div className="space-y-4 px-6 py-5">
            <div className="grid gap-2"><Label className="text-sm">组织名称 <span className="text-danger">*</span></Label><Input className="h-9 text-sm" value={tenantForm.name} onChange={(e) => setTenantForm({ ...tenantForm, name: e.target.value })} placeholder="例如：AI 研究院" /></div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="grid gap-2"><Label className="text-sm">标识 (slug) {!editingTenant && <span className="text-danger">*</span>}</Label><Input className="h-9 font-mono text-sm" value={tenantForm.slug} onChange={(e) => setTenantForm({ ...tenantForm, slug: e.target.value.toLowerCase().replace(/\s+/g, '-') })} placeholder="my-org" disabled={!!editingTenant} /><p className="text-[11px] text-text-tertiary">{editingTenant ? '标识创建后不可修改' : '仅小写字母、数字和连字符'}</p></div>
              <div className="grid gap-2"><Label className="text-sm">套餐</Label><Select value={tenantForm.plan} onValueChange={(v: AdminTenant['plan']) => setTenantForm({ ...tenantForm, plan: v })}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="free">免费版</SelectItem><SelectItem value="pro">专业版</SelectItem><SelectItem value="enterprise">企业版</SelectItem></SelectContent></Select></div>
            </div>
          </div>
          <DialogFooter className="border-t border-border-soft bg-bg-secondary/30 px-6 py-4">
            <Button variant="outline" size="sm" onClick={() => setTenantDialogOpen(false)} disabled={saveTenant.isPending}>取消</Button>
            <Button size="sm" onClick={() => saveTenant.mutate()} disabled={saveTenant.isPending}>{saveTenant.isPending && <SpinnerIcon size={14} className="mr-2 animate-spin" />}{editingTenant ? '保存修改' : '创建组织'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={keyDialogOpen} onOpenChange={setKeyDialogOpen}>
        <DialogContent className="gap-0 p-0 sm:max-w-lg">
          <DialogHeader className="px-6 pb-2 pt-6"><DialogTitle className="text-base">添加 API Key</DialogTitle><DialogDescription className="mt-1 text-xs">添加新的 API Key。支持多 Provider 多 Key 配置，可按系统或团队维度隔离。添加后可在 LLM/Embedding 卡片中通过下拉框切换默认 Key。</DialogDescription></DialogHeader>
          <div className="space-y-4 px-6 py-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="grid gap-2"><Label className="text-sm">Provider <span className="text-danger">*</span></Label><Select value={keyForm.provider} onValueChange={(v) => { const p = findProvider(v); setKeyForm({ ...keyForm, provider: v, base_url: p?.baseUrl || '' }); }}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{PROVIDER_CATALOG.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent></Select></div>
              <div className="grid gap-2"><Label className="text-sm">名称</Label><Input className="h-9 text-sm" value={keyForm.name} onChange={(e) => setKeyForm({ ...keyForm, name: e.target.value })} placeholder="default" /></div>
            </div>
            <div className="grid gap-2"><Label className="text-sm">API Key <span className="text-danger">*</span></Label>
              <div className="flex gap-2"><Input className="h-9 flex-1 font-mono text-sm" type={showKeyValue ? 'text' : 'password'} value={keyForm.api_key} onChange={(e) => setKeyForm({ ...keyForm, api_key: e.target.value })} placeholder="sk-..." autoComplete="off" /><Button type="button" variant="outline" size="sm" className="h-9" onClick={() => setShowKeyValue(!showKeyValue)}>{showKeyValue ? '隐藏' : '显示'}</Button></div>
              <p className="text-[11px] text-text-tertiary">Key 在服务端加密存储，仅返回脱敏形式。</p>
            </div>
            <div className="grid gap-2"><Label className="text-sm">Base URL</Label><Input className="h-9 font-mono text-sm" value={keyForm.base_url} onChange={(e) => setKeyForm({ ...keyForm, base_url: e.target.value })} placeholder="https://api.example.com/v1" /></div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="grid gap-2"><Label className="text-sm">Scope</Label><Select value={keyForm.scope} onValueChange={(v) => setKeyForm({ ...keyForm, scope: v })}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="system">系统</SelectItem><SelectItem value="team">团队</SelectItem></SelectContent></Select></div>
              <div className="flex items-center justify-between rounded-lg border border-border-soft p-3">
                <div><Label className="text-sm">设为默认</Label><p className="mt-0.5 text-[11px] text-text-tertiary">同 Provider 下仅一个默认</p></div>
                <button type="button" aria-label="切换默认" className={`relative h-6 w-11 rounded-full transition-colors ${keyForm.is_default ? 'bg-brand-500' : 'bg-border-default'}`} onClick={() => setKeyForm({ ...keyForm, is_default: !keyForm.is_default })}>
                  <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${keyForm.is_default ? 'left-5' : 'left-0.5'}`} />
                </button>
              </div>
            </div>
          </div>
          <DialogFooter className="border-t border-border-soft bg-bg-secondary/30 px-6 py-4">
            <Button variant="outline" size="sm" onClick={() => setKeyDialogOpen(false)} disabled={saveKey.isPending}>取消</Button>
            <Button size="sm" onClick={() => saveKey.mutate()} disabled={saveKey.isPending}>{saveKey.isPending && <SpinnerIcon size={14} className="mr-2 animate-spin" />}保存 Key</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog open={!!delUserTarget} title="移除成员" description={delUserTarget ? `确定要将 ${delUserTarget.display_name} 从「${delUserTarget.tenant_name}」移除吗？该操作不可撤销。` : ''} destructive={true} confirmText="移除" onConfirm={confirmDelUser} onCancel={() => setDelUserTarget(null)} />
      <ConfirmDialog open={!!delKeyTarget} title="删除 API Key" description={delKeyTarget ? `确定要删除 ${delKeyTarget.provider}/${delKeyTarget.name} 吗？该操作不可撤销。` : ''} destructive={true} confirmText="删除" onConfirm={confirmDelKey} onCancel={() => setDelKeyTarget(null)} />
    </div>
  );
}
