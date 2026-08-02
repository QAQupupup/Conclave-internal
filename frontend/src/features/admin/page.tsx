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
interface SystemConfig { llm_provider: string; llm_model: string; llm_base_url: string; llm_api_key_configured: boolean; embed_provider: string; embed_model: string; embed_base_url: string; embed_api_key_configured: boolean; rerank_model: string; rerank_base_url: string; rerank_api_key_configured: boolean; vector_db_provider: string; vector_db_url: string; vector_db_collection: string; max_agents: number; max_meeting_duration: number; enable_public_registration: boolean; default_temperature: number; }
interface ProviderCatalog { value: string; label: string; baseUrl: string; models: { value: string; label: string }[]; }
interface TeamItem { id: string | number; name: string; slug: string; member_count?: number; meeting_count?: number; status?: string; plan?: string; created_at?: string; }
interface MemberItem { user_id: string | number; username: string; display_name: string; email: string; is_active?: boolean; role: string; is_banned?: boolean; joined_at?: string; created_at?: string; }
interface ApiKeyItem { id: string | number; provider: string; name: string; key_masked: string; base_url: string; is_default: boolean; scope: string; created_at?: string; }

const LLM_PROVIDERS: ProviderCatalog[] = [
  { value: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', models: [{ value: 'deepseek-chat', label: 'deepseek-chat' }, { value: 'deepseek-reasoner', label: 'deepseek-reasoner' }] },
  { value: 'siliconflow', label: '硅基流动 (SiliconFlow)', baseUrl: 'https://api.siliconflow.cn/v1', models: [{ value: 'deepseek-ai/DeepSeek-V3', label: 'DeepSeek-V3' }, { value: 'Qwen/Qwen2.5-72B-Instruct', label: 'Qwen2.5-72B' }] },
  { value: 'doubao', label: '豆包 (火山引擎)', baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', models: [{ value: 'doubao-seed-2-0-code', label: 'doubao-seed-2-0-code' }] },
  { value: 'qwen', label: '通义千问 (DashScope)', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: [{ value: 'qwen-plus', label: 'qwen-plus' }, { value: 'qwen-max', label: 'qwen-max' }] },
  { value: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', models: [{ value: 'gpt-4o', label: 'GPT-4o' }, { value: 'gpt-4o-mini', label: 'GPT-4o mini' }] },
  { value: 'custom', label: '自定义 (OpenAI 兼容)', baseUrl: '', models: [] },
];
const EMBED_PROVIDERS: ProviderCatalog[] = [
  { value: 'local', label: '本地模型 (BGE/M3E/E5)', baseUrl: '', models: [{ value: 'BAAI/bge-m3', label: 'BAAI/bge-m3 (推荐)' }, { value: 'BAAI/bge-large-zh-v1.5', label: 'BAAI/bge-large-zh-v1.5' }, { value: 'moka-ai/m3e-base', label: 'm3e-base' }] },
  { value: 'siliconflow', label: '硅基流动 (SiliconFlow)', baseUrl: 'https://api.siliconflow.cn/v1', models: [{ value: 'BAAI/bge-m3', label: 'BAAI/bge-m3' }] },
  { value: 'qwen', label: '通义千问 (DashScope)', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: [{ value: 'text-embedding-v3', label: 'text-embedding-v3' }] },
  { value: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1', models: [{ value: 'text-embedding-3-large', label: 'text-embedding-3-large' }, { value: 'text-embedding-3-small', label: 'text-embedding-3-small' }] },
  { value: 'custom', label: '自定义 (OpenAI 兼容)', baseUrl: '', models: [] },
];
const VDB_PROVIDERS = [{ value: 'qdrant', label: 'Qdrant' }, { value: 'memory', label: '内存模式（仅测试）' }];
const KEY_PROVIDERS = [
  { value: 'siliconflow', label: '硅基流动 (SiliconFlow)' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'qwen', label: '通义千问 (DashScope)' },
  { value: 'doubao', label: '豆包 (火山引擎)' },
  { value: 'custom', label: '自定义' },
];
// 系统配置中可通过 PUT /api/config/system/{key} 保存的键（对齐后端 SYSTEM_OVERRIDABLE_KEYS）
const SAVABLE_CONFIG_KEYS: (keyof SystemConfig)[] = ['llm_model', 'llm_base_url', 'llm_provider', 'embed_model', 'embed_base_url', 'embed_provider', 'rerank_model', 'rerank_base_url', 'default_temperature', 'enable_public_registration', 'max_agents', 'max_meeting_duration', 'vector_db_provider', 'vector_db_url', 'vector_db_collection'];

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
const findProvider = (cat: ProviderCatalog[], v: string) => cat.find((p) => p.value === v);
const inferProvider = (baseUrl: string, cat: ProviderCatalog[]) => { if (!baseUrl) return ''; return cat.find((p) => p.baseUrl && baseUrl.startsWith(p.baseUrl))?.value || ''; };

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
  return {
    llm_provider: getStr('llm_provider') || inferProvider(llmBaseUrl, LLM_PROVIDERS),
    llm_model: getStr('llm_model'),
    llm_base_url: llmBaseUrl,
    llm_api_key_configured: getBool('llm_api_key_configured') || (!!llmKey && llmKey !== ''),
    embed_provider: getStr('embed_provider') || inferProvider(embBaseUrl, EMBED_PROVIDERS) || 'local',
    embed_model: getStr('embed_model') || 'BAAI/bge-m3',
    embed_base_url: embBaseUrl,
    embed_api_key_configured: getBool('embed_api_key_configured') || (!!embKey && embKey !== ''),
    rerank_model: getStr('rerank_model') || 'BAAI/bge-reranker-v2-m3',
    rerank_base_url: getStr('rerank_base_url'),
    rerank_api_key_configured: getBool('rerank_api_key_configured') || (!!rrKey && rrKey !== ''),
    vector_db_provider: getStr('vector_db_provider') || 'qdrant',
    vector_db_url: getStr('vector_db_url') || 'http://qdrant:6333',
    vector_db_collection: getStr('vector_db_collection') || 'conclave_chunks',
    max_agents: getNum('max_agents', 8),
    max_meeting_duration: getNum('max_meeting_duration', 120),
    enable_public_registration: getBool('enable_public_registration'),
    default_temperature: getNum('default_temperature', 0.1),
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
const MOCK_CONFIG: SystemConfig = { llm_provider: 'siliconflow', llm_model: 'deepseek-ai/DeepSeek-V3', llm_base_url: 'https://api.siliconflow.cn/v1', llm_api_key_configured: true, embed_provider: 'local', embed_model: 'BAAI/bge-m3', embed_base_url: '', embed_api_key_configured: false, rerank_model: 'BAAI/bge-reranker-v2-m3', rerank_base_url: '', rerank_api_key_configured: false, vector_db_provider: 'qdrant', vector_db_url: 'http://qdrant:6333', vector_db_collection: 'conclave_chunks', max_agents: 8, max_meeting_duration: 120, enable_public_registration: false, default_temperature: 0.1 };
const MOCK_KEYS: ApiKeyItem[] = [
  { id: 'k1', provider: 'siliconflow', name: 'default', key_masked: 'sk-****1234', base_url: 'https://api.siliconflow.cn/v1', is_default: true, scope: 'system', created_at: new Date().toISOString() },
  { id: 'k2', provider: 'deepseek', name: 'default', key_masked: 'sk-****5678', base_url: 'https://api.deepseek.com/v1', is_default: false, scope: 'team', created_at: new Date().toISOString() },
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
  const [llmKey, setLlmKey] = React.useState(''); const [embKey, setEmbKey] = React.useState(''); const [rrKey, setRrKey] = React.useState('');
  const [showLlmKey, setShowLlmKey] = React.useState(false); const [showEmbKey, setShowEmbKey] = React.useState(false); const [showRrKey, setShowRrKey] = React.useState(false);
  const [delUserTarget, setDelUserTarget] = React.useState<AdminUser | null>(null);
  const [keyDialogOpen, setKeyDialogOpen] = React.useState(false);
  const [editingKey, setEditingKey] = React.useState<ApiKeyItem | null>(null);
  const [keyForm, setKeyForm] = React.useState({ provider: 'siliconflow', name: 'default', api_key: '', base_url: '', is_default: false, scope: 'system' });
  const [showKeyValue, setShowKeyValue] = React.useState(false);
  const [delKeyTarget, setDelKeyTarget] = React.useState<ApiKeyItem | null>(null);

  // 系统配置：GET /api/config/system
  const { data: configData, error: cfgErr, isLoading: cfgLoad } = useQuery({ queryKey: ['admin', 'config'], queryFn: async () => isDemoMode() ? MOCK_CONFIG : normalizeConfig(await api.get<unknown>('/api/config/system')), retry: false });
  React.useEffect(() => { if (configData) { setConfig(configData); configSnapshot.current = configData; setLlmKey(''); setEmbKey(''); setRrKey(''); } }, [configData]);

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
      if (llmKey.trim()) changes.push({ key: 'llm_api_key', value: llmKey.trim() });
      if (embKey.trim()) changes.push({ key: 'embed_api_key', value: embKey.trim() });
      if (rrKey.trim()) changes.push({ key: 'rerank_api_key', value: rrKey.trim() });
      if (!changes.length) return;
      const results = await Promise.allSettled(changes.map((c) => api.put(`/api/config/system/${encodeURIComponent(c.key)}`, { value: c.value })));
      const failed = results.filter((r) => r.status === 'rejected');
      if (failed.length) { const fr = failed[0]; const err = fr.status === 'rejected' ? fr.reason : null; throw err instanceof Error ? err : new Error(`${failed.length} 项保存失败`); }
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'config'] }); setLlmKey(''); setEmbKey(''); setRrKey(''); toast({ title: '配置已保存', description: '部分设置需重启服务生效' }); },
    onError: (e: unknown) => { const info = getErrorDisplay(e, 'PUT /api/config/system/{key}'); toast({ title: info.title, description: info.hint, variant: 'destructive' }); },
  });
  // 保存/设为默认 API Key：POST /api/keys
  const saveKey = useMutation({
    mutationFn: async () => {
      if (!keyForm.provider || !keyForm.api_key) throw new Error('请填写 Provider 和 API Key');
      if (isDemoMode()) return;
      await api.post('/api/keys', { provider: keyForm.provider, name: keyForm.name || 'default', api_key: keyForm.api_key, base_url: keyForm.base_url, is_default: keyForm.is_default, scope: keyForm.scope });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'keys'] }); toast({ title: editingKey ? 'Key 已更新' : 'Key 已保存' }); setKeyDialogOpen(false); setEditingKey(null); setKeyForm({ provider: 'siliconflow', name: 'default', api_key: '', base_url: '', is_default: false, scope: 'system' }); setShowKeyValue(false); },
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
  const openAddKey = () => { setEditingKey(null); setKeyForm({ provider: 'siliconflow', name: 'default', api_key: '', base_url: '', is_default: false, scope: 'system' }); setShowKeyValue(false); setKeyDialogOpen(true); };
  const openSetDefault = (k: ApiKeyItem) => { setEditingKey(k); setKeyForm({ provider: k.provider, name: k.name, api_key: '', base_url: k.base_url || '', is_default: true, scope: k.scope }); setShowKeyValue(false); setKeyDialogOpen(true); };
  const onSaveCfg = () => {
    if (isDemoMode()) { toast({ title: '演示模式', description: '配置不可修改' }); return; }
    if (!config) return;
    const snap = configSnapshot.current;
    const hasChanges = SAVABLE_CONFIG_KEYS.some((f) => String(config[f] ?? '') !== String(snap?.[f] ?? '')) || !!llmKey.trim() || !!embKey.trim() || !!rrKey.trim();
    if (!hasChanges) { toast({ title: '无变更', description: '没有需要保存的配置项' }); return; }
    saveCfg.mutate();
  };
  const onLlmProvider = (v: string) => { if (!config) return; const p = findProvider(LLM_PROVIDERS, v); setConfig({ ...config, llm_provider: v, llm_base_url: p?.baseUrl || config.llm_base_url, llm_model: p?.models?.[0]?.value || '' }); };
  const onEmbProvider = (v: string) => { if (!config) return; const p = findProvider(EMBED_PROVIDERS, v); setConfig({ ...config, embed_provider: v, embed_base_url: p?.baseUrl || '', embed_model: p?.models?.[0]?.value || 'BAAI/bge-m3' }); };
  const llmModels = findProvider(LLM_PROVIDERS, config?.llm_provider || '')?.models || [];
  const embModels = findProvider(EMBED_PROVIDERS, config?.embed_provider || '')?.models || [];

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
                  <CardHeader><CardTitle className="text-base">大语言模型 (LLM)</CardTitle><CardDescription className="text-xs">配置用于会议主持和讨论推理的大语言模型</CardDescription></CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid gap-2"><Label className="text-sm">LLM 提供商</Label>
                      <Select value={config.llm_provider} onValueChange={onLlmProvider}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{LLM_PROVIDERS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent></Select>
                    </div>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div className="grid gap-2"><Label className="text-sm">API Base URL</Label><Input className="h-9 text-sm" value={config.llm_base_url} onChange={(e) => setConfig({ ...config, llm_base_url: e.target.value })} placeholder="https://api.example.com/v1" /></div>
                      <div className="grid gap-2"><Label className="text-sm">模型名称</Label>
                        {llmModels.length > 0 ? <Select value={config.llm_model} onValueChange={(v) => setConfig({ ...config, llm_model: v })}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{llmModels.map((m) => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}</SelectContent></Select>
                          : <Input className="h-9 text-sm" value={config.llm_model} onChange={(e) => setConfig({ ...config, llm_model: e.target.value })} placeholder="模型 ID" />}
                      </div>
                    </div>
                    <div className="grid gap-2">
                      <Label className="flex items-center gap-2 text-sm"><KeyIcon size={14} /> API Key (SK){config.llm_api_key_configured && !llmKey && <Badge className="bg-success/15 px-1.5 py-0 text-[10px] text-success">已配置</Badge>}</Label>
                      <div className="flex gap-2"><Input className="h-9 flex-1 font-mono text-sm" type={showLlmKey ? 'text' : 'password'} value={llmKey} onChange={(e) => setLlmKey(e.target.value)} placeholder={config.llm_api_key_configured ? '留空则保持原 Key 不变' : '请输入 API Key'} autoComplete="off" /><Button type="button" variant="outline" size="sm" className="h-9" onClick={() => setShowLlmKey(!showLlmKey)}>{showLlmKey ? '隐藏' : '显示'}</Button></div>
                      <p className="text-[11px] text-text-tertiary">API Key 仅在服务端加密存储，不会返回给前端。留空表示保持现有配置不变。</p>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader><div className="flex items-center justify-between"><div><CardTitle className="text-base">API Key 管理</CardTitle><CardDescription className="text-xs">管理系统、团队级的 API Key，支持多 Provider 多 Key 配置</CardDescription></div><Button size="sm" variant="outline" onClick={openAddKey}><PlusIcon size={14} /> 添加 Key</Button></div></CardHeader>
                  <CardContent>
                    {keysLoad && !apiKeys ? <div className="flex items-center justify-center gap-2 py-8 text-xs text-text-tertiary"><SpinnerIcon size={16} className="animate-spin" /> 加载 API Key 列表...</div>
                      : keysErr ? <div className="flex flex-col items-center justify-center gap-2 py-8"><div className="text-xs text-danger">{getErrorDisplay(keysErr, '/api/keys').title}</div><div className="text-[10px] text-text-tertiary">{getErrorDisplay(keysErr, '/api/keys').hint}</div></div>
                      : !apiKeys?.length ? <div className="flex items-center justify-center py-8 text-xs text-text-tertiary">暂无 API Key，点击右上角"添加 Key"创建</div>
                      : <div className="overflow-x-auto"><table className="w-full text-sm">
                        <thead><tr className="border-b border-border-soft bg-bg-secondary text-text-tertiary">
                          <th className="px-3 py-2.5 text-left font-medium">Provider</th><th className="px-3 py-2.5 text-left font-medium">名称</th><th className="px-3 py-2.5 text-left font-medium">Scope</th><th className="px-3 py-2.5 text-left font-medium">Key</th><th className="px-3 py-2.5 text-left font-medium">Base URL</th><th className="px-3 py-2.5 text-right font-medium">操作</th>
                        </tr></thead>
                        <tbody>
                          {apiKeys.map((k: ApiKeyItem) => {
                            const sb = SCOPE_BADGE[k.scope] || SCOPE_BADGE.team;
                            return (
                              <tr key={`${k.provider}-${k.name}-${k.id}`} className="border-b border-border-soft last:border-0 hover:bg-bg-secondary/50">
                                <td className="px-3 py-2.5 font-medium text-text-primary">{k.provider}</td>
                                <td className="px-3 py-2.5 text-text-secondary">{k.name}</td>
                                <td className="px-3 py-2.5"><Badge className={`${sb.className} px-2 py-0.5 text-[11px]`}>{sb.label}</Badge></td>
                                <td className="px-3 py-2.5"><div className="flex items-center gap-2"><span className="font-mono text-xs text-text-secondary">{k.key_masked}</span>{k.is_default && <Badge className="bg-success/15 px-1.5 py-0 text-[10px] text-success">默认</Badge>}</div></td>
                                <td className="px-3 py-2.5 font-mono text-xs text-text-tertiary">{k.base_url || '-'}</td>
                                <td className="px-3 py-2.5 text-right"><div className="flex items-center justify-end gap-1">
                                  {!k.is_default && <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openSetDefault(k)} title="设为默认"><StarIcon size={14} /></Button>}
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
                  <CardHeader><CardTitle className="text-base">Embedding 模型 & 向量库</CardTitle><CardDescription className="text-xs">配置文本向量化模型、重排序模型和向量数据库。Embedding 模型与 LLM 独立，不能选择 DeepSeek 等仅提供对话能力的模型。</CardDescription></CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid gap-2"><Label className="text-sm">Embedding 提供商</Label>
                      <Select value={config.embed_provider} onValueChange={onEmbProvider}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{EMBED_PROVIDERS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent></Select>
                    </div>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div className="grid gap-2"><Label className="text-sm">Embedding API Base URL</Label><Input className="h-9 text-sm" value={config.embed_base_url} onChange={(e) => setConfig({ ...config, embed_base_url: e.target.value })} placeholder={config.embed_provider === 'local' ? '本地模型无需配置' : 'https://api.example.com/v1'} disabled={config.embed_provider === 'local'} /></div>
                      <div className="grid gap-2"><Label className="text-sm">Embedding 模型</Label>
                        {embModels.length > 0 ? <Select value={config.embed_model} onValueChange={(v) => setConfig({ ...config, embed_model: v })}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{embModels.map((m) => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}</SelectContent></Select>
                          : <Input className="h-9 text-sm" value={config.embed_model} onChange={(e) => setConfig({ ...config, embed_model: e.target.value })} placeholder="BAAI/bge-m3" />}
                      </div>
                    </div>
                    {config.embed_provider !== 'local' && (
                      <div className="grid gap-2">
                        <Label className="flex items-center gap-2 text-sm"><KeyIcon size={14} /> Embedding API Key{config.embed_api_key_configured && !embKey && <Badge className="bg-success/15 px-1.5 py-0 text-[10px] text-success">已配置</Badge>}</Label>
                        <div className="flex gap-2"><Input className="h-9 flex-1 font-mono text-sm" type={showEmbKey ? 'text' : 'password'} value={embKey} onChange={(e) => setEmbKey(e.target.value)} placeholder={config.embed_api_key_configured ? '留空则保持原 Key 不变' : '请输入 Embedding API Key'} autoComplete="off" /><Button type="button" variant="outline" size="sm" className="h-9" onClick={() => setShowEmbKey(!showEmbKey)}>{showEmbKey ? '隐藏' : '显示'}</Button></div>
                      </div>
                    )}
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div className="grid gap-2"><Label className="text-sm">Reranker 模型</Label><Input className="h-9 text-sm" value={config.rerank_model} onChange={(e) => setConfig({ ...config, rerank_model: e.target.value })} placeholder="BAAI/bge-reranker-v2-m3" /></div>
                      <div className="grid gap-2">
                        <Label className="flex items-center gap-2 text-sm"><KeyIcon size={14} /> Reranker API Key{config.rerank_api_key_configured && !rrKey && <Badge className="bg-success/15 px-1.5 py-0 text-[10px] text-success">已配置</Badge>}</Label>
                        <div className="flex gap-2"><Input className="h-9 flex-1 font-mono text-sm" type={showRrKey ? 'text' : 'password'} value={rrKey} onChange={(e) => setRrKey(e.target.value)} placeholder="可选，留空不使用远程 Reranker" autoComplete="off" /><Button type="button" variant="outline" size="sm" className="h-9" onClick={() => setShowRrKey(!showRrKey)}>{showRrKey ? '隐藏' : '显示'}</Button></div>
                      </div>
                    </div>
                    <div className="my-2 border-t border-border-soft" />
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                      <div className="grid gap-2"><Label className="text-sm">向量数据库</Label><Select value={config.vector_db_provider} onValueChange={(v) => setConfig({ ...config, vector_db_provider: v })}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{VDB_PROVIDERS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent></Select></div>
                      <div className="grid gap-2"><Label className="text-sm">向量库 URL</Label><Input className="h-9 text-sm" value={config.vector_db_url} onChange={(e) => setConfig({ ...config, vector_db_url: e.target.value })} placeholder="http://qdrant:6333" disabled={config.vector_db_provider === 'memory'} /></div>
                      <div className="grid gap-2"><Label className="text-sm">Collection 名称</Label><Input className="h-9 text-sm" value={config.vector_db_collection} onChange={(e) => setConfig({ ...config, vector_db_collection: e.target.value })} placeholder="conclave_chunks" disabled={config.vector_db_provider === 'memory'} /></div>
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
          <DialogHeader className="px-6 pb-2 pt-6"><DialogTitle className="text-base">{editingKey ? '设为默认 Key' : '添加 API Key'}</DialogTitle><DialogDescription className="mt-1 text-xs">{editingKey ? '重新输入 Key 以将其设为默认。设为默认后，同 Provider 下其他 Key 将自动取消默认。' : '添加新的 API Key。支持多 Provider 多 Key 配置，可按系统或团队维度隔离。'}</DialogDescription></DialogHeader>
          <div className="space-y-4 px-6 py-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="grid gap-2"><Label className="text-sm">Provider <span className="text-danger">*</span></Label><Select value={keyForm.provider} onValueChange={(v) => setKeyForm({ ...keyForm, provider: v })} disabled={!!editingKey}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent>{KEY_PROVIDERS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent></Select></div>
              <div className="grid gap-2"><Label className="text-sm">名称</Label><Input className="h-9 text-sm" value={keyForm.name} onChange={(e) => setKeyForm({ ...keyForm, name: e.target.value })} placeholder="default" disabled={!!editingKey} /></div>
            </div>
            <div className="grid gap-2"><Label className="text-sm">API Key <span className="text-danger">*</span></Label>
              <div className="flex gap-2"><Input className="h-9 flex-1 font-mono text-sm" type={showKeyValue ? 'text' : 'password'} value={keyForm.api_key} onChange={(e) => setKeyForm({ ...keyForm, api_key: e.target.value })} placeholder={editingKey ? '重新输入完整 Key 以设为默认' : 'sk-...'} autoComplete="off" /><Button type="button" variant="outline" size="sm" className="h-9" onClick={() => setShowKeyValue(!showKeyValue)}>{showKeyValue ? '隐藏' : '显示'}</Button></div>
              <p className="text-[11px] text-text-tertiary">Key 在服务端加密存储，仅返回脱敏形式。</p>
            </div>
            <div className="grid gap-2"><Label className="text-sm">Base URL</Label><Input className="h-9 font-mono text-sm" value={keyForm.base_url} onChange={(e) => setKeyForm({ ...keyForm, base_url: e.target.value })} placeholder="https://api.example.com/v1" /></div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="grid gap-2"><Label className="text-sm">Scope</Label><Select value={keyForm.scope} onValueChange={(v) => setKeyForm({ ...keyForm, scope: v })} disabled={!!editingKey}><SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="system">系统</SelectItem><SelectItem value="team">团队</SelectItem></SelectContent></Select></div>
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
            <Button size="sm" onClick={() => saveKey.mutate()} disabled={saveKey.isPending}>{saveKey.isPending && <SpinnerIcon size={14} className="mr-2 animate-spin" />}{editingKey ? '设为默认' : '保存 Key'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog open={!!delUserTarget} title="移除成员" description={delUserTarget ? `确定要将 ${delUserTarget.display_name} 从「${delUserTarget.tenant_name}」移除吗？该操作不可撤销。` : ''} destructive={true} confirmText="移除" onConfirm={confirmDelUser} onCancel={() => setDelUserTarget(null)} />
      <ConfirmDialog open={!!delKeyTarget} title="删除 API Key" description={delKeyTarget ? `确定要删除 ${delKeyTarget.provider}/${delKeyTarget.name} 吗？该操作不可撤销。` : ''} destructive={true} confirmText="删除" onConfirm={confirmDelKey} onCancel={() => setDelKeyTarget(null)} />
    </div>
  );
}
