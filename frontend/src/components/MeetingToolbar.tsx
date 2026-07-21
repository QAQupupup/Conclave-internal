import { useApp, type CtxType } from '../state/AppContext';
import { STAGES } from '../data/mock';

const CTX_BTNS: { type: CtxType; tip: string; badge?: string; svg: JSX.Element }[] = [
  { type: 'overview', tip: '议题概览', svg: (<><circle cx="12" cy="12" r="9" /><line x1="12" y1="8" x2="12" y2="12" /><circle cx="12" cy="16" r="0.5" fill="currentColor" /></>) },
  { type: 'evidence', tip: '证据库', badge: '12', svg: (<><path d="M6 3h9l4 4v14H6z" /><path d="M14 3v5h5" /><path d="M9 12l2 2 4-4" /></>) },
  { type: 'artifact', tip: '产出物', svg: (<><rect x="5" y="3" width="14" height="18" rx="1" /><line x1="9" y1="8" x2="15" y2="8" /><line x1="9" y1="12" x2="15" y2="12" /><line x1="9" y1="16" x2="13" y2="16" /></>) },
  { type: 'token', tip: 'Token 与成本', badge: '48k', svg: (<path d="M3 12h4l2-6 4 12 2-6h6" />) },
  { type: 'model', tip: '模型调度', svg: (<><rect x="7" y="7" width="10" height="10" rx="1" /><line x1="10" y1="4" x2="10" y2="7" /><line x1="14" y1="4" x2="14" y2="7" /><line x1="10" y1="17" x2="10" y2="20" /><line x1="14" y1="17" x2="14" y2="20" /><line x1="4" y1="10" x2="7" y2="10" /><line x1="4" y1="14" x2="7" y2="14" /><line x1="17" y1="10" x2="20" y2="10" /><line x1="17" y1="14" x2="20" y2="14" /></>) },
];

export default function MeetingToolbar() {
  const { meeting, ctx, openCtx, closeCtx, pauseMeeting, abortMeeting, toggleIntervene } = useApp();
  const current = meeting.stage;

  const onCtxClick = (type: CtxType) => {
    if (ctx.open && ctx.type === type) closeCtx();
    else openCtx(type);
  };

  return (
    <aside className="meeting-toolbar" id="meeting-toolbar">
      <div className="toolbar-stages" id="toolbar-stages">
        {STAGES.map((s, i) => (
          <div key={s.key} style={{ display: 'contents' }}>
            <div className={`toolbar-stage-dot ${i < current ? 'done' : i === current ? 'current' : ''}`}>
              <span className="toolbar-stage-tip">{s.name}</span>
            </div>
            {i < STAGES.length - 1 && (
              <div className={`toolbar-stage-line ${i < current ? 'done' : ''}`}></div>
            )}
          </div>
        ))}
      </div>
      <div className="toolbar-divider"></div>
      <div className="toolbar-group">
        {CTX_BTNS.map((b) => (
          <button
            key={b.type}
            className={`toolbar-btn ${ctx.open && ctx.type === b.type ? 'active' : ''}`}
            data-ctx={b.type}
            onClick={() => onCtxClick(b.type)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round">{b.svg}</svg>
            {b.badge && <span className="toolbar-badge">{b.badge}</span>}
            <span className="toolbar-tooltip">{b.tip}</span>
          </button>
        ))}
      </div>
      <div className="toolbar-spacer"></div>
      <div className="toolbar-group">
        <button className="toolbar-btn" id="btn-pause" onClick={pauseMeeting} title={meeting.paused ? '恢复会议' : '暂停会议'}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"><line x1="9" y1="5" x2="9" y2="19" /><line x1="15" y1="5" x2="15" y2="19" /></svg>
          <span className="toolbar-tooltip">{meeting.paused ? '恢复会议' : '暂停会议'}</span>
        </button>
        <button className="toolbar-btn" id="btn-intervene" onClick={toggleIntervene} title="介入引导">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12l16-8-6 16-3-7z" /></svg>
          <span className="toolbar-tooltip">介入引导</span>
        </button>
        <button className="toolbar-btn" id="btn-abort" onClick={abortMeeting} style={{ color: 'var(--dot-error)' }} title="终止会议">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"><rect x="7" y="7" width="10" height="10" rx="1" /></svg>
          <span className="toolbar-tooltip">终止会议</span>
        </button>
      </div>
      <div style={{ height: 8 }}></div>
    </aside>
  );
}
