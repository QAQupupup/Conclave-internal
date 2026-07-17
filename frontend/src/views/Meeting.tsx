import { useNavigate, useParams } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { useApp } from '../state/AppContext';
import { STAGES, ROLES, MESSAGES, type MeetingMessage } from '../data/mock';
import { REPORT_TYPES } from '../data/reportData';
import { sanitizeRich, formatTime } from '../lib/format';

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  REPORT_TYPES.map((t) => [t.id, t.label]),
);
// 兜底：后端可能返回未在 REPORT_TYPES 中定义的类型
const TYPE_FALLBACK: Record<string, string> = {
  research_report: '调研报告',
  deployable_service: '可部署服务',
  prd_openapi: 'PRD + OpenAPI',
  design_doc: '设计文档',
  comprehensive: '综合报告',
  business_report: '商业报告',
  code_analysis: '代码分析',
  tested_system: '可测试系统',
  execution: '执行方案',
};

// 阶段时间不再写死，改为动态计算占位（后端未返回各阶段时间戳）
// 已完成阶段显示"已完成"，进行中阶段显示"进行中"，未开始阶段显示"待定"
function stageTimeLabel(si: number, currentStage: number): string {
  if (si < currentStage) return '已完成';
  if (si === currentStage) return '进行中';
  return '待定';
}

export default function Meeting() {
  const { meeting, statusText, stageName, toggleIntervene, sendIntervention, appendLog, openMeeting } = useApp();
  const navigate = useNavigate();
  const { id } = useParams();
  const [expanded, setExpanded] = useState<Set<number>>(new Set([meeting.stage]));
  const [interveneText, setInterveneText] = useState('');
  const [sending, setSending] = useState(false);
  // claim 溯源预览：点击 claim-xxx 标签时显示对应发言片段
  const [claimPreview, setClaimPreview] = useState<{ claimId: string; role: string; stage: string; snippet: string } | null>(null);

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

  // claim 溯源：点击 msg-body 内的 claim-xxx 标签，查找对应发言片段
  const onMsgBodyClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (!target.classList.contains('ck-claim-ref')) return;
    const claimId = target.getAttribute('data-claim-id');
    if (!claimId) return;

    // 在所有发言中查找包含该 claim ID 的消息
    const found = source.find((m: any) => {
      const content = m.content || m.text || '';
      const refs = [...(m.claim_refs || []), ...(m.refs || [])];
      return content.includes(claimId) || refs.includes(claimId);
    });

    if (found) {
      const roleKey = found.agent_role || found.role || found.speaker || 'moderator';
      const role = (ROLES as any)[roleKey] || { name: roleKey };
      const content = found.content || found.text || '';
      // 提取 claim 上下文片段：claim 所在行 ±前后各一行
      const lines = content.split('\n');
      const lineIdx = lines.findIndex((l: string) => l.includes(claimId));
      let snippet: string;
      if (lineIdx >= 0) {
        const start = Math.max(0, lineIdx);
        const end = Math.min(lines.length, lineIdx + 2);
        snippet = lines.slice(start, end).join('\n');
      } else {
        // claim 在 refs 里，不在正文里，取前 200 字
        snippet = content.substring(0, 200);
      }
      const stageName_ = STAGES.find((s) => s.key === found.stage)?.name || found.stage || '';
      setClaimPreview({ claimId, role: role.name, stage: stageName_, snippet });
    } else {
      setClaimPreview({ claimId, role: '未知', stage: '', snippet: '未在当前会议发言中找到该论断的来源片段' });
    }
  };

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
        <div className="meeting-meta-item">产出类型 {TYPE_LABELS[meeting.type] || TYPE_FALLBACK[meeting.type] || meeting.type || '—'}</div>
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
                <span className="stage-time">{stageTimeLabel(si, meeting.stage)}</span>
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
                          <div className="msg-body" onClick={onMsgBodyClick} dangerouslySetInnerHTML={{ __html: sanitizeRich(content) }} />
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
                    {si === meeting.stage && meeting.status === 'failed' && (
                      <div className="msg-typing" style={{ color: 'var(--danger)' }}>
                        <span className="msg-role" style={{ color: 'var(--danger)', fontSize: 13, fontWeight: 500 }}>系统</span>
                        <span className="typing-text">本阶段执行失败，部分 Agent 可能已降级到占位输出</span>
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

      {/* claim 溯源预览弹窗 */}
      {claimPreview && (
        <div className="claim-preview-overlay" onClick={() => setClaimPreview(null)}>
          <div className="claim-preview-card" onClick={(e) => e.stopPropagation()}>
            <div className="claim-preview-head">
              <span className="claim-preview-id">{claimPreview.claimId}</span>
              <button className="claim-preview-close" onClick={() => setClaimPreview(null)}>×</button>
            </div>
            <div className="claim-preview-meta">
              {claimPreview.role && <span className="claim-preview-role">{claimPreview.role}</span>}
              {claimPreview.stage && <span className="claim-preview-stage">{claimPreview.stage}</span>}
            </div>
            <div className="claim-preview-snippet" dangerouslySetInnerHTML={{ __html: sanitizeRich(claimPreview.snippet) }} />
          </div>
        </div>
      )}
    </div>
  );
}
