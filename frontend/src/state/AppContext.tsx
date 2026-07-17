import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react';
import { subscribeAuth, getAuthUser, commitLogout, type ConclaveUser } from '../lib/auth';
import { onUnauthorized, apiMe, apiListMeetings, apiCreateMeeting, apiRunMeeting, apiGetMeeting, apiControlMeeting, apiIntervene } from '../lib/api';
import { MeetingWsClient, connectSystemWs, STAGE_KEYS } from '../lib/ws';
import { MEETINGS as MOCK_MEETINGS, STAGES } from '../data/mock';

export type LogLevel = 'ALL' | 'INFO' | 'DEBUG' | 'WARN' | 'ERROR' | 'info' | 'debug' | 'warning' | 'error';
export type CtxType = 'overview' | 'evidence' | 'artifact' | 'token' | 'model';

export interface LogEntry { time: string; level: string; msg: string }

export interface MeetingState {
  messages: any[];
  conflicts: any[];
  claims: any[];
  confidence: any[];
  stage: number;
  status: string;
  currentMeetingId: string | null;
  title: string;
  type: string;
  interveneOpen: boolean;
  borrowRequest: any | null;
  elapsed: number;
  paused: boolean;
}

const INITIAL_MEETING: MeetingState = {
  messages: [], conflicts: [], claims: [], confidence: [],
  stage: 0, status: '', currentMeetingId: null, title: '微服务架构迁移方案',
  type: 'prd_openapi', interveneOpen: false, borrowRequest: null, elapsed: 32 * 60 + 14, paused: false,
};

const STATUS_TEXT: Record<string, string> = {
  running: '进行中', paused: '已暂停', done: '已完成', aborted: '已终止',
  failed: '失败', pending: '待开始', created: '待开始',
};

interface AppApi {
  theme: 'light' | 'dark';
  toggleTheme: () => void;
  user: ConclaveUser | null;
  setUser: (u: ConclaveUser | null) => void;
  authChecked: boolean;
  authExpired: boolean;
  clearAuthExpired: () => void;
  logout: () => void;
  logOpen: boolean;
  toggleLog: () => void;
  logFilter: string;
  setLogFilter: (l: string) => void;
  logs: LogEntry[];
  appendLog: (msg: string, level?: string) => void;
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
  refreshBoard: () => Promise<void>;
  meeting: MeetingState;
  startMeeting: (topic: string, type: string) => Promise<string | null>;
  openMeeting: (id: string) => Promise<void>;
  pauseMeeting: () => Promise<void>;
  abortMeeting: () => Promise<void>;
  toggleIntervene: () => void;
  sendIntervention: (content: string) => Promise<void>;
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
  const [logOpen, setLogOpen] = useState(false);
  const [logFilter, setLogFilter] = useState('ALL');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [ctx, setCtx] = useState<{ open: boolean; type: CtxType }>({ open: false, type: 'overview' });
  const [selectedType, setSelectedType] = useState('prd_openapi');
  const [meetings, setMeetings] = useState<any[]>(MOCK_MEETINGS);
  const [meeting, setMeeting] = useState<MeetingState>(INITIAL_MEETING);

  const wsRef = useRef<MeetingWsClient | null>(null);
  // 全局 401 去重：并发请求只触发一次 authExpired
  const authExpiredFired = useRef(false);

