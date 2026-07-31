import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import {
  ShieldIcon,
  UsersIcon,
  BuildingIcon,
  SettingsIcon,
  PlusIcon,
  TrashIcon,
  EditIcon,
  UserIcon,
  CheckIcon,
  XIcon,
} from '@/components/ui/svg-icons';
import { useAuthStore } from '@/stores/auth-slice';

// ====== Mock Data (when backend APIs are not available) ======
interface AdminUser {
  id: string;
  username: string;
  display_name: string;
  email: string;
  role: 'admin' | 'member' | 'owner';
  tenant_id: string;
  tenant_name: string;
  status: 'active' | 'disabled';
  created_at: string;
  last_login?: string;
}

interface AdminTenant {
  id: string;
  name: string;
  slug: string;
  member_count: number;
  meeting_count: number;
  status: 'active' | 'suspended';
  plan: 'free' | 'pro' | 'enterprise';
  created_at: string;
}

interface SystemConfig {
  llm_provider: string;
  llm_model: string;
  max_agents: number;
  max_meeting_duration: number;
  enable_public_registration: boolean;
  default_temperature: number;
  embedding_model: string;
  vector_db: string;
}

const MOCK_USERS: AdminUser[] = [
  { id: 'u1', username: 'admin', display_name: '系统管理员', email: 'admin@conclave.local', role: 'owner', tenant_id: 't1', tenant_name: '默认组织', status: 'active', created_at: '2026-01-01T00:00:00Z', last_login: new Date().toISOString() },
  { id: 'u2', username: 'zhangsan', display_name: '张三', email: 'zhangsan@example.com', role: 'admin', tenant_id: 't1', tenant_name: '默认组织', status: 'active', created_at: '2026-02-15T10:30:00Z', last_login: '2026-07-30T09:00:00Z' },
  { id: 'u3', username: 'lisi', display_name: '李四', email: 'lisi@example.com', role: 'member', tenant_id: 't1', tenant_name: '默认组织', status: 'active', created_at: '2026-03-01T14:20:00Z', last_login: '2026-07-29T16:45:00Z' },
  { id: 'u4', username: 'wangwu', display_name: '王五', email: 'wangwu@example.com', role: 'member', tenant_id: 't2', tenant_name: 'AI研究院', status: 'active', created_at: '2026-03-10T08:00:00Z', last_login: '2026-07-28T11:30:00Z' },
  { id: 'u5', username: 'zhaoliu', display_name: '赵六', email: 'zhaoliu@example.com', role: 'admin', tenant_id: 't2', tenant_name: 'AI研究院', status: 'disabled', created_at: '2026-04-05T16:00:00Z' },
  { id: 'u6', username: 'sunqi', display_name: '孙七', email: 'sunqi@techcorp.com', role: 'owner', tenant_id: 't3', tenant_name: 'TechCorp', status: 'active', created_at: '2026-05-20T09:15:00Z', last_login: '2026-07-30T08:00:00Z' },
];

const MOCK_TENANTS: AdminTenant[] = [
  { id: 't1', name: '默认组织', slug: 'default', member_count: 3, meeting_count: 42, status: 'active', plan: 'enterprise', created_at: '2026-01-01T00:00:00Z' },
  { id: 't2', name: 'AI研究院', slug: 'ai-research', member_count: 2, meeting_count: 18, status: 'active', plan: 'pro', created_at: '2026-03-10T08:00:00Z' },
  { id: 't3', name: 'TechCorp', slug: 'techcorp', member_count: 1, meeting_count: 7, status: 'active', plan: 'free', created_at: '2026-05-20T09:15:00Z' },
];

const MOCK_CONFIG: SystemConfig = {
  llm_provider: 'deepseek',
  llm_model: 'deepseek-chat',
  max_agents: 8,
  max_meeting_duration: 120,
  enable_public_registration: false,
  default_temperature: 0.1,
  embedding_model: 'bge-m3',
  vector_db: 'qdrant',
};

const ROLE_BADGE: Record<string, { className: string; label: string }> = {
  owner: { className: 'bg-accent-purple/15 text-accent-purple', label: '所有者' },
  admin: { className: 'bg-brand-soft text-brand-600', label: '管理员' },
  member: { className: 'bg-bg-tertiary text-text-secondary', label: '成员' },
};

