import { useState, useEffect } from 'react';
import { useApp } from '../state/AppContext';
import { ROLES, STAGES } from '../data/mock';
import { REPORT_TYPES } from '../data/reportData';

const TITLES: Record<string, string> = {
  overview: '议题概览', evidence: '证据库', artifact: '产出物', token: 'Token与成本', model: '模型调度',
};

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  REPORT_TYPES.map((t) => [t.id, t.label]),
);

function fmtElapsed(sec: number): string {
  if (!sec || sec < 0) return '—';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}分${String(s).padStart(2, '0')}秒`;
}

export default function ContextPanel() {
  const { ctx, closeCtx, meeting, stageName, statusText } = useApp();
  const [elapsedSec, setElapsedSec] = useState(0);

  // 本地 elapsed 计算（同 Meeting 视图）
  useEffect(() => {
    if (!meeting.startedAt || (meeting.status !== 'running' && meeting.status !== 'paused')) {
      setElapsedSec(0);
      return;
    }
    const tick = () => setElapsedSec(Math.floor((Date.now() - meeting.startedAt!) / 1000));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [meeting.startedAt, meeting.status]);

  if (!ctx.open) return null;

  const stageIdx = Math.min(meeting.stage, STAGES.length - 1);
  const typeLabel = TYPE_LABELS[meeting.type] || meeting.type;

  // 从真实消息中提取参与角色和证据
  const activeSpeakers = new Set<string>();
  const evidenceRefs = new Set<string>();
  let totalChars = 0;
  meeting.messages.forEach((m) => {
    const role = m.speaker_role || m.speaker;
    if (role) activeSpeakers.add(role);
    totalChars += m.content?.length || 0;
    // 提取证据引用（简单提取 URL 和 § 引用）
    const urlMatches = m.content?.match(/https?:\/\/[^\s)）]+/g) || [];
    urlMatches.forEach((u) => evidenceRefs.add(u));
    const docMatches = m.content?.match(/[§#][\w.]+/g) || [];
    docMatches.forEach((d) => evidenceRefs.add(d));
  });

  const isRunning = meeting.status === 'running' || meeting.status === 'paused';
  const isDone = meeting.status === 'done' || meeting.status === 'aborted' || meeting.status === 'failed';

  return (
    <div className="ctx-panel open" id="ctx-panel">
      <div className="ctx-panel-head">
        <div className="ctx-panel-title">{TITLES[ctx.type]}</div>
        <div className="ctx-panel-close" onClick={closeCtx}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
        </div>
      </div>
      <div className="ctx-panel-body">
        {ctx.type === 'overview' && (
          <>
            <div className="ctx-field"><div className="ctx-label">议题</div><div className="ctx-value">{meeting.title || '—'}</div></div>
            <div className="ctx-field"><div className="ctx-label">产出类型</div><div className="ctx-value">{typeLabel || '—'}</div></div>
            <div className="ctx-field"><div className="ctx-label">当前阶段</div><div className="ctx-value">{stageName(STAGES[stageIdx]?.key) || '—'} · 第 {stageIdx + 1} / {STAGES.length} 阶段</div></div>
            <div className="ctx-field"><div className="ctx-label">已运行</div><div className="ctx-value" style={{ fontFamily: 'var(--mono)' }}>{isRunning ? fmtElapsed(elapsedSec) : statusText(meeting.status || 'pending')}</div></div>
            <div className="ctx-field"><div className="ctx-label">状态</div><div className="ctx-value">{statusText(meeting.status || 'pending')}</div></div>
            <div className="ctx-field"><div className="ctx-label">消息数</div><div className="ctx-value" style={{ fontFamily: 'var(--mono)' }}>{meeting.messages.length} 条</div></div>
            <div className="ctx-field">
              <div className="ctx-label">参会角色（{activeSpeakers.size}）</div>
              <div className="ctx-roles">
                {Object.entries(ROLES).map(([k, r]) => {
                  const hasSpoken = activeSpeakers.has(k) || activeSpeakers.has(r.name);
                  return (
                    <div className="ctx-role" key={k} style={{ opacity: hasSpoken ? 1 : 0.4 }}>
                      <span className="ctx-role-dot" style={{ background: r.color }}></span>
                      <span className="ctx-role-name">{r.name}</span>
                      <span className="ctx-role-status">{hasSpoken ? '已发言' : '等待中'}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}
        {ctx.type === 'evidence' && (
          <>
            <div className="ctx-field"><div className="ctx-label">证据引用 · {evidenceRefs.size}条</div></div>
            {evidenceRefs.size === 0 && (
              <div style={{ padding: '12px 0', fontSize: 13, color: 'var(--text-3)', fontStyle: 'italic' }}>
                暂未提取到证据引用
              </div>
            )}
            {[...evidenceRefs].slice(0, 50).map((ref, i) => (
              <div key={ref} style={{ padding: '10px 0', borderBottom: '1px solid var(--line)', fontSize: 13 }}>
                <div style={{ color: 'var(--text)', wordBreak: 'break-all' }}>{ref}</div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4, fontFamily: 'var(--mono)' }}>
                  #{i + 1} · 来源: 会议讨论
                </div>
              </div>
            ))}
          </>
        )}
        {ctx.type === 'artifact' && (
          <>
            <div className="ctx-field">
              <div className="ctx-label">产出状态</div>
              <div className="ctx-value" style={{ color: isDone ? 'var(--text)' : 'var(--text-3)' }}>
                {isDone ? '已完成' : meeting.status === 'running' ? '生成中…' : '等待中'}
              </div>
            </div>
            <div className="ctx-field"><div className="ctx-label">预期产出</div><div className="ctx-value">{typeLabel || '—'}</div></div>
            <div className="ctx-field"><div className="ctx-label">输出字符</div><div className="ctx-value" style={{ fontFamily: 'var(--mono)' }}>{totalChars.toLocaleString()} 字</div></div>
          </>
        )}
        {ctx.type === 'token' && (
          <>
            <div className="ctx-stat"><span className="ctx-stat-label">消息条数</span><span className="ctx-stat-value">{meeting.messages.length}</span></div>
            <div className="ctx-stat"><span className="ctx-stat-label">总字符数</span><span className="ctx-stat-value">{totalChars.toLocaleString()}</span></div>
            <div className="ctx-stat"><span className="ctx-stat-label">已运行</span><span className="ctx-stat-value" style={{ fontFamily: 'var(--mono)' }}>{fmtElapsed(elapsedSec)}</span></div>
            <div style={{ padding: '16px 0', fontSize: 12, color: 'var(--text-3)', borderTop: '1px solid var(--line)', marginTop: 8 }}>
              详细 Token 成本统计将在后端 metrics API 完善后展示
            </div>
          </>
        )}
        {ctx.type === 'model' && (
          <div style={{ padding: '16px 0', fontSize: 12, color: 'var(--text-3)' }}>
            模型调度与成本统计随会议运行实时更新
          </div>
        )}
      </div>
    </div>
  );
}
