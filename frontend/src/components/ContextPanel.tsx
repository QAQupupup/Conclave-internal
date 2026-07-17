import { useApp } from '../state/AppContext';
import { ROLES, MODELS, STAGES } from '../data/mock';
import { REPORT_TYPES } from '../data/reportData';

const TITLES: Record<string, string> = {
  overview: '议题概览', evidence: '证据库', artifact: '产出物', token: 'Token与成本', model: '模型调度',
};

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  REPORT_TYPES.map((t) => [t.id, t.label]),
);

const EVIDENCE = ['规格 §3.2', 'martinfowler.com', 'arxiv:1706.04024', 'owasp.org/ms-top10', 'debezium.io', 'microservices.io', 'linkerd.io'];
const TOKEN_STATS: [string, string][] = [
  ['总消耗', '48,213'], ['主持人', '8,420'], ['架构师', '12,105'], ['工程师', '7,832'],
  ['安全专家', '6,540'], ['UX设计师', '4,210'], ['数据工程师', '5,106'], ['市场专家', '4,000'], ['预估成本', '¥0.34'],
];

function fmtElapsed(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}分${String(s).padStart(2, '0')}秒`;
}

export default function ContextPanel() {
  const { ctx, closeCtx, meeting, stageName, statusText } = useApp();
  if (!ctx.open) return null;

  const stageIdx = Math.min(meeting.stage, STAGES.length - 1);
  const typeLabel = TYPE_LABELS[meeting.type] || meeting.type;

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
            <div className="ctx-field"><div className="ctx-label">议题</div><div className="ctx-value">{meeting.title}</div></div>
            <div className="ctx-field"><div className="ctx-label">产出类型</div><div className="ctx-value">{typeLabel}</div></div>
            <div className="ctx-field"><div className="ctx-label">当前阶段</div><div className="ctx-value">{stageName(STAGES[stageIdx].key)} · 第 {stageIdx + 1} / {STAGES.length} 阶段</div></div>
            <div className="ctx-field"><div className="ctx-label">已运行</div><div className="ctx-value" style={{ fontFamily: 'var(--mono)' }}>{fmtElapsed(meeting.elapsed)}</div></div>
            <div className="ctx-field"><div className="ctx-label">状态</div><div className="ctx-value">{statusText(meeting.status || 'running')}</div></div>
            <div className="ctx-field">
              <div className="ctx-label">参会角色</div>
              <div className="ctx-roles">
                {Object.entries(ROLES).map(([k, r]) => (
                  <div className="ctx-role" key={k}>
                    <span className="ctx-role-dot" style={{ background: r.color }}></span>
                    <span className="ctx-role-name">{r.name}</span>
                    <span className="ctx-role-status">{k === 'moderator' ? '主持' : '已发言'}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
        {ctx.type === 'evidence' && (
          <>
            <div className="ctx-field"><div className="ctx-label">证据列表 · {EVIDENCE.length}条</div></div>
            {EVIDENCE.map((r, i) => (
              <div key={r} style={{ padding: '12px 0', borderBottom: '1px solid var(--line)' }}>
                <div style={{ fontSize: 13, color: 'var(--text)' }}>{r}</div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4, fontFamily: 'var(--mono)' }}>
                  来源: {i < 2 ? '文档' : i < 5 ? 'Web搜索' : '已验证'} · 可信度: {i < 2 ? '高' : i < 5 ? '中' : '高'}
                </div>
              </div>
            ))}
          </>
        )}
        {ctx.type === 'artifact' && (
          <>
            <div className="ctx-field"><div className="ctx-label">产出状态</div><div className="ctx-value" style={{ color: 'var(--text-3)' }}>尚未生成 · 等待仲裁和产出阶段</div></div>
            <div className="ctx-field"><div className="ctx-label">预期产出</div><div className="ctx-value">{typeLabel} · 包含迁移路径、分期方案、风险评估</div></div>
          </>
        )}
        {ctx.type === 'token' && TOKEN_STATS.map(([label, val]) => (
          <div className="ctx-stat" key={label}><span className="ctx-stat-label">{label}</span><span className="ctx-stat-value">{val}</span></div>
        ))}
        {ctx.type === 'model' && MODELS.map((m: any) => (
          <div className="ctx-stat" key={m.id}><span className="ctx-stat-label">{m.name}</span><span className="ctx-stat-value">{m.tag}</span></div>
        ))}
      </div>
    </div>
  );
}
