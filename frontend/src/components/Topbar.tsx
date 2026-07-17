import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../state/AppContext';

export default function Topbar() {
  const { theme, toggleTheme, toggleLog, openCmdk, user, logout } = useApp();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [menuOpen]);

  const initial = (user?.display_name || user?.username || '?')[0] || '?';

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-dot"></span>
        <span className="brand-name">Conclave</span>
      </div>
      <div className="topbar-right">
        <div className="topbar-search" onClick={openCmdk} style={{ cursor: 'pointer' }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"><circle cx="10.5" cy="10.5" r="6.5" /><line x1="15.5" y1="15.5" x2="21" y2="21" /></svg>
          <input type="text" placeholder="搜索或输入命令…" readOnly />
          <span className="kbd">⌘K</span>
        </div>
        <button className="icon-btn" onClick={toggleLog} title="日志">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 5h14v14H5z" /><line x1="8" y1="9" x2="16" y2="9" /><line x1="8" y1="12" x2="16" y2="12" /><line x1="8" y1="15" x2="13" y2="15" /></svg>
        </button>
        <button className="icon-btn" onClick={toggleTheme} title="切换主题">
          {theme === 'dark' ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.5 5.5l1.4 1.4M17.1 17.1l1.4 1.4M5.5 18.5l1.4-1.4M17.1 6.9l1.4-1.4" /></svg>
          )}
        </button>
        <button className="icon-btn" onClick={() => navigate('/settings')} title="设置">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="3.5" /><path d="M5 21c0-4 3-6 7-6s7 2 7 6" /></svg>
        </button>
        <div style={{ position: 'relative' }} ref={menuRef}>
          <button
            className="icon-btn user-btn"
            id="user-btn"
            onClick={() => (user ? setMenuOpen((o) => !o) : navigate('/login'))}
            title="用户"
          >
            {user ? (
              <span className="user-avatar">{initial}</span>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
            )}
            <span>{user ? (user.display_name || user.username) : '登录'}</span>
          </button>
          {menuOpen && user && (
            <div className="user-menu-popup" style={{ position: 'absolute', top: 'calc(100% + 8px)', right: 0 }}>
              <div className="user-menu-header">
                <div className="user-avatar large">{initial}</div>
                <div>
                  <div className="user-menu-name">{user.display_name || user.username}</div>
                  <div className="user-menu-role">{user.role || 'user'}</div>
                </div>
              </div>
              <div className="user-menu-item" onClick={() => { logout(); setMenuOpen(false); navigate('/login'); }}>退出登录</div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
