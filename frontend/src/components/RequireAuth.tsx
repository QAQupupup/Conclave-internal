import { Navigate, useLocation } from 'react-router-dom';
import { useApp } from '../state/AppContext';
import type { ReactNode } from 'react';

/**
 * 路由守卫：未登录且未在演示模式下重定向到登录页。
 * - 已登录（user 非 null）：正常访问
 * - 演示模式（demoMode=true）：允许访问（展示 mock 数据）
 * - 其他情况：重定向到登录页，并携带 redirect 参数
 */
export default function RequireAuth({ children }: { children: ReactNode }) {
  const { user, authChecked, demoMode } = useApp();
  const location = useLocation();

  // 等待启动时的 token 验证完成，避免闪烁
  if (!authChecked) {
    return <div className="app" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
      <span style={{ color: 'var(--text-3)', fontSize: 13 }}>正在验证登录状态…</span>
    </div>;
  }

  if (!user && !demoMode) {
    const redirect = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?redirect=${redirect}`} replace />;
  }

  return <>{children}</>;
}
