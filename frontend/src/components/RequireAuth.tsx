import { Navigate, useLocation } from 'react-router-dom';
import { useApp } from '../state/AppContext';
import type { ReactNode } from 'react';

/**
 * 路由守卫：未登录用户重定向到登录页，并携带 redirect 参数记录原路径。
 * 登录成功后登录页读取 redirect 参数跳回原页面。
 *
 * 判定依据：user 状态非 null（AppContext 启动时已通过 apiMe 验证 token 有效性）。
 * token 过期场景由全局 401 拦截器处理（设 authExpired → 触发重定向）。
 */
export default function RequireAuth({ children }: { children: ReactNode }) {
  const { user, authChecked } = useApp();
  const location = useLocation();

  // 等待启动时的 token 验证完成，避免闪烁
  if (!authChecked) {
    return <div className="app" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
      <span style={{ color: 'var(--text-3)', fontSize: 13 }}>正在验证登录状态…</span>
    </div>;
  }

  if (!user) {
    const redirect = encodeURIComponent(location.pathname + location.search);
    // basename="/app" 已由 BrowserRouter 处理，此处 to 用相对 /login 即可，
    // 否则 /app/login 会被拼成 /app/app/login
    return <Navigate to={`/login?redirect=${redirect}`} replace />;
  }

  return <>{children}</>;
}
