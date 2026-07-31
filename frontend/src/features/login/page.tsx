import * as React from 'react';
import { useNavigate, useLocation } from 'react-router';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Logo } from '@/components/ui/svg-icons';
import { useAuthStore } from '@/stores/auth-slice';
import { api } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';
import { sha256Hash } from '@/lib/crypto';
import type { UserInfo } from '@/types';

interface LoginResponse {
  access_token: string;
  refresh_token?: string;
  token_type: string;
}

export default function LoginPage() {
  const [username, setUsername] = React.useState('admin');
  const [password, setPassword] = React.useState('admin123');
  const [isLoading, setIsLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const navigate = useNavigate();
  const location = useLocation();
  const setAuth = useAuthStore((s) => s.setAuth);
  const { toast } = useToast();

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/board';

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
    navigate(from, { replace: true });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('请输入用户名和密码');
      return;
    }
    setError('');
    setIsLoading(true);
    try {
      // 安全：客户端先做 SHA-256 预哈希，后端永远不接触明文密码
      const clientHash = await sha256Hash(password);
      const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password: clientHash }),
        credentials: 'include',
      });

      if (!res.ok) {
        let msg = '用户名或密码错误';
        try {
          const errData = await res.json();
          if (typeof errData.detail === 'string') {
            msg = errData.detail;
          } else if (Array.isArray(errData.detail)) {
            msg = errData.detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ');
          } else if (errData.message) {
            msg = errData.message;
          }
        } catch {
          if (res.status === 502 || res.status === 504) {
            msg = '无法连接到服务器，请确认后端服务已启动';
          } else if (res.status >= 500) {
            msg = '服务器内部错误，请稍后重试';
          }
        }
        throw new Error(msg);
      }

      const data = await res.json();
      const token = data.access_token;
      // Login response includes user directly
      const user = data.user as UserInfo;

      if (!user) {
        // Fallback: fetch /auth/me if user not in response
        useAuthStore.setState({ token });
        try {
          const meUser = await api.get<UserInfo>('/auth/me');
          setAuth(token, meUser);
        } catch {
          setError('获取用户信息失败');
          useAuthStore.setState({ token: null });
          setIsLoading(false);
          return;
        }
      } else {
        setAuth(token, user);
      }

      toast({ title: '登录成功', description: `欢迎回来，${user?.display_name || user?.username || username}` });
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请稍后重试');
    } finally {
      setIsLoading(false);
    }
  };

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
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="space-y-1.5">
              <label className="text-xs text-text-secondary">用户名</label>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                autoFocus
                disabled={isLoading}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-text-secondary">密码</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                disabled={isLoading}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSubmit(e);
                }}
              />
            </div>
            {error && (
              <div className="rounded-md bg-danger-bg px-2.5 py-2 text-xs text-danger">
                {error}
              </div>
            )}
            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? '登录中...' : '登录'}
            </Button>
          </form>
          <div className="mt-3 flex items-center gap-2">
            <div className="h-px flex-1 bg-border" />
            <span className="text-[10px] text-text-tertiary">或</span>
            <div className="h-px flex-1 bg-border" />
          </div>
          <Button
            type="button"
            variant="outline"
            className="mt-3 w-full"
            onClick={handleDemoLogin}
            disabled={isLoading}
          >
            演示模式（无需后端）
          </Button>
          <p className="mt-2 text-center text-[10px] text-text-tertiary">
            默认账号：admin / admin123
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
