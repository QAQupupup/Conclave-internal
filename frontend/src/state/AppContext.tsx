import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react';
import { subscribeAuth, getAuthUser, commitLogout, getToken, type ConclaveUser } from '../lib/auth';
import { onUnauthorized, apiMe, apiListMeetings, apiCreateMeeting, apiRunMeeting, apiGetMeeting, apiControlMeeting, apiIntervene } from '../lib/api';
import { MeetingWsClient, connectSystemWs, STAGE_KEYS } from '../lib/ws';
import { STAGES, MEETINGS as MOCK_MEETINGS } from '../data/mock';
import { type ToastKind } from '../components/Toast';

export type LogLevel = 'ALL' | 'INFO' | 'DEBUG' | 'WARN' | 'ERROR';
export type CtxType = 'overview' | 'evidence' | 'artifact' | 'token' | 'model';

export interface LogEntry { time: string; level: LogLevel; msg: string; category?: string }

/** 结构化会议消息类型，消除 any */
export interface MeetingMessage {
  id?: string;
  speaker: string;
  speaker_role?: string;
  content: string;
  stage?: string;
  ts: number;
  isIntervention?: boolean;
  isUser?: boolean;
  replyTo?: string | null;
  metadata?: Record<string, unknown>;
}

export interface BorrowRequest {
  request_id: string;
  from_role: string;
  to_role: string;
  topic?: string;
  reason?: string;
  created_at?: string;
}

export interface MeetingState {
  messages: MeetingMessage[];
  conflicts: any[];
  claims: any[];
  confidence: any[];
  stage: number;
  status: string;
  currentMeetingId: string | null;
  title: string;
  type: string;
  interveneOpen: boolean;
  borrowRequest: BorrowRequest | null;
  paused: boolean;
  /** 会议开始时间戳（ms），elapsed 由视图层基于此计算，避免每秒重渲染 */
  startedAt: number | null;
  /** 引用回复目标消息 */
  replyTarget: MeetingMessage | null;
}

const INITIAL_MEETING: MeetingState = {
  messages: [], conflicts: [], claims: [], confidence: [],
  stage: 0, status: '', currentMeetingId: null, title: '',
  type: 'prd_openapi', interveneOpen: false, borrowRequest: null, paused: false,
  startedAt: null, replyTarget: null,
};

const STATUS_TEXT: Record<string, string> = {
  running: '进行中', paused: '已暂停', done: '已完成', aborted: '已终止',
  failed: '失败', pending: '待开始', created: '待开始',
};

/** 确认对话框配置 */
export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
}

interface AppApi {
  theme: 'light' | 'dark';
  toggleTheme: () => void;
  user: ConclaveUser | null;
  setUser: (u: ConclaveUser | null) => void;
  authChecked: boolean;
  authExpired: boolean;
  clearAuthExpired: () => void;
  logout: () => void;
  /** 演示模式：未登录时可进入，所有数据来自 mock，与真实 API 完全隔离 */
  demoMode: boolean;
  enterDemo: () => void;
  exitDemo: () => void;
  logOpen: boolean;
  toggleLog: () => void;
  logFilter: string;
  setLogFilter: (l: string) => void;
  logs: LogEntry[];
  appendLog: (msg: string, level?: string, category?: string) => void;
  clearLogs: () => void;
  cmdkOpen: boolean;
  openCmdk: () => void;
  closeCmdk: () => void;
  ctx: { open: boolean; type: CtxType };
  openCtx: (type: CtxType) => void;
  closeCtx: () => void;
  selectedType: string;
  setSelectedType: (t: string) => void;
  meetings: any[];
  meetingsLoading: boolean;
  meetingsError: string | null;
  refreshBoard: () => Promise<void>;
  meeting: MeetingState;
  startMeeting: (topic: string, type: string) => Promise<string | null>;
  openMeeting: (id: string) => Promise<void>;
  pauseMeeting: () => Promise<void>;
  abortMeeting: () => Promise<void>;
  toggleIntervene: () => void;
  sendIntervention: (content: string) => Promise<void>;
  approveBorrow: (req: BorrowRequest) => void;
  rejectBorrow: (req: BorrowRequest, reason?: string) => void;
  setReplyTarget: (msg: MeetingMessage | null) => void;
  requestConfirm: (opts: ConfirmOptions) => Promise<boolean>;
  confirmState: ConfirmOptions | null;
  resolveConfirm: (val: boolean) => void;
  toast: (msg: string, kind?: ToastKind, duration?: number) => void;
  _toastFn: ((msg: string, kind?: ToastKind, duration?: number) => void) | null;
  _setToastFn: (fn: (msg: string, kind?: ToastKind, duration?: number) => void) => void;
  statusText: (s: string) => string;
  stageName: (s: string) => string;
}

