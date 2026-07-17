import { NavLink, useNavigate } from 'react-router-dom';

const NAV_ITEMS = [
  { key: '', label: '首页', icon: 'home' },
  { key: 'board', label: '会议看板', icon: 'board' },
  { key: 'meeting', label: '当前会议', icon: 'meeting' },
  { key: 'report', label: '会议报告', icon: 'report' },
  { key: 'models', label: '模型中心', icon: 'models' },
  { key: 'monitor', label: '监控面板', icon: 'monitor' },
  { key: 'topology', label: '组件联通', icon: 'topology' },
] as const;

const ICON_PATHS: Record<string, string> = {
  home: 'M3 12L12 3l9 9M5 10v10h4v-6h6v6h4V10',
  board: 'M3 4h7v16H3zM14 4h7v9h-7zM14 15h7v5h-7z',
  meeting: 'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  report: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5',
  models: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5',
  monitor: 'M22 3H2v14h22V3zM8 21h8M12 17v4',
  topology: 'M4 7V4h16v3M9 20h6M12 4v16M7 12h2M15 12h2',
};

function NavIcon({ name }: { name: string }) {
  return (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d={ICON_PATHS[name] || ICON_PATHS.home} />
    </svg>
  );
}

export default function NavRail() {
  const navigate = useNavigate();

  return (
    <nav className="nav-rail">
      {NAV_ITEMS.map((item) => {
        const to = item.key ? `/${item.key}` : '/';
        // "当前会议" 特殊处理：无会议 ID 时跳 /meeting（Meeting 视图内部处理）
        if (item.key === 'meeting') {
          return (
            <button key={item.key} className="nav-btn" onClick={() => navigate('/meeting')} title={item.label}>
              <NavIcon name={item.icon} />
              <span className="nav-label">{item.label}</span>
            </button>
          );
        }
        return (
          <NavLink key={item.key} to={to} end={item.key === ''} className={({ isActive }) => 'nav-btn' + (isActive ? ' active' : '')} title={item.label}>
            <NavIcon name={item.icon} />
            <span className="nav-label">{item.label}</span>
          </NavLink>
        );
      })}
      <div className="nav-spacer"></div>
      <NavLink to="/settings" className={({ isActive }) => 'nav-btn' + (isActive ? ' active' : '')} title="设置">
        <NavIcon name="home" />
        <span className="nav-label">设置</span>
      </NavLink>
    </nav>
  );
}