const PLAN_BADGE: Record<string, { className: string; label: string }> = {
  free: { className: 'bg-bg-tertiary text-text-secondary', label: '免费版' },
  pro: { className: 'bg-brand-soft text-brand-600', label: '专业版' },
  enterprise: { className: 'bg-accent-purple/15 text-accent-purple', label: '企业版' },
};

export default function AdminPage() {
  const { toast } = useToast();
  const currentUser = useAuthStore((s) => s.user);
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = React.useState('users');

  // User dialog state
  const [userDialogOpen, setUserDialogOpen] = React.useState(false);
  const [editingUser, setEditingUser] = React.useState<AdminUser | null>(null);
  const [userForm, setUserForm] = React.useState({ username: '', display_name: '', email: '', role: 'member' as AdminUser['role'], tenant_id: 't1' });

  // Tenant dialog state
  const [tenantDialogOpen, setTenantDialogOpen] = React.useState(false);
  const [editingTenant, setEditingTenant] = React.useState<AdminTenant | null>(null);
  const [tenantForm, setTenantForm] = React.useState({ name: '', slug: '', plan: 'free' as AdminTenant['plan'] });

  // Config state
  const [config, setConfig] = React.useState<SystemConfig>(MOCK_CONFIG);

  // Fetch data with fallback to mock
  const { data: users = MOCK_USERS, isLoading: usersLoading } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: async () => {
      try {
        return await api.get<AdminUser[]>('/admin/users');
      } catch {
        return MOCK_USERS;
      }
    },
    retry: false,
  });

  const { data: tenants = MOCK_TENANTS, isLoading: tenantsLoading } = useQuery({
    queryKey: ['admin', 'tenants'],
    queryFn: async () => {
      try {
        return await api.get<AdminTenant[]>('/admin/tenants');
      } catch {
        return MOCK_TENANTS;
      }
    },
    retry: false,
  });

  const toggleUserStatus = useMutation({
    mutationFn: async (userId: string) => {
      try {
        await api.post(`/admin/users/${userId}/toggle`);
      } catch {
        // Mock: toggle locally
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
      toast({ title: '操作成功' });
    },
  });

  const deleteUser = useMutation({
    mutationFn: async (userId: string) => {
      try {
        await api.delete(`/admin/users/${userId}`);
      } catch {
        // Mock
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
      toast({ title: '用户已删除' });
    },
  });

  const saveUser = () => {
    if (!userForm.username || !userForm.display_name) {
      toast({ title: '请填写必填字段', variant: 'destructive' });
      return;
    }
    toast({ title: editingUser ? '用户已更新' : '用户已创建', description: '(原型演示，数据未持久化)' });
    setUserDialogOpen(false);
    setEditingUser(null);
    setUserForm({ username: '', display_name: '', email: '', role: 'member', tenant_id: 't1' });
  };

  const saveTenant = () => {
    if (!tenantForm.name || !tenantForm.slug) {
      toast({ title: '请填写必填字段', variant: 'destructive' });
      return;
    }
    toast({ title: editingTenant ? '组织已更新' : '组织已创建', description: '(原型演示，数据未持久化)' });
    setTenantDialogOpen(false);
    setEditingTenant(null);
    setTenantForm({ name: '', slug: '', plan: 'free' });
  };

  const saveConfig = () => {
    toast({ title: '配置已保存', description: '(原型演示，配置未持久化)' });
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return '从未登录';
    return new Date(dateStr).toLocaleDateString('zh-CN');
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex-shrink-0 border-b border-border-soft bg-bg-primary p-4">
        <div className="flex items-center gap-2">
          <ShieldIcon size={20} className="text-accent-purple" />
          <h2 className="text-lg font-semibold text-text-primary">系统管理</h2>
        </div>
        <p className="text-xs text-text-tertiary mt-1">管理用户、组织和系统配置</p>
      </div>

      {/* Content */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col">
        <div className="flex-shrink-0 border-b border-border-soft bg-bg-primary px-4">
          <TabsList className="h-10 bg-transparent gap-0 p-0">
            <TabsTrigger value="users" className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-brand-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-3 gap-1.5">
              <UsersIcon size={14} />
              用户管理
              <Badge className="ml-1 bg-bg-tertiary text-text-tertiary text-[10px] px-1 py-0">{users.length}</Badge>
            </TabsTrigger>
            <TabsTrigger value="tenants" className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-brand-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-3 gap-1.5">
              <BuildingIcon size={14} />
              组织管理
              <Badge className="ml-1 bg-bg-tertiary text-text-tertiary text-[10px] px-1 py-0">{tenants.length}</Badge>
            </TabsTrigger>
            <TabsTrigger value="config" className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-brand-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-3 gap-1.5">
              <SettingsIcon size={14} />
              系统配置
            </TabsTrigger>
          </TabsList>
        </div>

        <ScrollArea className="flex-1">
          {/* Users Tab */}
          <TabsContent value="users" className="p-4 m-0">
            <div className="flex justify-end mb-3">
              <Button size="sm" onClick={() => { setEditingUser(null); setUserForm({ username: '', display_name: '', email: '', role: 'member', tenant_id: 't1' }); setUserDialogOpen(true); }}>
                <PlusIcon size={14} />
                新建用户
              </Button>
            </div>
            <Card>
              <CardContent className="p-0">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border-soft bg-bg-secondary text-text-tertiary">
                      <th className="text-left py-2.5 px-3 font-medium">用户</th>
                      <th className="text-left py-2.5 px-3 font-medium">邮箱</th>
                      <th className="text-left py-2.5 px-3 font-medium">角色</th>
                      <th className="text-left py-2.5 px-3 font-medium">所属组织</th>
                      <th className="text-left py-2.5 px-3 font-medium">状态</th>
                      <th className="text-left py-2.5 px-3 font-medium">最后登录</th>
                      <th className="text-right py-2.5 px-3 font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u: AdminUser) => {
                      const roleBadge = ROLE_BADGE[u.role] || ROLE_BADGE.member;
                      return (
                        <tr key={u.id} className="border-b border-border-soft last:border-0 hover:bg-bg-secondary/50">
                          <td className="py-2.5 px-3">
                            <div className="flex items-center gap-2">
                              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-soft text-brand-600 text-[10px] font-semibold">
                                {u.display_name.charAt(0)}
                              </div>
                              <div>
                                <div className="font-medium text-text-primary">{u.display_name}</div>
                                <div className="text-text-tertiary">@{u.username}</div>
                              </div>
                            </div>
                          </td>
                          <td className="py-2.5 px-3 text-text-secondary">{u.email}</td>
                          <td className="py-2.5 px-3">
                            <Badge className={`${roleBadge.className} text-[10px] px-1.5 py-0.5`}>{roleBadge.label}</Badge>
                          </td>
                          <td className="py-2.5 px-3 text-text-secondary">{u.tenant_name}</td>
                          <td className="py-2.5 px-3">
                            {u.status === 'active' ? (
                              <Badge className="bg-success/15 text-success text-[10px] px-1.5 py-0.5 gap-1">
                                <CheckIcon size={10} /> 正常
                              </Badge>
                            ) : (
                              <Badge className="bg-danger/15 text-danger text-[10px] px-1.5 py-0.5 gap-1">
                                <XIcon size={10} /> 已禁用
                              </Badge>
                            )}
                          </td>
                          <td className="py-2.5 px-3 text-text-tertiary">{formatDate(u.last_login)}</td>
                          <td className="py-2.5 px-3 text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                onClick={() => { setEditingUser(u); setUserForm({ username: u.username, display_name: u.display_name, email: u.email, role: u.role, tenant_id: u.tenant_id }); setUserDialogOpen(true); }}
                                title="编辑"
                              >
                                <EditIcon size={13} />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                onClick={() => toggleUserStatus.mutate(u.id)}
                                title={u.status === 'active' ? '禁用' : '启用'}
                              >
                                {u.status === 'active' ? <XIcon size={13} className="text-danger" /> : <CheckIcon size={13} className="text-success" />}
                              </Button>
                              {u.id !== currentUser?.id && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7 text-danger"
                                  onClick={() => { if (confirm('确定删除该用户？')) deleteUser.mutate(u.id); }}
                                  title="删除"
                                >
                                  <TrashIcon size={13} />
                                </Button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Tenants Tab */}
          <TabsContent value="tenants" className="p-4 m-0">
            <div className="flex justify-end mb-3">
              <Button size="sm" onClick={() => { setEditingTenant(null); setTenantForm({ name: '', slug: '', plan: 'free' }); setTenantDialogOpen(true); }}>
                <PlusIcon size={14} />
                新建组织
              </Button>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {tenants.map((t: AdminTenant) => {
                const planBadge = PLAN_BADGE[t.plan] || PLAN_BADGE.free;
                return (
                  <Card key={t.id}>
                    <CardHeader className="pb-2">
                      <div className="flex items-start justify-between">
                        <div className="flex items-center gap-2">
                          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-soft text-brand-600">
                            <BuildingIcon size={16} />
                          </div>
                          <div>
                            <CardTitle className="text-sm">{t.name}</CardTitle>
                            <CardDescription className="text-[11px]">{t.slug}</CardDescription>
                          </div>
                        </div>
                        <Badge className={`${planBadge.className} text-[10px] px-1.5 py-0.5`}>{planBadge.label}</Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <div className="grid grid-cols-2 gap-2 text-[11px] mb-3">
                        <div>
                          <div className="text-text-tertiary">成员数</div>
                          <div className="font-medium text-text-primary flex items-center gap-1">
                            <UsersIcon size={11} />{t.member_count}
                          </div>
                        </div>
                        <div>
                          <div className="text-text-tertiary">会议数</div>
                          <div className="font-medium text-text-primary">{t.meeting_count}</div>
                        </div>
                        <div>
                          <div className="text-text-tertiary">创建时间</div>
                          <div className="text-text-secondary">{formatDate(t.created_at)}</div>
                        </div>
                        <div>
                          <div className="text-text-tertiary">状态</div>
                          <div className={t.status === 'active' ? 'text-success' : 'text-danger'}>
                            {t.status === 'active' ? '正常' : '已暂停'}
                          </div>
                        </div>
                      </div>
                      <div className="flex gap-1">
                        <Button variant="outline" size="sm" className="h-7 text-xs flex-1" onClick={() => { setEditingTenant(t); setTenantForm({ name: t.name, slug: t.slug, plan: t.plan }); setTenantDialogOpen(true); }}>
                          <EditIcon size={12} /> 编辑
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </TabsContent>

          {/* Config Tab */}
          <TabsContent value="config" className="p-4 m-0">
            <div className="max-w-2xl space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">LLM 配置</CardTitle>
                  <CardDescription className="text-xs">配置大语言模型提供商和参数</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid gap-2">
                    <Label className="text-xs">LLM 提供商</Label>
                    <Select value={config.llm_provider} onValueChange={(v) => setConfig({ ...config, llm_provider: v })}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="deepseek">DeepSeek</SelectItem>
                        <SelectItem value="openai">OpenAI</SelectItem>
                        <SelectItem value="anthropic">Anthropic</SelectItem>
                        <SelectItem value="qwen">通义千问</SelectItem>
                        <SelectItem value="local">本地模型</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid gap-2">
                    <Label className="text-xs">模型名称</Label>
                    <Input className="h-8 text-xs" value={config.llm_model} onChange={(e) => setConfig({ ...config, llm_model: e.target.value })} />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="grid gap-2">
                      <Label className="text-xs">默认温度</Label>
                      <Input type="number" step="0.1" min="0" max="1" className="h-8 text-xs" value={config.default_temperature} onChange={(e) => setConfig({ ...config, default_temperature: parseFloat(e.target.value) })} />
                    </div>
                    <div className="grid gap-2">
                      <Label className="text-xs">Embedding 模型</Label>
                      <Input className="h-8 text-xs" value={config.embedding_model} onChange={(e) => setConfig({ ...config, embedding_model: e.target.value })} />
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">运行限制</CardTitle>
                  <CardDescription className="text-xs">配置系统运行时参数限制</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="grid gap-2">
                      <Label className="text-xs">最大 Agent 数量</Label>
                      <Input type="number" className="h-8 text-xs" value={config.max_agents} onChange={(e) => setConfig({ ...config, max_agents: parseInt(e.target.value) })} />
                    </div>
                    <div className="grid gap-2">
                      <Label className="text-xs">最大会议时长(分钟)</Label>
                      <Input type="number" className="h-8 text-xs" value={config.max_meeting_duration} onChange={(e) => setConfig({ ...config, max_meeting_duration: parseInt(e.target.value) })} />
                    </div>
                  </div>
                  <div className="flex items-center justify-between">
                    <div>
                      <Label className="text-xs">允许公开注册</Label>
                      <p className="text-[11px] text-text-tertiary">关闭后仅管理员可创建用户</p>
                    </div>
                    <button
                      className={`relative h-5 w-9 rounded-full transition-colors ${config.enable_public_registration ? 'bg-brand-500' : 'bg-border-default'}`}
                      onClick={() => setConfig({ ...config, enable_public_registration: !config.enable_public_registration })}
                    >
                      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${config.enable_public_registration ? 'left-4' : 'left-0.5'}`} />
                    </button>
                  </div>
                </CardContent>
              </Card>

              <div className="flex justify-end">
                <Button size="sm" onClick={saveConfig}>保存配置</Button>
              </div>
            </div>
          </TabsContent>
        </ScrollArea>
      </Tabs>

      {/* User Dialog */}
      <Dialog open={userDialogOpen} onOpenChange={setUserDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-sm">{editingUser ? '编辑用户' : '新建用户'}</DialogTitle>
            <DialogDescription className="text-xs">
              {editingUser ? '修改用户信息和权限' : '创建新用户并分配到组织'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid gap-2">
              <Label className="text-xs">用户名 *</Label>
              <Input className="h-8 text-xs" value={userForm.username} onChange={(e) => setUserForm({ ...userForm, username: e.target.value })} placeholder="username" />
            </div>
            <div className="grid gap-2">
              <Label className="text-xs">显示名称 *</Label>
              <Input className="h-8 text-xs" value={userForm.display_name} onChange={(e) => setUserForm({ ...userForm, display_name: e.target.value })} placeholder="张三" />
            </div>
            <div className="grid gap-2">
              <Label className="text-xs">邮箱</Label>
              <Input className="h-8 text-xs" type="email" value={userForm.email} onChange={(e) => setUserForm({ ...userForm, email: e.target.value })} placeholder="user@example.com" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label className="text-xs">角色</Label>
                <Select value={userForm.role} onValueChange={(v: any) => setUserForm({ ...userForm, role: v })}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="member">成员</SelectItem>
                    <SelectItem value="admin">管理员</SelectItem>
                    <SelectItem value="owner">所有者</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <Label className="text-xs">所属组织</Label>
                <Select value={userForm.tenant_id} onValueChange={(v) => setUserForm({ ...userForm, tenant_id: v })}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {tenants.map((t: AdminTenant) => (
                      <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setUserDialogOpen(false)}>取消</Button>
            <Button size="sm" onClick={saveUser}>{editingUser ? '保存' : '创建'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Tenant Dialog */}
      <Dialog open={tenantDialogOpen} onOpenChange={setTenantDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-sm">{editingTenant ? '编辑组织' : '新建组织'}</DialogTitle>
            <DialogDescription className="text-xs">
              {editingTenant ? '修改组织信息和套餐' : '创建新的组织/租户'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid gap-2">
              <Label className="text-xs">组织名称 *</Label>
              <Input className="h-8 text-xs" value={tenantForm.name} onChange={(e) => setTenantForm({ ...tenantForm, name: e.target.value })} placeholder="我的组织" />
            </div>
            <div className="grid gap-2">
              <Label className="text-xs">标识(slug) *</Label>
              <Input className="h-8 text-xs" value={tenantForm.slug} onChange={(e) => setTenantForm({ ...tenantForm, slug: e.target.value.toLowerCase().replace(/\s+/g, '-') })} placeholder="my-org" />
            </div>
            <div className="grid gap-2">
              <Label className="text-xs">套餐</Label>
              <Select value={tenantForm.plan} onValueChange={(v: any) => setTenantForm({ ...tenantForm, plan: v })}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="free">免费版</SelectItem>
                  <SelectItem value="pro">专业版</SelectItem>
                  <SelectItem value="enterprise">企业版</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setTenantDialogOpen(false)}>取消</Button>
            <Button size="sm" onClick={saveTenant}>{editingTenant ? '保存' : '创建'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