  /* ── 日志 ── */
  const appendLog = useCallback((msg: string, level: string = 'info') => {
    const lv = level === 'warning' ? 'WARN' : level.toUpperCase();
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    setLogs((prev) => [{ time, level: lv, msg }, ...prev].slice(0, 500));
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
  const setUser = useCallback((u: ConclaveUser | null) => setUserState(u), []);
  const clearAuthExpired = useCallback(() => {
    setAuthExpired(false);
    authExpiredFired.current = false;
  }, []);
  const logout = useCallback(() => {
    commitLogout();
    setUserState(null);
  }, []);
  useEffect(() => subscribeAuth(setUserState), []);

  /* ── 全局 401 拦截器（去重） ──
   * 任意 API 请求收到 401 → 标记 authExpired（仅首次触发）
   * App 根层监听 authExpired → 弹"会话过期"提示 → 跳转登录页（带 redirect）
   * 后续并发的 401 不会重复触发（authExpiredFired 去重） */
  useEffect(() => {
    onUnauthorized(() => {
      if (authExpiredFired.current) return;
      authExpiredFired.current = true;
      commitLogout();
      setUserState(null);
      setAuthExpired(true);
    });
  }, []);

  /* ── 命令面板 ── */
  const openCmdk = useCallback(() => setCmdkOpen(true), []);
  const closeCmdk = useCallback(() => setCmdkOpen(false), []);

  /* ── 上下文面板 ── */
  const openCtx = useCallback((type: CtxType) => setCtx({ open: true, type }), []);
  const closeCtx = useCallback(() => setCtx((c) => ({ ...c, open: false })), []);

  /* ── 看板 ── */
  const refreshBoard = useCallback(async () => {
    try {
      const data = await apiListMeetings('', 20, 0, true);
      const list = Array.isArray(data) ? data : (data?.items || data?.meetings || []);
      if (list.length) setMeetings(list);
    } catch (e: any) {
      appendLog('刷新会议列表失败: ' + e.message, 'warning');
    }
  }, [appendLog]);

  /* ── 会议状态辅助 ── */
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
    setMeeting((m) => ({ ...m, status }));
  }, []);
  const appendMeetingMessage = useCallback((msg: any) => {
    setMeeting((m) => ({ ...m, messages: [...m.messages, msg] }));
  }, []);

  /* ── 会议 WS 客户端（懒建，handlers 绑定到稳定 setter） ── */
  const getWs = useCallback(() => {
    if (!wsRef.current) {
      wsRef.current = new MeetingWsClient({
        onSnapshot: (state) => setMeeting((m) => ({
          ...m,
          messages: state.messages ?? m.messages,
          conflicts: state.conflicts ?? m.conflicts,
          claims: state.claims ?? m.claims,
          confidence: state.confidence_flags ?? m.confidence,
        })),
        onAgentSpoke: (msg) => appendMeetingMessage({
          speaker: msg.payload?.speaker || msg.speaker || '',
          content: msg.payload?.content || msg.content || '',
          stage: msg.payload?.stage || msg.stage || '',
          ts: Date.now(),
        }),
        onStageChanged: (msg) => updateStageTrack(msg.payload?.to || msg.to),
        onRunStarted: () => updateMeetingStatus('running'),
        onControlSignal: (msg) => { const s = msg.payload?.status || msg.status; if (s) updateMeetingStatus(s); },
        onControlAck: (msg) => updateMeetingStatus(msg.status),
        onInterventionReply: (msg) => {
          const reply = msg.payload?.message;
          if (reply) appendMeetingMessage({
            speaker: '主持人', content: reply.content || reply.text || '',
            stage: 'intervention', ts: Date.now(), isIntervention: true,
          });
        },
        onBorrowRequest: (msg) => {
          const req = msg.payload?.pending_borrow_request || msg.pending_borrow_request;
          if (req) setMeeting((m) => ({ ...m, borrowRequest: req }));
        },
        onBorrowResolved: (msg) => {
          setMeeting((m) => ({ ...m, borrowRequest: null }));
          if (msg.type === 'borrow.approved_by_user') appendLog('借调请求已批准', 'info');
          else if (msg.type === 'borrow.rejected_by_user') appendLog('借调请求已拒绝', 'warning');
          else if (msg.type === 'borrow.frozen') appendLog('借调已冻结', 'warning');
        },
        onProduceProgress: (msg) => {
          const p = msg.payload || {};
          if (p.message) appendLog(p.message, 'info');
        },
        onProduceDegradation: (msg) => appendLog(`产出降级: ${msg.payload?.reason || '未知原因'}`, 'warning'),
        onLogEntry: (msg) => {
          const e = msg.payload || {};
          appendLog(e.message || e.msg || '', e.level || 'info');
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
  }, [appendLog, appendMeetingMessage, updateStageTrack, updateMeetingStatus]);

  /* ── 打开/启动会议 ── */
  const connectMeeting = useCallback((id: string) => {
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
      }));
    } catch (e: any) {
      appendLog('加载会议详情失败: ' + e.message, 'error');
    }
  }, [appendLog]);

  const openMeeting = useCallback(async (id: string) => {
    setMeeting((m) => ({ ...m, currentMeetingId: id, messages: [] }));
    connectMeeting(id);
    await loadMeetingDetail(id);
  }, [connectMeeting, loadMeetingDetail]);

