import * as React from 'react';
import { useNavigate } from 'react-router';
import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FieldError, FormAlert } from '@/components/ui/form-feedback';
import { Logo } from '@/components/ui/svg-icons';
import { api } from '@/lib/api';
import { sha256Hash } from '@/lib/crypto';

interface SetupStatus {
  needs_setup: boolean;
  has_admin: boolean;
}

interface SetupFormData {
  username: string;
  password: string;
  confirm_password: string;
}

export default function SetupPage() {
  const form = useForm<SetupFormData>({
    defaultValues: { username: '', password: '', confirm_password: '' },
  });
  const { errors, isSubmitting } = form.formState;
  const [setupToken] = React.useState('');
  const [checking, setChecking] = React.useState(true);
  const [needsSetup, setNeedsSetup] = React.useState(false);
  const [serverError, setServerError] = React.useState('');
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

  const handleSubmit = form.handleSubmit(async (data) => {
    setServerError('');
    try {
      // 安全：客户端先做 SHA-256 预哈希，后端永远不接触明文密码
      const clientHash = await sha256Hash(data.password);
      await api.post('/setup', {
        setup_token: setupToken || undefined,
        username: data.username.trim(),
        password: clientHash,
      });
      // Setup successful, redirect to login
      navigate('/login', { replace: true });
    } catch (err) {
      setServerError(err instanceof Error ? err.message : '初始化失败');
    }
  });

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
          <form onSubmit={handleSubmit} noValidate className="space-y-3">
            <div className="space-y-1.5">
              <label htmlFor="setup-username" className="text-xs text-text-secondary">管理员用户名</label>
              <Input
                id="setup-username"
                placeholder="admin"
                disabled={isSubmitting}
                aria-invalid={!!errors.username}
                aria-describedby={errors.username ? 'setup-username-error' : undefined}
                {...form.register('username', {
                  validate: (v) => v.trim().length > 0 || '请填写用户名',
                })}
              />
              <FieldError id="setup-username-error">{errors.username?.message}</FieldError>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="setup-password" className="text-xs text-text-secondary">密码</label>
              <Input
                id="setup-password"
                type="password"
                placeholder="至少 6 位"
                disabled={isSubmitting}
                aria-invalid={!!errors.password}
                aria-describedby={errors.password ? 'setup-password-error' : undefined}
                {...form.register('password', {
                  required: '请填写密码',
                  minLength: { value: 6, message: '密码长度至少 6 位' },
                })}
              />
              <FieldError id="setup-password-error">{errors.password?.message}</FieldError>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="setup-confirm-password" className="text-xs text-text-secondary">确认密码</label>
              <Input
                id="setup-confirm-password"
                type="password"
                placeholder="再次输入密码"
                disabled={isSubmitting}
                aria-invalid={!!errors.confirm_password}
                aria-describedby={errors.confirm_password ? 'setup-confirm-password-error' : undefined}
                {...form.register('confirm_password', {
                  required: '请再次输入密码',
                  validate: (v, values) => v === values.password || '两次输入的密码不一致',
                })}
              />
              <FieldError id="setup-confirm-password-error">{errors.confirm_password?.message}</FieldError>
            </div>
            <FormAlert>{serverError}</FormAlert>
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? '初始化中...' : '创建管理员账号'}
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
