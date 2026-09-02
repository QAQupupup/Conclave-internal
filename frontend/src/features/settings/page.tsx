import * as React from 'react';
import { useForm } from 'react-hook-form';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { FieldError } from '@/components/ui/form-feedback';
import { Separator } from '@/components/ui/separator';
import {
  UserIcon,
  SettingsIcon,
  SunIcon,
  MoonIcon,
  MonitorIcon,
  LogOutIcon,
  SpinnerIcon,
  BuildingIcon,
} from '@/components/ui/svg-icons';
import { useAuthStore } from '@/stores/auth-slice';
import { api } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';
import { useTheme } from '@/providers/theme-context';
import { sha256Hash } from '@/lib/crypto';

// ===== Form data types =====
interface ProfileFormData {
  display_name: string;
}

interface PasswordFormData {
  old_password: string;
  new_password: string;
  confirm_password: string;
}

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const setUser = useAuthStore((s) => s.setUser);
  const { theme, setTheme, resolvedTheme } = useTheme();
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // ===== Profile form =====
  const profileForm = useForm<ProfileFormData>({
    defaultValues: {
      display_name: user?.display_name || '',
    },
    values: React.useMemo(() => ({ display_name: user?.display_name || '' }), [user?.display_name]),
  });

  const profileMutation = useMutation({
    mutationFn: (data: ProfileFormData) =>
      api.put('/auth/profile', { display_name: data.display_name }),
    onSuccess: (_data, variables) => {
      if (user) {
        setUser({ ...user, display_name: variables.display_name });
      }
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] });
      toast({ title: '个人资料已更新', variant: 'success' });
      profileForm.reset({ display_name: variables.display_name });
    },
    onError: (err: Error) => {
      toast({
        title: '更新失败',
        description: err.message || '请稍后重试',
        variant: 'error',
      });
    },
  });

  const onProfileSubmit = profileForm.handleSubmit((data) => {
    profileMutation.mutate(data);
  });

  // ===== Password form =====
  const passwordForm = useForm<PasswordFormData>({
    defaultValues: { old_password: '', new_password: '', confirm_password: '' },
  });

  const passwordMutation = useMutation({
    mutationFn: async (data: PasswordFormData) => {
      // 安全：客户端先做 SHA-256 预哈希，后端永远不接触明文密码
      const [oldHash, newHash] = await Promise.all([
        sha256Hash(data.old_password),
        sha256Hash(data.new_password),
      ]);
      return api.post('/auth/change-password', {
        old_password: oldHash,
        new_password: newHash,
      });
    },
    onSuccess: () => {
      toast({ title: '密码修改成功', variant: 'success' });
      passwordForm.reset();
    },
    onError: (err: Error) => {
      toast({
        title: '密码修改失败',
        description: err.message || '请检查原密码是否正确',
        variant: 'error',
      });
    },
  });

  const onPasswordSubmit = passwordForm.handleSubmit((data) => {
    // 字段校验（必填/长度/两次一致）已全部收敛到 register 规则，此处只处理提交
    passwordMutation.mutate(data);
  });

  // ===== Theme option click =====
  const handleThemeChange = (t: 'light' | 'dark' | 'system') => {
    setTheme(t);
    toast({
      title: '主题已切换',
      description:
        t === 'light' ? '已切换到浅色模式' : t === 'dark' ? '已切换到深色模式' : '已跟随系统主题',
      variant: 'default',
    });
  };

  // ===== Tenant info =====
  const currentTenant = user?.tenants?.find((t) => t.id === user.tenant_id);

  return (
    <div className="mx-auto max-w-2xl pt-6 px-8 pb-8">
      {/* Page header */}
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-500">
          <SettingsIcon size={20} />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">设置</h1>
          <p className="text-sm text-text-secondary">管理你的账户、外观和偏好</p>
        </div>
      </div>

      <Tabs defaultValue="profile" className="w-full">
        <TabsList className="mb-4 w-full justify-start bg-bg-tertiary p-1">
          <TabsTrigger value="profile" className="flex items-center gap-1.5">
            <UserIcon size={14} />
            个人资料
          </TabsTrigger>
          <TabsTrigger value="password" className="flex items-center gap-1.5">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            修改密码
          </TabsTrigger>
          <TabsTrigger value="appearance" className="flex items-center gap-1.5">
            {resolvedTheme === 'dark' ? <MoonIcon size={14} /> : <SunIcon size={14} />}
            外观
          </TabsTrigger>
          <TabsTrigger value="about" className="flex items-center gap-1.5">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 16v-4M12 8h.01" />
            </svg>
            关于
          </TabsTrigger>
        </TabsList>

        {/* ===== Profile Tab ===== */}
        <TabsContent value="profile">
          <Card>
            <CardHeader>
              <CardTitle>个人资料</CardTitle>
              <CardDescription>查看和修改你的基本信息</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* Username (readonly) */}
              <div className="space-y-2">
                <Label htmlFor="username">用户名</Label>
                <Input
                  id="username"
                  value={user?.username || ''}
                  readOnly
                  disabled
                  className="bg-bg-tertiary text-text-secondary"
                />
                <p className="text-xs text-text-tertiary">用户名不可修改</p>
              </div>

              <Separator />

              {/* Display name (editable) */}
              <form onSubmit={onProfileSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="display_name">显示名称</Label>
                  <Input
                    id="display_name"
                    placeholder="输入显示名称"
                    aria-invalid={!!profileForm.formState.errors.display_name}
                    aria-describedby={profileForm.formState.errors.display_name ? 'display-name-error' : undefined}
                    {...profileForm.register('display_name', {
                      required: '显示名称不能为空',
                      minLength: { value: 1, message: '显示名称不能为空' },
                    })}
                  />
                  <FieldError id="display-name-error">
                    {profileForm.formState.errors.display_name?.message}
                  </FieldError>
                </div>

                {/* Tenant info */}
                {currentTenant && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <Label className="flex items-center gap-1.5">
                        <BuildingIcon size={13} />
                        当前组织
                      </Label>
                      <div className="rounded-md border border-border-default bg-bg-tertiary px-3 py-2 text-sm text-text-primary">
                        {currentTenant.name}
                        <span className="ml-2 text-xs text-text-tertiary">
                          ({currentTenant.role === 'owner' ? '所有者' : currentTenant.role === 'admin' ? '管理员' : '成员'})
                        </span>
                      </div>
                      {user?.tenants && user.tenants.length > 1 && (
                        <p className="text-xs text-text-tertiary">
                          你属于 {user.tenants.length} 个组织，可在侧边栏切换
                        </p>
                      )}
                    </div>
                  </>
                )}

                <div className="flex justify-end pt-2">
                  <Button
                    type="submit"
                    disabled={profileMutation.isPending || !profileForm.formState.isDirty}
                  >
                    {profileMutation.isPending && <SpinnerIcon size={14} />}
                    保存修改
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ===== Password Tab ===== */}
        <TabsContent value="password">
          <Card>
            <CardHeader>
              <CardTitle>修改密码</CardTitle>
              <CardDescription>定期修改密码有助于保护账户安全</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={onPasswordSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="old_password">原密码</Label>
                  <Input
                    id="old_password"
                    type="password"
                    placeholder="输入当前密码"
                    aria-invalid={!!passwordForm.formState.errors.old_password}
                    aria-describedby={passwordForm.formState.errors.old_password ? 'old-password-error' : undefined}
                    {...passwordForm.register('old_password', { required: '请输入原密码' })}
                  />
                  <FieldError id="old-password-error">
                    {passwordForm.formState.errors.old_password?.message}
                  </FieldError>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="new_password">新密码</Label>
                  <Input
                    id="new_password"
                    type="password"
                    placeholder="输入新密码（至少 6 位）"
                    aria-invalid={!!passwordForm.formState.errors.new_password}
                    aria-describedby={passwordForm.formState.errors.new_password ? 'new-password-error' : undefined}
                    {...passwordForm.register('new_password', {
                      required: '请输入新密码',
                      minLength: { value: 6, message: '新密码长度至少 6 位' },
                    })}
                  />
                  <FieldError id="new-password-error">
                    {passwordForm.formState.errors.new_password?.message}
                  </FieldError>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="confirm_password">确认新密码</Label>
                  <Input
                    id="confirm_password"
                    type="password"
                    placeholder="再次输入新密码"
                    aria-invalid={!!passwordForm.formState.errors.confirm_password}
                    aria-describedby={passwordForm.formState.errors.confirm_password ? 'confirm-password-error' : undefined}
                    {...passwordForm.register('confirm_password', {
                      required: '请确认新密码',
                      validate: (v, values) => v === values.new_password || '两次输入的新密码不一致',
                    })}
                  />
                  <FieldError id="confirm-password-error">
                    {passwordForm.formState.errors.confirm_password?.message}
                  </FieldError>
                </div>

                <div className="flex justify-end pt-2">
                  <Button
                    type="submit"
                    disabled={passwordMutation.isPending}
                  >
                    {passwordMutation.isPending && <SpinnerIcon size={14} />}
                    修改密码
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ===== Appearance Tab ===== */}
        <TabsContent value="appearance">
          <Card>
            <CardHeader>
              <CardTitle>外观</CardTitle>
              <CardDescription>选择你偏好的主题模式</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="space-y-2">
                <Label>主题模式</Label>
                <div className="grid grid-cols-3 gap-3">
                  {/* Light */}
                  <button
                    type="button"
                    onClick={() => handleThemeChange('light')}
                    className={`flex flex-col items-center gap-2 rounded-lg border p-4 transition-all hover:bg-bg-tertiary ${
                      theme === 'light'
                        ? 'border-brand-500 bg-brand-500/5 ring-2 ring-brand-500/20'
                        : 'border-border-default bg-bg-primary'
                    }`}
                  >
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bg-tertiary text-text-primary">
                      <SunIcon size={20} />
                    </div>
                    <span className="text-sm font-medium text-text-primary">浅色</span>
                    {theme === 'light' && (
                      <span className="text-xs text-brand-500">当前使用</span>
                    )}
                  </button>

                  {/* Dark */}
                  <button
                    type="button"
                    onClick={() => handleThemeChange('dark')}
                    className={`flex flex-col items-center gap-2 rounded-lg border p-4 transition-all hover:bg-bg-tertiary ${
                      theme === 'dark'
                        ? 'border-brand-500 bg-brand-500/5 ring-2 ring-brand-500/20'
                        : 'border-border-default bg-bg-primary'
                    }`}
                  >
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bg-tertiary text-text-primary">
                      <MoonIcon size={20} />
                    </div>
                    <span className="text-sm font-medium text-text-primary">深色</span>
                    {theme === 'dark' && (
                      <span className="text-xs text-brand-500">当前使用</span>
                    )}
                  </button>

                  {/* System */}
                  <button
                    type="button"
                    onClick={() => handleThemeChange('system')}
                    className={`flex flex-col items-center gap-2 rounded-lg border p-4 transition-all hover:bg-bg-tertiary ${
                      theme === 'system'
                        ? 'border-brand-500 bg-brand-500/5 ring-2 ring-brand-500/20'
                        : 'border-border-default bg-bg-primary'
                    }`}
                  >
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-bg-tertiary text-text-primary">
                      <MonitorIcon size={20} />
                    </div>
                    <span className="text-sm font-medium text-text-primary">跟随系统</span>
                    {theme === 'system' && (
                      <span className="text-xs text-brand-500">当前使用</span>
                    )}
                  </button>
                </div>
              </div>

              <Separator />

              <div className="text-xs text-text-tertiary">
                当前生效模式：{resolvedTheme === 'dark' ? '深色' : '浅色'}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ===== About Tab ===== */}
        <TabsContent value="about">
          <Card>
            <CardHeader>
              <CardTitle>关于 Conclave</CardTitle>
              <CardDescription>AI 智库 · 多 Agent 协同探索系统</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-4 rounded-lg bg-bg-tertiary p-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-brand-500/10">
                  <svg width="28" height="28" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="8" cy="10" r="3" fill="var(--color-brand-500)" fillOpacity="0.9" />
                    <circle cx="24" cy="10" r="3" fill="var(--color-brand-400)" fillOpacity="0.9" />
                    <circle cx="16" cy="24" r="3" fill="var(--color-accent-purple)" fillOpacity="0.9" />
                    <line x1="10.5" y1="11.5" x2="21.5" y2="11.5" stroke="var(--color-brand-500)" strokeWidth="1.5" strokeOpacity="0.4" />
                    <line x1="9" y1="12.5" x2="14" y2="21.5" stroke="var(--color-brand-500)" strokeWidth="1.5" strokeOpacity="0.4" />
                    <line x1="23" y1="12.5" x2="18" y2="21.5" stroke="var(--color-brand-400)" strokeWidth="1.5" strokeOpacity="0.4" />
                    <circle cx="16" cy="15" r="2" fill="var(--color-brand-500)" fillOpacity="0.2" />
                    <circle cx="16" cy="15" r="1" fill="var(--color-brand-500)" />
                  </svg>
                </div>
                <div>
                  <div className="text-base font-semibold text-text-primary">Conclave</div>
                  <div className="text-sm text-text-secondary">版本 v3.0</div>
                </div>
              </div>

              <div className="space-y-2 text-sm text-text-secondary">
                <p>
                  Conclave 是一个多 Agent 协同的 AI 智库探索系统，通过角色化 Agent 协作（主持人、澄清者、
                  队内探索者、跨队探索者、证据核查者、仲裁者、产出者），帮助你对复杂问题进行系统性的深度探索。
                </p>
              </div>

              <Separator />

              <div className="grid grid-cols-2 gap-4 text-xs text-text-tertiary">
                <div>
                  <div className="font-medium text-text-secondary">技术栈</div>
                  <div>Python 3.12 + FastAPI</div>
                  <div>React 19 + TypeScript</div>
                  <div>PostgreSQL + pgvector</div>
                </div>
                <div>
                  <div className="font-medium text-text-secondary">核心能力</div>
                  <div>多 Agent 协同推理</div>
                  <div>RAG 知识检索</div>
                  <div>结构化论点树产出</div>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* ===== Logout Section ===== */}
      <div className="mt-6">
        <Card className="border-danger/20">
          <CardContent className="flex items-center justify-between p-4">
            <div className="space-y-1">
              <div className="text-sm font-medium text-text-primary">退出登录</div>
              <div className="text-xs text-text-tertiary">退出当前账户，返回登录页面</div>
            </div>
            <Button
              variant="destructive"
              onClick={() => {
                logout();
              }}
            >
              <LogOutIcon size={14} />
              退出登录
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
