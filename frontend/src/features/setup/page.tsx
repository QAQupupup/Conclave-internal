import * as React from 'react';
import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Logo } from '@/components/ui/svg-icons';
import { api } from '@/lib/api';
import { useAuthStore } from '@/stores';
import { sha256Hash } from '@/lib/crypto';

interface SetupStatus {
  needs_setup: boolean;
  has_admin: boolean;
}

export default function SetupPage() {
  const [username, setUsername] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [confirmPassword, setConfirmPassword] = React.useState('');
  const [setupToken, setSetupToken] = React.useState('');
  const [isLoading, setIsLoading] = React.useState(false);
  const [checking, setChecking] = React.useState(true);
  const [needsSetup, setNeedsSetup] = React.useState(false);
  const [error, setError] = React.useState('');
  const navigate = useNavigate();

  React.useEffect(() => {
    api.get<SetupStatus>('/setup/status')
      .then((status) => {
        setNeedsSetup(status.needs_setup);
        // If no setup needed, redirect to login
        if (!status.needs_setup) {
          navigate('/login', { replace: true });
        }
      })
      .catch(() => {
        // If can't reach setup status, show setup page anyway
        setNeedsSetup(true);
      })
      .finally(() => setChecking(false));
  }, [navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('请填写用户名和密码');
      return;
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }
    if (password.length < 6) {
      setError('密码长度至少 6 位');
      return;
    }
    setError('');
    setIsLoading(true);
    try {
      // 安全：客户端先做 SHA-256 预哈希，后端永远不接触明文密码
      const clientHash = await sha256Hash(password);
      await api.post('/setup', {
        setup_token: setupToken || undefined,
        username: username.trim(),
        password: clientHash,
      });
      // Setup successful, redirect to login
      navigate('/login', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : '初始化失败');
    } finally {
      setIsLoading(false);
    }
  };

  if (checking) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-secondary">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-border-default border-t-brand-500" />
      </div>
    );
  }

  if (!needsSetup) {
    return null;
  }

  return (
    <div className="flex h-screen items-center justify-center bg-bg-secondary p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center">
            <Logo size={36} />
          </div>
          <CardTitle className="text-base">初始化 Conclave</CardTitle>
          <CardDescription className="text-xs">创建管理员账号以开始使用</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="space-y-1.5">
              <label className="text-xs text-text-secondary">管理员用户名</label>
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
                placeholder="至少 6 位"
                disabled={isLoading}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-text-secondary">确认密码</label>
              <Input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="再次输入密码"
                disabled={isLoading}
              />
            </div>
            {error && (
              <div className="rounded-md bg-danger-bg px-2.5 py-2 text-xs text-danger">{error}</div>
            )}
            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? '初始化中...' : '创建管理员账号'}
            </Button>
            <p className="text-center text-[11px] text-text-tertiary">
              已有账号？
              <button
                type="button"
                className="ml-1 text-brand-500 hover:underline"
                onClick={() => navigate('/login')}
              >
                去登录
              </button>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
