import { useNavigate, useParams } from 'react-router-dom';
import { useState, useEffect, useRef, useCallback } from 'react';
import { useApp, type MeetingMessage as AppMeetingMessage } from '../state/AppContext';
import { STAGES, ROLES } from '../data/mock';
import { REPORT_TYPES } from '../data/reportData';
import { sanitizeRich, formatTime } from '../lib/format';
import { useToast } from '../components/Toast';
import PhasedProgress, { usePhasedProgress } from '../components/PhasedProgress';

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  REPORT_TYPES.map((t) => [t.id, t.label]),
);
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

function stageTimeLabel(si: number, currentStage: number): string {
  if (si < currentStage) return '已完成';
  if (si === currentStage) return '进行中';
  return '待定';
}

const TYPING_TEXT: Record<string, string> = {
  clarify: '正在理解议题、澄清需求…',
  intra_team: '组内讨论中…',
  cross_team: '组间辩论中…',
  evidence_check: '正在校验证据与论断…',
  arbitrate: '正在仲裁分歧…',
  produce: '正在产出最终交付物…',
};

export default function Meeting() {
  const {
    meeting, statusText, stageName, toggleIntervene, sendIntervention,
    openMeeting, approveBorrow, rejectBorrow, setReplyTarget, requestConfirm,
  } = useApp();
  const toast = useToast();
  const navigate = useNavigate();
  const { id } = useParams();
  const [expanded, setExpanded] = useState<Set<number>>(new Set([meeting.stage]));
  const [interveneText, setInterveneText] = useState('');
  const [sending, setSending] = useState(false);
  const [claimPreview, setClaimPreview] = useState<{ claimId: string; role: string; stage: string; snippet: string } | null>(null);
  const [focusedMsgId, setFocusedMsgId] = useState<string | null>(null);

  // 分阶段生成进度（仅deployable_service类型激活）
  const phased = usePhasedProgress(meeting.currentMeetingId || undefined);

  // 本地 elapsed 计算：基于 startedAt 时间戳，避免 context 每秒重渲染
  const [elapsedSec, setElapsedSec] = useState(0);
  useEffect(() => {
    if (!meeting.startedAt || (meeting.status !== 'running' && meeting.status !== 'paused')) {
      setElapsedSec(0);
      return;
    }
    const tick = () => {
      setElapsedSec(Math.floor((Date.now() - meeting.startedAt!) / 1000));
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [meeting.startedAt, meeting.status]);
  const elapsedMin = Math.floor(elapsedSec / 60);

  // 路由参数驱动加载
  useEffect(() => {
    if (id && id !== meeting.currentMeetingId) {
      openMeeting(id);
    }
     
  }, [id]);

  // 自动展开当前阶段
  useEffect(() => {
    setExpanded((prev) => new Set(prev).add(meeting.stage));
  }, [meeting.stage]);

  // 使用真实消息（不回退 mock）
  const source: AppMeetingMessage[] = meeting.messages;

  // claim 溯源
  const onMsgBodyClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (!target.classList.contains('ck-claim-ref')) return;
    const claimId = target.getAttribute('data-claim-id');
    if (!claimId) return;
    const found = source.find((m) => {
      const content = m.content || '';
      return content.includes(claimId);
    });
    if (found) {
      const roleKey = found.speaker_role || found.speaker || 'moderator';
      const role = (ROLES as any)[roleKey] || { name: roleKey };
      const content = found.content || '';
      const lines = content.split('\n');
      const lineIdx = lines.findIndex((l: string) => l.includes(claimId));
      let snippet: string;
      if (lineIdx >= 0) {
        snippet = lines.slice(Math.max(0, lineIdx), Math.min(lines.length, lineIdx + 2)).join('\n');
      } else {
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

  /* ── 消息操作 ── */
  const handleCopy = useCallback(async (content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      toast.show('已复制到剪贴板', 'success', 2000);
    } catch {
      // fallback: textarea
      const ta = document.createElement('textarea');
      ta.value = content;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      toast.show('已复制到剪贴板', 'success', 2000);
    }
  }, [toast]);

  const msgRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const handleFocus = useCallback((msgId: string | undefined, idx: number) => {
    const key = msgId || `idx-${idx}`;
    const el = msgRefs.current.get(key);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setFocusedMsgId(key);
      setTimeout(() => setFocusedMsgId(null), 1500);
    }
  }, []);

  const handleQuote = useCallback((msg: AppMeetingMessage) => {
    setReplyTarget(msg);
    // 聚焦输入框
    setTimeout(() => {
      const input = document.getElementById('intervene-input') as HTMLTextAreaElement | null;
      input?.focus();
    }, 100);
  }, [setReplyTarget]);

  /* ── 借调操作 ── */
  const handleApproveBorrow = () => {
    if (!meeting.borrowRequest) return;
    approveBorrow(meeting.borrowRequest);
  };
  const handleRejectBorrow = async () => {
    if (!meeting.borrowRequest) return;
    const confirmed = await requestConfirm({
      title: '拒绝借调',
      message: '确定拒绝此借调请求吗？拒绝后该角色将无法参与当前阶段。',
      confirmText: '拒绝',
      cancelText: '取消',
      danger: true,
    });
    if (confirmed) rejectBorrow(meeting.borrowRequest, '用户拒绝');
  };

  const stageMsgs = (si: number, stageKey: string) =>
    source.filter((m) => {
      const ms = m.stage;
      if (typeof ms === 'number') return ms === si;
      if (typeof ms === 'string') return ms === stageKey || ms === STAGES[si].key || ms === 'intervention';
      return false;
    });

  const currentStageKey = meeting.stage < STAGES.length ? STAGES[meeting.stage].key : 'clarify';

  return (
    <div className="view active" id="view-meeting">
      <div className="meeting-back" onClick={() => navigate('/board')}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
        看板
      </div>
      <div className="meeting-title" id="meeting-title">{meeting.title || '加载中...'}</div>
      <div className="meeting-meta">
        <div className="meeting-meta-item">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></svg>
          <span id="meeting-timer">
            {meeting.status === 'running' ? `已运行 ${elapsedMin}分钟` :
             meeting.status === 'paused' ? `已暂停 · ${elapsedMin}分钟` :
             statusText(meeting.status)}
          </span>
        </div>
        <div className="meeting-meta-item">
          <span className={`status-dot ${meeting.status || 'running'}`}></span>
          <span>{statusText(meeting.status || 'running')}{meeting.stage < STAGES.length ? ` · ${stageName(STAGES[meeting.stage].key)}阶段` : ''}</span>
        </div>
        <div className="meeting-meta-item">产出类型 {TYPE_LABELS[meeting.type] || TYPE_FALLBACK[meeting.type] || meeting.type || '—'}</div>
      </div>

      {/* 借调请求 */}
      {meeting.borrowRequest && (
        <div className="borrow-request" style={{ margin: '16px 0', padding: 16, background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>借调请求</div>
          <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 12 }}>
            {meeting.borrowRequest.reason || `${meeting.borrowRequest.from_role} 请求借调 ${meeting.borrowRequest.to_role}`}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="ctrl-btn primary" onClick={handleApproveBorrow}>批准</button>
            <button className="ctrl-btn" onClick={handleRejectBorrow}>拒绝</button>
          </div>
        </div>
      )}

      {/* 引用回复提示 */}
      {meeting.replyTarget && (
        <div style={{ margin: '8px 0 16px', padding: '8px 12px', background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 6, fontSize: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ color: 'var(--text-2)' }}>
            引用回复 <strong>{meeting.replyTarget.speaker}</strong>：{meeting.replyTarget.content.substring(0, 60)}{meeting.replyTarget.content.length > 60 ? '...' : ''}
          </span>
          <button className="ctrl-btn" style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => setReplyTarget(null)}>取消引用</button>
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
                    {msgs.length === 0 && si === meeting.stage && meeting.status === 'pending' && (
                      <div className="msg-empty">等待会议开始…</div>
                    )}
                    {msgs.length === 0 && si !== meeting.stage && si > meeting.stage && (
                      <div className="msg-empty">该阶段尚未开始</div>
                    )}
                    {msgs.length === 0 && si < meeting.stage && (
                      <div className="msg-empty">该阶段无发言记录</div>
                    )}
                    {msgs.map((msg, mi) => {
                      const roleKey = msg.speaker_role || msg.speaker || 'moderator';
                      const role = (ROLES as any)[roleKey] || { name: msg.speaker || roleKey, color: 'var(--text-2)' };
                      const content = msg.content || '';
                      const timeStr = formatTime(msg.ts);
                      const isIntervention = msg.isIntervention;
                      const isUser = msg.isUser;
                      const msgKey = msg.id || `idx-${mi}`;
                      return (
                        <div
                          className={`msg ${isIntervention ? 'msg-intervention' : ''} ${isUser ? 'msg-user' : ''} ${focusedMsgId === msgKey ? 'msg-focused' : ''}`}
                          key={msgKey}
                          ref={(el) => { if (el) msgRefs.current.set(msgKey, el); }}
                        >
                          <div className="msg-head">
                            <span className="msg-role" style={{ color: role.color }}>{role.name}</span>
                            <span className="msg-time">{timeStr}</span>
                          </div>
                          <div className="msg-body" onClick={onMsgBodyClick} dangerouslySetInnerHTML={{ __html: sanitizeRich(content) }} />
                          <div className="msg-actions">
                            <button className="msg-action-btn" onClick={(e) => { e.stopPropagation(); handleCopy(content); }}>复制</button>
                            <button className="msg-action-btn" onClick={(e) => { e.stopPropagation(); handleFocus(msg.id, mi); }}>聚焦</button>
                            <button className="msg-action-btn" onClick={(e) => { e.stopPropagation(); handleQuote(msg); }}>引用</button>
                          </div>
                        </div>
                      );
                    })}
                    {si === meeting.stage && meeting.status === 'running' && (
                      <>
                        {/* 分阶段生成管线进度（deployable_service类型） */}
                        {stage.key === 'produce' && meeting.type === 'deployable_service' && phased.currentStage && (
                          <div style={{ margin: '8px 0' }}>
                            <PhasedProgress
                              currentStage={phased.currentStage}
                              stageMessage={phased.stageMessage}
                              percent={phased.percent}
                              completedStages={phased.completedStages}
                            />
                          </div>
                        )}
                        <div className="msg-typing">
                          <span className="msg-role" style={{ color: 'var(--r-moderator)', fontSize: 13, fontWeight: 500 }}>主持人</span>
                          <div className="typing-dots"><span className="typing-dot"></span><span className="typing-dot"></span><span className="typing-dot"></span></div>
                          <span className="typing-text">{TYPING_TEXT[currentStageKey] || '处理中…'}</span>
                        </div>
                      </>
                    )}
                    {si === meeting.stage && meeting.status === 'paused' && (
                      <div className="msg-typing" style={{ color: 'var(--text-3)' }}>
                        <span className="typing-text">会议已暂停</span>
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
        {meeting.replyTarget && (
          <div style={{ fontSize: 12, color: 'var(--text-3)', padding: '0 12px', marginBottom: 4 }}>
            回复 {meeting.replyTarget.speaker}
          </div>
        )}
        <textarea
          className="intervene-input"
          id="intervene-input"
          placeholder="输入你的介入意见、补充信息或纠正方向…"
          rows={3}
          value={interveneText}
          onChange={(e) => setInterveneText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitIntervene(); }}
        />
        <div className="intervene-panel-actions">
          <button className="ctrl-btn" onClick={() => { toggleIntervene(); setReplyTarget(null); }}>取消</button>
          <button className="ctrl-btn primary" id="intervene-send" disabled={sending || !interveneText.trim()} onClick={submitIntervene}>
            {sending ? '发送中...' : '发送介入'}
          </button>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-3)', padding: '0 12px 8px' }}>⌘/Ctrl + Enter 快速发送</div>
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
