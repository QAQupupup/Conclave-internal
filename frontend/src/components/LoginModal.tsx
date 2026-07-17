import { useState, useEffect, useRef } from 'react';
import { useApp } from '../state/AppContext';
import { apiLogin } from '../lib/api';

export default function LoginModal() {
  const { loginOpen, closeLogin } = useApp();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const userRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (loginOpen) {
      setError('');
      const t = setTimeout(() => userRef.current?.focus(), 100);
      return () => clearTimeout(t);
    }
  }, [loginOpen]);

  if (!loginOpen) return null;

  const submit = async () => {
    if (!username.trim() || !password) { setError('请输入用户名和密码'); return; }
    setLoading(true);
    setError('');
    try {
      await apiLogin(username.trim(), password);
      closeLogin();
      setPassword('');
    } catch (e: any) {
      setError(e.message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay show" id="login-modal" onClick={(e) => { if (e.target === e.currentTarget) closeLogin(); }}>
      <div className="modal-card">
        <div className="modal-header">
          <h3>登录 Conclave</h3>
          <span className="modal-close" onClick={closeLogin}>&times;</span>
        </div>
        <div className="modal-body">
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
        </div>
        <div className="modal-footer">
          <button className="ctrl-btn" onClick={closeLogin}>取消</button>
          <button className="ctrl-btn primary" disabled={loading} onClick={submit}>
            {loading ? '登录中...' : '登录'}
          </button>
        </div>
      </div>
    </div>
  );
}
