import { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../state/AppContext';
import { CMDK_ITEMS, type CmdkAction } from '../data/mock';

const NAV_ROUTES: Record<string, string> = {
  landing: '/',
  board: '/board',
  meeting: '/meeting',
  report: '/report',
  models: '/models',
  monitor: '/monitor',
  topology: '/topology',
  devops: '/devops',
  settings: '/settings',
};

export default function CommandPalette() {
  const { cmdkOpen, closeCmdk, toggleTheme, toggleLog } = useApp();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const items = useMemo(
    () => CMDK_ITEMS.filter((i) => !filter || i.label.includes(filter)),
    [filter],
  );

  useEffect(() => {
    if (cmdkOpen) {
      setFilter('');
      setSelected(0);
      const t = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [cmdkOpen]);

  useEffect(() => { setSelected(0); }, [filter]);

  if (!cmdkOpen) return null;

  const exec = (action: CmdkAction) => {
    const route = NAV_ROUTES[action];
    if (route) navigate(route);
    else if (action === 'toggleTheme') toggleTheme();
    else if (action === 'toggleLog') toggleLog();
    closeCmdk();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { closeCmdk(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!items.length) return;
      setSelected((s) => (s + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length);
    }
    if (e.key === 'Enter' && items[selected]) exec(items[selected].action);
  };

  return (
    <div className="cmdk-overlay open" id="cmdk-overlay" onClick={(e) => { if (e.target === e.currentTarget) closeCmdk(); }}>
      <div className="cmdk">
        <input
          ref={inputRef}
          className="cmdk-input"
          placeholder="输入命令或搜索…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={onKey}
        />
        <div className="cmdk-list" id="cmdk-list" ref={listRef}>
          {items.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>未找到匹配命令</div>
          ) : items.map((item, i) => (
            <div
              key={item.label}
              className={`cmdk-item ${i === selected ? 'selected' : ''}`}
              onClick={() => exec(item.action)}
              onMouseEnter={() => setSelected(i)}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><path d={item.icon} /></svg>
              <span>{item.label}</span>
              {item.shortcut ? <span className="cmdk-shortcut">{item.shortcut}</span> : null}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
