import * as React from 'react';
import { Navigate } from 'react-router';
import { useAuthStore } from '@/stores/auth-slice';
import { Card, CardContent } from '@/components/ui/card';
import { Lock } from 'lucide-react';

interface AdminRouteProps {
  children: React.ReactNode;
}

/**
 * 管理员路由守卫：
 * - 未登录用户：由 ProtectedRoute 处理跳转到 /login
 * - 已登录但非管理员：显示权限不足提示
 * - 管理员：正常渲染子页面
 */
export function AdminRoute({ children }: AdminRouteProps) {
  const user = useAuthStore((s) => s.user);

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  const isAdmin =
    user.system_role === 'system_owner' ||
    user.system_role === 'system_admin' ||
    user.role === 'admin' ||
    user.role === 'owner' ||
    user.role === 'system_admin' ||
    user.role === 'system_owner';

  if (!isAdmin) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] p-8">
        <Card className="max-w-md">
          <CardContent className="pt-6 text-center space-y-3">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-danger-bg text-danger">
              <Lock size={22} />
            </div>
            <h2 className="text-base font-medium text-text-primary">权限不足</h2>
            <p className="text-xs text-text-tertiary leading-relaxed">
              该页面仅对系统管理员开放。如果您需要访问管理功能，请联系您的系统管理员。
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return <>{children}</>;
}
