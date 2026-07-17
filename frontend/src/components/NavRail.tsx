import { useApp, type ViewName } from '../state/AppContext';

interface NavItem { view: ViewName; title: string; svg: JSX.Element }

const ICONS: NavItem[] = [
  { view: 'landing', title: '首页', svg: (<><path d="M3 10.5L12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /><path d="M9.5 21v-6h5v6" /></>) },
  { view: 'board', title: '会议看板', svg: (<><circle cx="5" cy="7" r="1" fill="currentColor" stroke="none" /><line x1="9" y1="7" x2="20" y2="7" /><circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" /><line x1="9" y1="12" x2="20" y2="12" /><circle cx="5" cy="17" r="1" fill="currentColor" stroke="none" /><line x1="9" y1="17" x2="20" y2="17" /></>) },
  { view: 'meeting', title: '当前会议', svg: (<><path d="M4 5h16v12H8l-4 4z" /><line x1="8" y1="10" x2="16" y2="10" /><line x1="8" y1="13" x2="13" y2="13" /></>) },
  { view: 'report', title: '会议报告', svg: (<><path d="M6 3h9l4 4v14H6z" /><path d="M14 3v5h5" /><line x1="9" y1="13" x2="16" y2="13" /><line x1="9" y1="17" x2="14" y2="17" /></>) },
  { view: 'models', title: '模型中心', svg: (<><rect x="7" y="7" width="10" height="10" rx="1" /><line x1="10" y1="4" x2="10" y2="7" /><line x1="14" y1="4" x2="14" y2="7" /><line x1="10" y1="17" x2="10" y2="20" /><line x1="14" y1="17" x2="14" y2="20" /><line x1="4" y1="10" x2="7" y2="10" /><line x1="4" y1="14" x2="7" y2="14" /><line x1="17" y1="10" x2="20" y2="10" /><line x1="17" y1="14" x2="20" y2="14" /></>) },
  { view: 'monitor', title: '监控面板', svg: (<path d="M3 12h4l2-6 4 12 2-6h6" />) },
  { view: 'topology', title: '组件联通', svg: (<><circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="12" cy="18" r="2" /><path d="M7 6h10M6.5 7.5L10.5 16M17.5 7.5L13.5 16" /></>) },
];

export default function NavRail() {
  const { view, setView, toggleLog } = useApp();
  return (
    <nav className="nav-rail">
      {ICONS.map((it) => (
        <button
          key={it.view}
          className={`nav-rail-item ${view === it.view ? 'active' : ''}`}
          data-view={it.view}
          onClick={() => setView(it.view)}
          title={it.title}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round">{it.svg}</svg>
        </button>
      ))}
      <div className="nav-rail-spacer"></div>
      <button className="nav-rail-item" onClick={toggleLog} title="日志">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 5h14v14H5z" /><line x1="8" y1="9" x2="16" y2="9" /><line x1="8" y1="12" x2="16" y2="12" /><line x1="8" y1="15" x2="13" y2="15" /></svg>
      </button>
    </nav>
  );
}