const Ctx = createContext<AppApi | null>(null);

export function useApp(): AppApi {
  const v = useContext(Ctx);
  if (!v) throw new Error('useApp must be used within AppProvider');
  return v;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<'light' | 'dark'>(() =>
    (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme')) === 'dark' ? 'dark' : 'light');
  const [user, setUserState] = useState<ConclaveUser | null>(getAuthUser());
  const [authChecked, setAuthChecked] = useState(false);
  const [authExpired, setAuthExpired] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [logFilter, setLogFilter] = useState<string>('ALL');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [ctx, setCtx] = useState<{ open: boolean; type: CtxType }>({ open: false, type: 'overview' });
  const [selectedType, setSelectedType] = useState('prd_openapi');
  const [meetings, setMeetings] = useState<any[]>([]);
  const [meetingsLoading, setMeetingsLoading] = useState(false);
  const [meetingsError, setMeetingsError] = useState<string | null>(null);
  const [meeting, setMeeting] = useState<MeetingState>(INITIAL_MEETING);

  // 确认对话框状态（Promise-based，替换原生 confirm）
  const [confirmState, setConfirmState] = useState<ConfirmOptions | null>(null);
  const confirmResolverRef = useRef<((val: boolean) => void) | null>(null);

  // Toast 函数引用（由 ToastProvider 挂载后注入）
  const toastFnRef = useRef<((msg: string, kind?: ToastKind, duration?: number) => void) | null>(null);

  const wsRef = useRef<MeetingWsClient | null>(null);
  const authExpiredFired = useRef(false);

  /* ── Toast 桥接 ── */
  const toast = useCallback((msg: string, kind: ToastKind = 'info', duration = 4000) => {
    if (toastFnRef.current) toastFnRef.current(msg, kind, duration);
  }, []);
  const _setToastFn = useCallback((fn: (msg: string, kind?: ToastKind, duration?: number) => void) => {
    toastFnRef.current = fn;
  }, []);

  /* ── 日志（结构化，带分类） ── */
  const appendLog = useCallback((msg: string, level: string = 'info', category?: string) => {
    const lv = (level === 'warning' ? 'WARN' : level.toUpperCase()) as LogLevel;
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    setLogs((prev) => [{ time, level: lv, msg, category }, ...prev].slice(0, 500));
  }, []);
  const clearLogs = useCallback(() => setLogs([]), []);

  /* ── 主题 ── */
  const toggleTheme = useCallback(() => {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('conclave_theme', next); } catch { /* ignore */ }
      return next;
    });
  }, []);

  /* ── 认证 ── */
  const setUser = useCallback((u: ConclaveUser | null) => {
    setUserState(u);
    // 登录成功后自动退出演示模式，确保走真实 API
    if (u) setDemoMode(false);
  }, []);
  const clearAuthExpired = useCallback(() => {
    setAuthExpired(false);
    authExpiredFired.current = false;
  }, []);
  const logout = useCallback(() => {
    commitLogout();
    setUserState(null);
    if (wsRef.current) { wsRef.current.disconnect(); wsRef.current = null; }
    setMeeting({ ...INITIAL_MEETING });
    clearLogs();
    setDemoMode(false);
    toast('已退出登录', 'info');
  }, [clearLogs, toast]);
  /* ── 演示模式 ── */
  const enterDemo = useCallback(() => {
    setDemoMode(true);
    setUserState(null);
    commitLogout();
    if (wsRef.current) { wsRef.current.disconnect(); wsRef.current = null; }
    setMeeting({ ...INITIAL_MEETING });
    appendLog('已进入演示模式（数据为模拟数据）', 'info', 'demo');
    toast('已进入演示模式', 'info');
  }, [appendLog, toast]);
  const exitDemo = useCallback(() => {
    setDemoMode(false);
    setMeetings([]);
    setMeeting({ ...INITIAL_MEETING });
  }, []);
  useEffect(() => subscribeAuth(setUserState), []);

  useEffect(() => {
    onUnauthorized(() => {
      if (authExpiredFired.current) return;
      authExpiredFired.current = true;
      commitLogout();
      setUserState(null);
      if (wsRef.current) { wsRef.current.disconnect(); wsRef.current = null; }
      setMeeting({ ...INITIAL_MEETING });
      setAuthExpired(true);
    });
  }, []);

  /* ── 命令面板 ── */
  const openCmdk = useCallback(() => setCmdkOpen(true), []);
  const closeCmdk = useCallback(() => setCmdkOpen(false), []);

  /* ── 上下文面板 ── */
  const openCtx = useCallback((type: CtxType) => setCtx({ open: true, type }), []);
  const closeCtx = useCallback(() => setCtx((c) => ({ ...c, open: false })), []);

  /* ── 确认对话框（Promise-based） ── */
  const requestConfirm = useCallback((opts: ConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      confirmResolverRef.current = resolve;
      setConfirmState(opts);
    });
  }, []);
  const resolveConfirm = useCallback((val: boolean) => {
    setConfirmState(null);
    if (confirmResolverRef.current) {
      confirmResolverRef.current(val);
      confirmResolverRef.current = null;
    }
  }, []);

  /* ── 看板 ── */
  const refreshBoard = useCallback(async () => {
    // 演示模式：直接使用 mock 数据，不调用真实 API
    if (demoMode) {
      const list = MOCK_MEETINGS.map((m: any) => ({
        id: m.id,
        title: m.title,
        topic: m.topic || m.title,
        status: m.status,
        date: m.date,
        progress: m.progress,
        is_running: m.status === 'running',
        tags: [],
      }));
      setMeetings(list);
      setMeetingsLoading(false);
      setMeetingsError(null);
      return;
    }
    setMeetingsLoading(true);
    setMeetingsError(null);
    try {
      const data = await apiListMeetings('', 50, 0, false);
      const raw = Array.isArray(data) ? data : (data?.items || data?.meetings || []);
      const stageLabel: Record<string, string> = {
        clarify: '澄清', intra: '讨论', intra_team: '讨论',
        cross: '辩论', cross_team: '辩论',
        evidence: '校验', evidence_check: '校验',
        arbitrate: '仲裁', produce: '产出',
      };
      const list = raw.map((m: any) => ({
        id: m.id || m.meeting_id,
        title: m.title || m.topic || '未命名议题',
        topic: m.topic || '',
        status: m.status || 'pending',
        date: m.date || (m.created_at ? m.created_at.slice(0, 16).replace('T', ' ') : '—'),
        progress: m.progress || stageLabel[m.stage] || (m.stage ? m.stage : '—'),
        is_running: !!m.is_running,
        tags: m.tags || [],
      }));
      setMeetings(list);
    } catch (e: any) {
      setMeetingsError(e.message || '加载会议列表失败');
      setMeetings([]); // 失败时清空，不显示旧的 mock 数据
      toast('会议列表加载失败: ' + (e.message || '请检查后端连接'), 'error', 6000);
      appendLog('刷新会议列表失败: ' + e.message, 'error', 'board');
    } finally {
      setMeetingsLoading(false);
    }
  }, [appendLog, demoMode, toast]);

  /* ── 状态辅助 ── */
  const statusText = useCallback((s: string) => STATUS_TEXT[s] || s, []);
  const stageName = useCallback((s: string) => {
    const i = STAGE_KEYS.indexOf(s as any);
    return i >= 0 ? STAGES[i].name : '';
  }, []);

  const updateStageTrack = useCallback((stage: string) => {
    const i = STAGE_KEYS.indexOf(stage as any);
    if (i >= 0) setMeeting((m) => ({ ...m, stage: i }));
  }, []);
  const updateMeetingStatus = useCallback((status: string) => {
    setMeeting((m) => {
      const startedAt = (status === 'running' && !m.startedAt) ? Date.now() : m.startedAt;
      return { ...m, status, startedAt, paused: status === 'paused' ? true : (status === 'running' ? false : m.paused) };
    });
  }, []);
  const appendMeetingMessage = useCallback((msg: MeetingMessage) => {
    setMeeting((m) => {
      // 去重：相同 id 的消息不重复添加（断线重连增量回放时可能收到重复事件）
      if (msg.id && m.messages.some((existing) => existing.id === msg.id)) return m;
      return { ...m, messages: [...m.messages, msg] };
    });
  }, []);

  /* ── 引用回复 ── */
  const setReplyTarget = useCallback((msg: MeetingMessage | null) => {
    setMeeting((m) => ({ ...m, replyTarget: msg, interveneOpen: msg ? true : m.interveneOpen }));
  }, []);

  /* ── WS 客户端 ── */
  const getWs = useCallback(() => {
    if (!wsRef.current) {
      wsRef.current = new MeetingWsClient({
        onSnapshot: (state) => setMeeting((m) => ({
          ...m,
          messages: state.messages ?? m.messages,
          conflicts: state.conflicts ?? m.conflicts,
          claims: state.claims ?? m.claims,
          confidence: state.confidence_flags ?? m.confidence,
          stage: state.stage != null ? Math.max(0, STAGE_KEYS.indexOf(state.stage)) : m.stage,
          status: state.status ?? m.status,
          startedAt: state.started_at ? new Date(state.started_at).getTime() : m.startedAt,
          paused: state.paused ?? m.paused,
        })),
        onAgentSpoke: (msg) => appendMeetingMessage({
          speaker: msg.payload?.speaker || msg.speaker || '',
          speaker_role: msg.payload?.speaker_role || msg.payload?.role,
          content: msg.payload?.content || msg.content || '',
          stage: msg.payload?.stage || msg.stage || '',
          ts: Date.now(),
          id: msg.payload?.message_id || msg.id,
        }),
        onStageChanged: (msg) => {
          const to = msg.payload?.to || msg.to;
          updateStageTrack(to);
          appendLog(`阶段切换 → ${stageName(to) || to}`, 'info', 'stage');
        },
        onRunStarted: () => { updateMeetingStatus('running'); appendLog('会议已开始运行', 'info', 'meeting'); },
        onControlSignal: (msg) => { const s = msg.payload?.status || msg.status; if (s) updateMeetingStatus(s); },
        onControlAck: (msg) => updateMeetingStatus(msg.status),
        onInterventionReply: (msg) => {
          const reply = msg.payload?.message;
          if (reply) appendMeetingMessage({
            speaker: '主持人', content: reply.content || reply.text || '',
            stage: 'intervention', ts: Date.now(), isIntervention: true,
            id: reply.id,
          });
        },
        onBorrowRequest: (msg) => {
          const req = msg.payload?.pending_borrow_request || msg.pending_borrow_request;
          if (req) {
            setMeeting((m) => ({ ...m, borrowRequest: req }));
            appendLog(`收到借调请求：${req.from_role} → ${req.to_role}`, 'info', 'borrow');
          }
        },
        onBorrowResolved: (msg) => {
          setMeeting((m) => ({ ...m, borrowRequest: null }));
          if (msg.type === 'borrow.approved_by_user') { appendLog('借调请求已批准', 'info', 'borrow'); toast('已批准借调请求', 'success'); }
          else if (msg.type === 'borrow.rejected_by_user') { appendLog('借调请求已拒绝', 'warning', 'borrow'); toast('已拒绝借调请求', 'warning'); }
          else if (msg.type === 'borrow.frozen') { appendLog('借调已冻结', 'warning', 'borrow'); }
          else if (msg.type === 'borrow.auto_approved') { appendLog('借调已自动批准（超时未响应）', 'info', 'borrow'); }
        },
        onProduceProgress: (msg) => {
          const p = msg.payload || {};
          if (p.message) appendLog(p.message, 'info', 'produce');
        },
        onProduceDegradation: (msg) => {
          appendLog(`产出降级: ${msg.payload?.reason || '未知原因'}`, 'warning', 'produce');
          toast('产出降级，请查看日志', 'warning');
        },
        onLogEntry: (msg) => {
          const e = msg.payload || {};
          appendLog(e.message || e.msg || '', e.level || 'info', e.category);
        },
        onAuthRequired: () => {
          if (!authExpiredFired.current) {
            authExpiredFired.current = true;
            commitLogout();
            setUserState(null);
            setAuthExpired(true);
          }
        },
      });
    }
    return wsRef.current;
  }, [appendLog, appendMeetingMessage, updateStageTrack, updateMeetingStatus, stageName, toast]);

  /* ── 打开/启动会议 ── */
  const connectMeeting = useCallback((id: string) => {
    // 防重复连接：如果已连接到同一会议，跳过
    if (wsRef.current && wsRef.current.currentMeetingId === id) return;
    getWs().connect(id);
  }, [getWs]);

  const loadMeetingDetail = useCallback(async (meetingId: string) => {
    try {
      const data = await apiGetMeeting(meetingId);
      setMeeting((m) => ({
        ...m,
        messages: data.messages ?? m.messages,
        conflicts: data.conflicts ?? m.conflicts,
        claims: data.claims ?? m.claims,
        confidence: data.confidence_flags ?? m.confidence,
        stage: data.stage ? Math.max(0, STAGE_KEYS.indexOf(data.stage)) : m.stage,
        status: data.status || m.status,
        title: (data.clarified_topic || data.topic || m.title).trim(),
        type: data.deliverable_type || m.type,
        currentMeetingId: meetingId,
        startedAt: data.started_at ? new Date(data.started_at).getTime() : m.startedAt,
        paused: data.paused ?? m.paused,
      }));
    } catch (e: any) {
      appendLog('加载会议详情失败: ' + e.message, 'error', 'meeting');
      toast('加载会议失败', 'error');
    }
  }, [appendLog, toast]);

  const openMeeting = useCallback(async (id: string) => {
    // 防重复打开：同一会议且已有数据则仅确保 WS 连接
    if (meeting.currentMeetingId === id && wsRef.current?.currentMeetingId === id) {
      return;
    }
    setMeeting((m) => ({ ...INITIAL_MEETING, currentMeetingId: id }));
    connectMeeting(id);
    await loadMeetingDetail(id);
  }, [connectMeeting, loadMeetingDetail, meeting.currentMeetingId]);

  const startMeeting = useCallback(async (topic: string, type: string) => {
    // 演示模式：不允许发起真实会议
    if (demoMode) {
      toast('演示模式下无法发起会议，请登录后使用完整功能', 'warning');
      appendLog('演示模式下发起会议被阻止', 'warning', 'demo');
      return null;
    }
    try {
      appendLog('正在创建会议...', 'info', 'meeting');
      const result = await apiCreateMeeting(topic, type);
      const meetingId = result.meeting_id;
      appendLog(`会议已创建: ${meetingId}`, 'info', 'meeting');
      setMeeting({ ...INITIAL_MEETING, currentMeetingId: meetingId, title: topic, type, status: 'running', startedAt: Date.now() });
      connectMeeting(meetingId);
      await apiRunMeeting(meetingId);
      appendLog('会议已启动，观察实时进度', 'info', 'meeting');
      toast('会议已启动', 'success');
      return meetingId;
    } catch (e: any) {
      appendLog('启动会议失败: ' + e.message, 'error', 'meeting');
      toast('启动会议失败: ' + e.message, 'error');
      return null;
    }
  }, [appendLog, connectMeeting, demoMode, toast]);

  const pauseMeeting = useCallback(async () => {
    const id = meeting.currentMeetingId;
    if (!id) { appendLog('未在会议中', 'warning', 'meeting'); return; }
    const willPause = !meeting.paused;
    try {
      await apiControlMeeting(id, willPause ? 'pause' : 'resume');
      setMeeting((m) => ({ ...m, paused: willPause, status: willPause ? 'paused' : 'running' }));
      appendLog(willPause ? '会议已暂停' : '会议已恢复', 'info', 'meeting');
      toast(willPause ? '会议已暂停' : '会议已恢复', 'info');
    } catch (e: any) {
      appendLog('控制失败: ' + e.message, 'error', 'meeting');
      toast('操作失败: ' + e.message, 'error');
    }
  }, [meeting.currentMeetingId, meeting.paused, appendLog, toast]);

  const abortMeeting = useCallback(async () => {
    const id = meeting.currentMeetingId;
    if (!id) { appendLog('未在会议中', 'warning', 'meeting'); return; }
    const confirmed = await requestConfirm({
      title: '终止会议',
      message: '确认终止会议？此操作不可撤销。',
      confirmText: '终止',
      cancelText: '取消',
      danger: true,
    });
    if (!confirmed) return;
    try {
      await apiControlMeeting(id, 'abort');
      appendLog('会议已终止', 'warning', 'meeting');
      updateMeetingStatus('aborted');
      toast('会议已终止', 'warning');
    } catch (e: any) {
      appendLog('终止失败: ' + e.message, 'error', 'meeting');
      toast('终止失败: ' + e.message, 'error');
    }
  }, [meeting.currentMeetingId, appendLog, updateMeetingStatus, requestConfirm, toast]);

  const toggleIntervene = useCallback(() => {
    setMeeting((m) => ({ ...m, interveneOpen: !m.interveneOpen, replyTarget: m.interveneOpen ? null : m.replyTarget }));
  }, []);

  const sendIntervention = useCallback(async (content: string) => {
    const id = meeting.currentMeetingId;
    if (!id) { appendLog('未在会议中', 'warning', 'meeting'); return; }
    const replyToId = meeting.replyTarget?.id || null;
    try {
      await apiIntervene(id, content, replyToId);
      setMeeting((m) => ({ ...m, interveneOpen: false, replyTarget: null }));
      appendMeetingMessage({
        speaker: user?.username || '你', content,
        stage: 'intervention', ts: Date.now(), isUser: true, isIntervention: true,
      });
      appendLog(replyToId ? '介入已发送（引用回复），等待 Agent 回复...' : '介入已发送，等待 Agent 回复...', 'info', 'intervention');
    } catch (e: any) {
      appendLog('介入失败: ' + e.message, 'error', 'intervention');
      toast('介入失败: ' + e.message, 'error');
    }
  }, [meeting.currentMeetingId, meeting.replyTarget, appendLog, appendMeetingMessage, toast, user?.username]);

  /* ── 借调批准/拒绝（通过 WS control signal） ── */
  const approveBorrow = useCallback((req: BorrowRequest) => {
    const ws = wsRef.current;
    if (!ws) { appendLog('WS 未连接，无法批准借调', 'error', 'borrow'); return; }
    ws.send({ type: 'control.signal', signal: 'approve_borrow', payload: { request_id: req.request_id } });
    appendLog(`正在批准借调：${req.from_role} → ${req.to_role}`, 'info', 'borrow');
  }, [appendLog]);

  const rejectBorrow = useCallback((req: BorrowRequest, reason?: string) => {
    const ws = wsRef.current;
    if (!ws) { appendLog('WS 未连接，无法拒绝借调', 'error', 'borrow'); return; }
    ws.send({ type: 'control.signal', signal: 'reject_borrow', payload: { request_id: req.request_id, reason: reason || '用户拒绝' } });
    appendLog(`已拒绝借调：${req.from_role} → ${req.to_role}`, 'warning', 'borrow');
  }, [appendLog]);

  /* ── 启动验证 + 系统 WS ── */
  useEffect(() => {
    (async () => {
      const token = getToken();
      if (token) {
        const u = await apiMe();
        if (u) { setUserState(u); refreshBoard(); }
        else { commitLogout(); setUserState(null); }
      }
      setAuthChecked(true);
    })();
    const disconnect = connectSystemWs({ onMeetingsChanged: () => { if (!demoMode) refreshBoard(); } });
    return () => { disconnect(); wsRef.current?.disconnect(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demoMode]);

  /* ── elapsed 不再在 context 中每秒更新，由 Meeting 视图基于 startedAt 本地计算 ── */

  const api: AppApi = useMemo(() => ({
    theme, toggleTheme, user, setUser, authChecked, authExpired, clearAuthExpired, logout,
    demoMode, enterDemo, exitDemo,
    logOpen, toggleLog: () => setLogOpen((o) => !o), logFilter, setLogFilter, logs, appendLog, clearLogs,
    cmdkOpen, openCmdk, closeCmdk,
    ctx, openCtx, closeCtx,
    selectedType, setSelectedType,
    meetings, meetingsLoading, meetingsError, refreshBoard,
    meeting, startMeeting, openMeeting, pauseMeeting, abortMeeting, toggleIntervene, sendIntervention,
    approveBorrow, rejectBorrow, setReplyTarget,
    requestConfirm, confirmState, resolveConfirm,
    toast, _toastFn: toastFnRef.current, _setToastFn,
    statusText, stageName,
  }), [
    theme, toggleTheme, user, setUser, authChecked, authExpired, clearAuthExpired, logout,
    demoMode, enterDemo, exitDemo,
    logOpen, logFilter, logs, appendLog, clearLogs, cmdkOpen, openCmdk, closeCmdk,
    ctx, openCtx, closeCtx, selectedType, meetings, meetingsLoading, meetingsError, refreshBoard,
    meeting, startMeeting, openMeeting, pauseMeeting, abortMeeting, toggleIntervene, sendIntervention,
    approveBorrow, rejectBorrow, setReplyTarget,
    requestConfirm, confirmState, resolveConfirm,
    toast, _setToastFn,
    statusText, stageName,
  ]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}