  const startMeeting = useCallback(async (topic: string, type: string) => {
    try {
      appendLog('正在创建会议...', 'info');
      const result = await apiCreateMeeting(topic, type);
      const meetingId = result.meeting_id;
      appendLog(`会议已创建: ${meetingId}`, 'info');
      setMeeting((m) => ({ ...m, currentMeetingId: meetingId, title: topic, type, messages: [], stage: 0, status: 'running', elapsed: 0 }));
      connectMeeting(meetingId);
      await apiRunMeeting(meetingId);
      appendLog('会议已启动，观察实时进度', 'info');
      return meetingId;
    } catch (e: any) {
      appendLog('启动会议失败: ' + e.message, 'error');
      return null;
    }
  }, [appendLog, connectMeeting]);

  const pauseMeeting = useCallback(async () => {
    const id = meeting.currentMeetingId;
    if (!id) { appendLog('未在会议中', 'warning'); return; }
    const willPause = !meeting.paused;
    try {
      await apiControlMeeting(id, willPause ? 'pause' : 'resume');
      setMeeting((m) => ({ ...m, paused: willPause, status: willPause ? 'paused' : 'running' }));
      appendLog(willPause ? '会议已暂停' : '会议已恢复', 'info');
    } catch (e: any) {
      appendLog('控制失败: ' + e.message, 'error');
    }
  }, [meeting.currentMeetingId, meeting.paused, appendLog]);

  const abortMeeting = useCallback(async () => {
    const id = meeting.currentMeetingId;
    if (!id) { appendLog('未在会议中', 'warning'); return; }
    if (!confirm('确认终止会议？此操作不可撤销。')) return;
    try {
      await apiControlMeeting(id, 'abort');
      appendLog('会议已终止', 'warning');
      updateMeetingStatus('aborted');
    } catch (e: any) {
      appendLog('终止失败: ' + e.message, 'error');
    }
  }, [meeting.currentMeetingId, appendLog, updateMeetingStatus]);

  const toggleIntervene = useCallback(() => {
    setMeeting((m) => ({ ...m, interveneOpen: !m.interveneOpen }));
  }, []);

  const sendIntervention = useCallback(async (content: string) => {
    const id = meeting.currentMeetingId;
    if (!id) { appendLog('未在会议中', 'warning'); return; }
    try {
      await apiIntervene(id, content);
      setMeeting((m) => ({ ...m, interveneOpen: false }));
      appendLog('介入已发送，等待 Agent 回复...', 'info');
    } catch (e: any) {
      appendLog('介入失败: ' + e.message, 'error');
    }
  }, [meeting.currentMeetingId, appendLog]);

  /* ── 启动时：验证 token（仅一次） ── */
  useEffect(() => {
    (async () => {
      const token = localStorage.getItem('conclave_token');
      if (token) {
        const u = await apiMe();
        if (u) { setUserState(u); refreshBoard(); }
        else { commitLogout(); setUserState(null); }
      }
      setAuthChecked(true);
    })();
    const disconnect = connectSystemWs({ onMeetingsChanged: () => refreshBoard() });
    return () => { disconnect(); wsRef.current?.disconnect(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── 会议运行计时器 ── */
  useEffect(() => {
    const t = setInterval(() => {
      setMeeting((m) => (m.status === 'running' ? { ...m, elapsed: m.elapsed + 1 } : m));
    }, 1000);
    return () => clearInterval(t);
  }, []);

  const api: AppApi = useMemo(() => ({
    theme, toggleTheme, user, setUser, authChecked, authExpired, clearAuthExpired, logout,
    logOpen, toggleLog: () => setLogOpen((o) => !o), logFilter, setLogFilter, logs, appendLog, clearLogs,
    cmdkOpen, openCmdk, closeCmdk,
    ctx, openCtx, closeCtx,
    selectedType, setSelectedType,
    meetings, refreshBoard,
    meeting, startMeeting, openMeeting, pauseMeeting, abortMeeting, toggleIntervene, sendIntervention,
    statusText, stageName,
  }), [
    theme, toggleTheme, user, setUser, authChecked, authExpired, clearAuthExpired, logout,
    logOpen, logFilter, logs, appendLog, clearLogs, cmdkOpen, openCmdk, closeCmdk,
    ctx, openCtx, closeCtx, selectedType, meetings, refreshBoard,
    meeting, startMeeting, openMeeting, pauseMeeting, abortMeeting, toggleIntervene, sendIntervention,
    statusText, stageName,
  ]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}
