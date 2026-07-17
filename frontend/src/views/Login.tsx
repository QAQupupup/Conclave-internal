import { useState, useRef, useEffect } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { useApp } from '../state/AppContext';
import { apiLogin } from '../lib/api';

/**
 * 登录页（路由化）
 * - 未登录访问受保护路由 → 重定向到 /app/login?redirect=原路径
 * - 登录成功 → 读取 redirect 参数跳回原页面，无 redirect 则跳 /app 首页
 * - 登录是独立路由页而非弹窗，刷新不丢失登录流程
 *
 * 跳转时机：不依赖 setUser 后的同步 navigate（状态更新是异步的，
 * 守卫此时 user 仍为 null 会把用户弹回登录页）。改为用 useEffect
 * 监听 user 变化：user 一旦变为非 null，立即读取 redirect 跳转，
 * 此时守卫已能看到新的 user 状态，放行通过。
 */
export default function Login() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { user, setUser } = useApp();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const userRef = useRef<HTMLInputElement>(null);

  // 登录成功标志：submit 设置，effect 监听 user 变化后消费
  const [loginSuccess, setLoginSuccess] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => userRef.current?.focus(), 100);
    return () => clearTimeout(t);
  }, []);

  // user 从 null 变为非 null（登录成功）→ 立即跳转
  // 此时守卫能拿到新 user 状态，不会再次重定向回登录页
  useEffect(() => {
    if (user && loginSuccess) {
      const redirect = params.get('redirect');
      // redirect 存在则回原页面；否则跳应用首页（空串 = index 路由）
      navigate(redirect || '', { replace: true });
      setLoginSuccess(false);
    }
  }, [user, loginSuccess, params, navigate]);

  const submit = async () => {
    if (!username.trim() || !password) { setError('请输入用户名和密码'); return; }
    setLoading(true);
    setError('');
    try {
      const data = await apiLogin(username.trim(), password);
      setUser(data.user);
      setLoginSuccess(true);
      setPassword('');
    } catch (e: any) {
      setError(e.message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <span className="brand-dot"></span>
          <span className="brand-name">Conclave</span>
        </div>
        <h3 className="login-title">登录 Conclave</h3>
        <div className="login-form">
          <input
            type="text"
            ref={userRef}
            className="modal-input"
            placeholder="用户名"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            type="password"
            className="modal-input"
            placeholder="密码"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
          />
          {error && <div className="modal-error">{error}</div>}
          <button className="ctrl-btn primary login-submit" disabled={loading} onClick={submit}>
            {loading ? '登录中...' : '登录'}
          </button>
          <Link to="/" className="login-back">返回首页</Link>
        </div>
      </div>
    </div>
  );
}
