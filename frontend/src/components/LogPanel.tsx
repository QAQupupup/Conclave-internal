import { useApp } from '../state/AppContext';

const TABS = ['ALL', 'INFO', 'DEBUG', 'WARN', 'ERROR'] as const;

export default function LogPanel() {
  const { logOpen, logFilter, setLogFilter, logs, clearLogs, toggleLog } = useApp();

  const counts: Record<string, number> = { ALL: logs.length };
  for (const l of logs) counts[l.level] = (counts[l.level] || 0) + 1;

  const shown = logFilter === 'ALL' ? logs : logs.filter((l) => l.level === logFilter);

  if (!logOpen) return null;

  return (
    <div className="log-panel open" id="log-panel">
      <div className="log-head">
        {TABS.map((t) => (
          <span
            key={t}
            className={`log-tab ${logFilter === t ? 'active' : ''}`}
            onClick={() => setLogFilter(t)}
          >
            {t}<span className="log-tab-count">{counts[t] || 0}</span>
          </span>
        ))}
        <div className="log-actions">
          <span className="log-action" onClick={clearLogs}>清空</span>
          <span className="log-action" onClick={toggleLog}>关闭</span>
        </div>
      </div>
      <div className="log-body" id="log-body">
        {shown.length === 0 ? (
          <span className="log-line"><span className="log-msg" style={{ color: 'var(--text-3)' }}>暂无日志</span></span>
        ) : shown.map((l, i) => (
          <span className="log-line" key={i}>
            <span className="log-time">{l.time}</span>{' '}
            <span className={`log-level ${l.level}`}>{l.level.padEnd(5)}</span>{' '}
            <span className="log-msg">{l.msg}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
