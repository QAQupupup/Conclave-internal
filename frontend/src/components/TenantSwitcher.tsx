import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../state/AppContext';

export default function TenantSwitcher() {
  const { user, currentTenant, tenants, tenantsLoading, switchTenant, createTenant, demoMode } = useApp();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [saving, setSaving] = useState(false);
  const [switchingId, setSwitchingId] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  // 未登录或演示模式不显示
  if (!user || demoMode) return null;

  const displayName = currentTenant?.name || '未选择组织';
  const roleLabel: Record<string, string> = { owner: '所有者', admin: '管理员', member: '成员' };

  async function handleSwitch(id: number) {
    if (id === user?.tenant_id) { setOpen(false); return; }
    setSwitchingId(id);
    const ok = await switchTenant(id);
    setSwitchingId(null);
    if (ok) setOpen(false);
  }

  async function handleCreate() {
    const name = newName.trim();
    if (!name) return;
    setSaving(true);
    const t = await createTenant(name);
    setSaving(false);
    if (t) {
      setNewName('');
      setCreating(false);
      // 创建后自动切换到新组织
      await handleSwitch(t.id);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') handleCreate();
    if (e.key === 'Escape') { setCreating(false); setNewName(''); }
  }

  return (
    <div style={{ position: 'relative' }} ref={ref}>
      <button
        className="tenant-switcher-btn"
        onClick={() => setOpen((o) => !o)}
        title="切换组织"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01" />
        </svg>
        <span className="tenant-switcher-name">{displayName}</span>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="tenant-switcher-chevron" style={{ transform: open ? 'rotate(180deg)' : undefined, transition: 'transform .15s' }}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div className="tenant-switcher-popup">
          <div className="tenant-switcher-header">
            <span>我的组织</span>
            {tenantsLoading && <span className="tenant-switcher-loading">加载中…</span>}
          </div>
          <div className="tenant-switcher-list">
            {tenants.length === 0 && !tenantsLoading && (
              <div className="tenant-switcher-empty">暂无组织</div>
            )}
            {tenants.map((t) => {
              const isCurrent = t.id === user?.tenant_id;
              const switching = switchingId === t.id;
              return (
                <div
                  key={t.id}
                  className={`tenant-switcher-item${isCurrent ? ' active' : ''}${switching ? ' switching' : ''}`}
                  onClick={() => !switching && handleSwitch(t.id)}
                >
                  <div className="tenant-switcher-item-icon">
                    {t.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="tenant-switcher-item-info">
                    <div className="tenant-switcher-item-name">{t.name}</div>
                    <div className="tenant-switcher-item-meta">
                      {roleLabel[t.role || 'member'] || t.role || '成员'}
                      {t.plan && t.plan !== 'free' && <span className="tenant-plan-badge">{t.plan}</span>}
                    </div>
                  </div>
                  {isCurrent && (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="16" height="16" style={{ color: 'var(--accent, #335c8e)' }}>
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  )}
                  {switching && <span className="tenant-switcher-spinner" />}
                </div>
              );
            })}
          </div>
          {creating ? (
            <div className="tenant-switcher-create-form">
              <input
                type="text"
                placeholder="输入组织名称…"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={handleKeyDown}
                autoFocus
                className="tenant-switcher-input"
              />
              <div className="tenant-switcher-create-actions">
                <button className="tenant-switcher-btn-ghost" onClick={() => { setCreating(false); setNewName(''); }}>取消</button>
                <button className="tenant-switcher-btn-primary" onClick={handleCreate} disabled={saving || !newName.trim()}>
                  {saving ? '创建中…' : '创建'}
                </button>
              </div>
            </div>
          ) : (
            <div className="tenant-switcher-footer">
              <button className="tenant-switcher-new" onClick={() => setCreating(true)}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                创建新组织
              </button>
              <button className="tenant-switcher-new" onClick={() => { setOpen(false); navigate('/settings'); }}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
                组织设置
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
