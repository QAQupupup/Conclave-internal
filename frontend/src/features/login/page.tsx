import * as React from 'react';
import { useNavigate, useLocation } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FieldError, FormAlert } from '@/components/ui/form-feedback';
import { Logo } from '@/components/ui/svg-icons';
import { useAuthStore } from '@/stores/auth-slice';
import { api } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';
import { sha256Hash } from '@/lib/crypto';
import type { UserInfo } from '@/types';

interface LoginFormData {
  username: string;
  password: string;
}

export default function LoginPage() {
  const form = useForm<LoginFormData>({
    defaultValues: {
      username: import.meta.env.DEV ? 'admin' : '',
      password: import.meta.env.DEV ? 'admin123' : '',
    },
  });
  const { errors, isSubmitting } = form.formState;
  // 服务端/网络错误不归属单一字段，用表单级横幅展示
  const [serverError, setServerError] = React.useState('');
  const navigate = useNavigate();
  const location = useLocation();
  const setAuth = useAuthStore((s) => s.setAuth);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/board';

  // If the user was redirected here because session recovery (hydration) failed,
  // show a toast explaining what happened instead of silently dropping them on
  // the login form.
  React.useEffect(() => {
    try {
      if (sessionStorage.getItem('conclave:auth-hydration-failed') === '1') {
        sessionStorage.removeItem('conclave:auth-hydration-failed');
        toast({
          title: '会话恢复失败',
          description: '登录状态无法自动恢复，请重新登录',
          variant: 'destructive',
        });
      }
    } catch {
      // sessionStorage unavailable (private mode, etc.) — skip silently
    }
  }, [toast]);

  // Demo/Dev mode login with mock data
  const handleDemoLogin = () => {
    const mockUser: UserInfo = {
      id: 'demo-user-001',
      username: 'admin',
      display_name: '演示管理员',
      email: 'admin@conclave.demo',
      role: 'admin',
      tenant_id: 'tenant-default',
      tenants: [
        { id: 'tenant-default', name: '默认组织', role: 'owner' },
        { id: 'tenant-research', name: '研究团队', role: 'admin' },
      ],
    };
    setAuth('demo-token-' + Date.now(), mockUser);
    toast({ title: '演示模式', description: '已使用演示账号登录，部分功能使用模拟数据' });
    queryClient.clear();
    navigate(from, { replace: true });
  };

  const handleSubmit = form.handleSubmit(async (data) => {
    setServerError('');
    try {
      // 安全：客户端先做 SHA-256 预哈希，后端永远不接触明文密码
      const clientHash = await sha256Hash(data.password);
      const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: data.username.trim(), password: clientHash }),
        credentials: 'include',
      });

      if (!res.ok) {
        let msg = '用户名或密码错误';
        try {
          const errData = await res.json();
          if (typeof errData.detail === 'string') {
            msg = errData.detail;
          } else if (Array.isArray(errData.detail)) {
            msg = errData.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ');
          } else if (errData.message) {
            msg = errData.message;
          }
        } catch {
          if (res.status === 502 || res.status === 504) {
            msg = import.meta.env.DEV ? '无法连接到服务器，请确认后端服务已启动' : '无法连接到服务，请稍后重试';
          } else if (res.status >= 500) {
            msg = '服务器内部错误，请稍后重试';
          }
        }
        throw new Error(msg);
      }

      const payload = await res.json();
      const token = payload.access_token;
      // Login response includes user directly
      const user = payload.user as UserInfo;

      if (!user) {
        // Fallback: fetch /auth/me if user not in response
        useAuthStore.setState({ token });
        try {
          const meRes = await api.get<UserInfo | { user: UserInfo }>('/auth/me');
          const meUser: UserInfo = (meRes as { user?: UserInfo }).user ?? (meRes as UserInfo);
          // 确保 tenants 是数组
          if (meUser && !Array.isArray(meUser.tenants)) {
            meUser.tenants = [];
          }
          // 确保 tenant_id 不为 null
          if (meUser && meUser.tenant_id == null) {
            meUser.tenant_id = '';
          }
          setAuth(token, meUser);
          toast({ title: '登录成功', description: `欢迎回来，${meUser.display_name || meUser.username || data.username}` });
        } catch {
          setServerError('获取用户信息失败');
          useAuthStore.setState({ token: null });
          return;
        }
      } else {
        // 确保 tenants 是数组
        if (!Array.isArray(user.tenants)) {
          user.tenants = [];
        }
        // 确保 tenant_id 不为 null
        if (user.tenant_id == null) {
          user.tenant_id = '';
        }
        setAuth(token, user);
        toast({ title: '登录成功', description: `欢迎回来，${user.display_name || user.username || data.username}` });
      }

      queryClient.clear();
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof TypeError && err.message.includes('fetch')) {
        setServerError(import.meta.env.DEV ? '无法连接到服务器，请确认后端服务已启动' : '无法连接到服务，请检查网络连接');
      } else {
        setServerError(err instanceof Error ? err.message : '登录失败，请稍后重试');
      }
    }
  });

  return (
    <div className="flex h-screen items-center justify-center bg-bg-secondary p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center">
            <Logo size={36} />
          </div>
          <CardTitle className="text-base">登录 Conclave</CardTitle>
          <CardDescription className="text-xs">AI 智库 · 多 Agent 协同探索系统</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} noValidate className="space-y-3">
            <div className="space-y-1.5">
              <label htmlFor="login-username" className="text-xs text-text-secondary">用户名</label>
              <Input
                id="login-username"
                placeholder="admin"
                disabled={isSubmitting}
                aria-invalid={!!errors.username}
                aria-describedby={errors.username ? 'login-username-error' : undefined}
                {...form.register('username', {
                  validate: (v) => v.trim().length > 0 || '请输入用户名',
                })}
              />
              <FieldError id="login-username-error">{errors.username?.message}</FieldError>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="login-password" className="text-xs text-text-secondary">密码</label>
              <Input
                id="login-password"
                type="password"
                placeholder="••••••••"
                disabled={isSubmitting}
                aria-invalid={!!errors.password}
                aria-describedby={errors.password ? 'login-password-error' : undefined}
                {...form.register('password', {
                  validate: (v) => v.trim().length > 0 || '请输入密码',
                })}
              />
              <FieldError id="login-password-error">{errors.password?.message}</FieldError>
            </div>
            <FormAlert>{serverError}</FormAlert>
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? '登录中...' : '登录'}
            </Button>
          </form>
          <div className="mt-3 flex items-center gap-2">
            <div className="h-px flex-1 bg-border" />
            <span className="text-[10px] text-text-tertiary">或</span>
            <div className="h-px flex-1 bg-border" />
          </div>
          {import.meta.env.DEV && (
            <>
              <Button
                type="button"
                variant="outline"
                className="mt-3 w-full"
                onClick={handleDemoLogin}
                disabled={isSubmitting}
              >
                演示模式（无需后端）
              </Button>
              <p className="mt-2 text-center text-[10px] text-text-tertiary">
                默认账号：admin / admin123
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
