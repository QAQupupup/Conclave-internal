import { useNavigate, useParams } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { useApp } from '../state/AppContext';
import { STAGES, ROLES, MESSAGES, type MeetingMessage } from '../data/mock';
import { REPORT_TYPES } from '../data/reportData';
import { sanitizeRich, formatTime } from '../lib/format';

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  REPORT_TYPES.map((t) => [t.id, t.label]),
);

const STAGE_TIMES = ['14:00', '14:08', '14:50', '15:02', '待定', '待定'];

export default function Meeting() {
  const { meeting, statusText, stageName, toggleIntervene, sendIntervention, appendLog, openMeeting } = useApp();
  const navigate = useNavigate();
  const { id } = useParams();
  const [expanded, setExpanded] = useState<Set<number>>(new Set([meeting.stage]));
  const [interveneText, setInterveneText] = useState('');
  const [sending, setSending] = useState(false);

  // 路由参数驱动：刷新 /meeting/:id 或直接进入该 URL 时，
  // 按 URL 中的 id 加载会议详情，避免依赖内存状态（刷新即丢失）。
  useEffect(() => {
    if (id && id !== meeting.currentMeetingId) {
      openMeeting(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const source: any[] = meeting.messages.length ? meeting.messages : MESSAGES;
  const elapsedMin = Math.floor(meeting.elapsed / 60);

  const toggleStage = (i: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
  };

  const submitIntervene = async () => {
    const text = interveneText.trim();
    if (!text) return;
    setSending(true);
    await sendIntervention(text);
    setInterveneText('');
    setSending(false);
  };

  const stageMsgs = (si: number, stageKey: string) =>
    source.filter((m) => {
      const ms = m.stage;
      if (typeof ms === 'number') return ms === si;
      if (typeof ms === 'string') return ms === stageKey || ms === STAGES[si].key;
      return false;
    });

  return (
    <div className="view active" id="view-meeting">
      <div className="meeting-back" onClick={() => navigate('/board')}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
        看板
      </div>
      <div className="meeting-title" id="meeting-title">{meeting.title}</div>
      <div className="meeting-meta">
        <div className="meeting-meta-item">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></svg>
          <span id="meeting-timer">{meeting.status === 'running' || meeting.status === 'paused' ? `已运行 ${elapsedMin}分钟` : statusText(meeting.status)}</span>
        </div>
        <div className="meeting-meta-item">
          <span className={`status-dot ${meeting.status || 'running'}`}></span>
          <span>{statusText(meeting.status || 'running')}{meeting.stage < STAGES.length ? ` · ${stageName(STAGES[meeting.stage].key)}阶段` : ''}</span>
        </div>
        <div className="meeting-meta-item">产出类型 {TYPE_LABELS[meeting.type] || meeting.type}</div>
      </div>

      {meeting.borrowRequest && (
        <div className="borrow-request" style={{ margin: '16px 0', padding: 16, background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>借调请求</div>
          <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 12 }}>{meeting.borrowRequest.reason || `${meeting.borrowRequest.from_role} 请求借调 ${meeting.borrowRequest.to_role}`}</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="ctrl-btn primary" onClick={() => appendLog('借调已批准', 'info')}>批准</button>
            <button className="ctrl-btn" onClick={() => appendLog('借调已拒绝', 'warning')}>拒绝</button>
          </div>
        </div>
      )}

      <div id="stage-sections" style={{ marginTop: 24 }}>
        {STAGES.map((stage, si) => {
          const msgs = stageMsgs(si, stage.key);
          const isOpen = expanded.has(si);
          const dotCls = si < meeting.stage ? 'done' : si === meeting.stage ? 'running' : '';
          const statusTxt = si < meeting.stage ? `${msgs.length}条发言` : si === meeting.stage ? '进行中' : '待执行';
          return (
            <div key={stage.key} className={`stage-section ${isOpen ? 'expanded' : ''}`} data-stage={si}>
              <div className="stage-header" onClick={() => toggleStage(si)}>
                <svg className="stage-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 6l6 6-6 6" /></svg>
                <span className="stage-name">{stage.name}</span>
                <span className="stage-time">{STAGE_TIMES[si]}</span>
                <span className="stage-status"><span className={`status-dot ${dotCls}`}></span>{statusTxt}</span>
              </div>
              {isOpen && (
                <div className="stage-body">
                  <div className="stage-messages">
                    {msgs.map((msg, mi) => {
                      const roleKey = msg.agent_role || msg.role || msg.speaker || 'moderator';
                      const role = (ROLES as any)[roleKey] || { name: roleKey, color: 'var(--text-2)' };
                      const content = msg.content || msg.text || '';
                      const timeStr = msg.time || formatTime(msg.created_at || msg.ts);
                      const refs = [...(msg.claim_refs || []), ...(msg.evidence_refs || []), ...(msg.refs || [])];
                      const risk: string | null = msg.risk || null;
                      const riskLabel = risk === 'high' ? '高风险' : risk === 'mid' ? '中风险' : risk ? '低风险' : '';
                      return (
                        <div className="msg" key={mi}>
                          <div className="msg-head">
                            <span className="msg-role" style={{ color: role.color }}>{role.name}</span>
                            <span className="msg-time">{timeStr}</span>
                          </div>
                          <div className="msg-body" dangerouslySetInnerHTML={{ __html: sanitizeRich(content) }} />
                          {(refs.length > 0 || risk) && (
                            <div className="msg-refs">
                              {refs.length > 0 && (<><span style={{ color: 'var(--text-3)' }}>参考</span>{' '}{refs.map((r: string, ri: number) => <span className="msg-ref" key={ri}>{r}</span>)}</>)}
                              {risk && <span className={`msg-risk msg-risk-${risk === 'high' ? 'high' : risk === 'mid' ? 'mid' : 'low'}`}><span className="msg-risk-dot"></span>{riskLabel}</span>}
                            </div>
                          )}
                          <div className="msg-actions">
                            <span className="msg-action" onClick={(e) => e.stopPropagation()}>复制</span>
                            <span className="msg-action" onClick={(e) => e.stopPropagation()}>聚焦</span>
                            <span className="msg-action" onClick={(e) => e.stopPropagation()}>引用</span>
                          </div>
                        </div>
                      );
                    })}
                    {si === meeting.stage && meeting.status === 'running' && (
                      <div className="msg-typing">
                        <span className="msg-role" style={{ color: 'var(--r-moderator)', fontSize: 13, fontWeight: 500 }}>主持人</span>
                        <div className="typing-dots"><span className="typing-dot"></span><span className="typing-dot"></span><span className="typing-dot"></span></div>
                        <span className="typing-text">正在总结校验结果…</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="intervene-panel" id="intervene-panel" style={{ display: meeting.interveneOpen ? 'block' : 'none' }}>
        <div className="intervene-panel-head">
          <span className="intervene-panel-title">介入引导</span>
          <span className="intervene-panel-close" onClick={toggleIntervene}>&times;</span>
        </div>
        <textarea
          className="intervene-input"
          id="intervene-input"
          placeholder="输入你的介入意见、补充信息或纠正方向…"
          rows={3}
          value={interveneText}
          onChange={(e) => setInterveneText(e.target.value)}
        />
        <div className="intervene-panel-actions">
          <button className="ctrl-btn" onClick={toggleIntervene}>取消</button>
          <button className="ctrl-btn primary" id="intervene-send" disabled={sending} onClick={submitIntervene}>
            {sending ? '发送中...' : '发送介入'}
          </button>
        </div>
      </div>
    </div>
  );
}
