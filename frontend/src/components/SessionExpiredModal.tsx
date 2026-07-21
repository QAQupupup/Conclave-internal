import { useApp } from '../state/AppContext';

/**
 * 会话过期提示弹窗
 * 由全局 401 拦截器触发（authExpired=true）
 * 显示"登录已过期"提示，App 根层会自动跳转到登录页
 */
export default function SessionExpiredModal() {
  return (
    <div className="modal-overlay show" style={{ zIndex: 2000 }}>
      <div className="modal-card">
        <div className="modal-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" />
          </svg>
        </div>
        <div className="modal-title">登录已过期</div>
        <div className="modal-desc">您的登录状态已失效，正在跳转到登录页面…</div>
        <div className="modal-retry" style={{ display: 'flex' }}>
          <span className="spinner" style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid var(--line-2)', borderTopColor: 'var(--accent-2)', borderRadius: '50%', animation: 'spin .7s linear infinite' }}></span>
          正在跳转…
        </div>
      </div>
    </div>
  );
}
