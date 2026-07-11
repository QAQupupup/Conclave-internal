// CAPTCHA 值守守卫组件
// - 连接 /ws/system 监听 captcha.pending / captcha.resolved / captcha.timeout 事件
// - 顶栏显示值守模式开关 + 状态指示器
// - 收到 pending 事件弹出 Modal：展示截图、倒计时、手动处理按钮
import { useCallback, useEffect, useRef, useState } from 'react'
import { Modal, Button, Switch, Tag, Image, Alert, Progress, message, Space, Typography } from 'antd'
import {
  SafetyCertificateOutlined,
  SafetyOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  GlobalOutlined,
} from '@ant-design/icons'
import {
  getCaptchaStatus,
  setGuardMode as apiSetGuardMode,
  getCaptchaScreenshot,
  resolveCaptcha as apiResolveCaptcha,
  type CaptchaPendingPayload,
} from '../lib/api.ts'

const { Text, Paragraph } = Typography

/** 默认超时时间（秒），与后端 captcha_guard 默认值一致 */
const DEFAULT_TIMEOUT = 300
/** VNC noVNC 地址（通过 nginx 代理到后端 websockify:6080） */
const VNC_URL = '/vnc/vnc.html?autoconnect=true&resize=scale&view_clip=auto'

// ---------------------------------------------------------------------------
// System WebSocket 连接（/ws/system）
// ---------------------------------------------------------------------------

function buildSystemWsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const base = `${proto}://${window.location.host}/ws/system`
  const params = new URLSearchParams()
  try {
    const token = localStorage.getItem('conclave.api_token')
    if (token) params.set('token', token)
  } catch { /* ignore */ }
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}

interface PendingCaptcha {
  sessionId: string
  url: string
  captchaTypes: string[]
  pageTitle: string
  vncReady: boolean
  timeout: number
  /** data:image/png;base64,... 截图 */
  screenshot: string | null
}

export interface CaptchaGuardHandle {
  /** 当前值守模式是否开启 */
  guardMode: boolean
  /** 是否有 pending 验证码 */
  hasPending: boolean
}

interface CaptchaGuardProps {
  /** 是否以紧凑模式渲染（顶栏小开关），默认 false */
  compact?: boolean
  /** 状态变化回调 */
  onStatusChange?: (status: { guardMode: boolean; hasPending: boolean }) => void
}

/**
 * CAPTCHA 值守守卫组件。
 *
 * 使用方式：在应用根部挂载一次即可。它会自动：
 * 1. 连接 system WebSocket 监听 captcha 事件
 * 2. 初始化时拉取值守状态
 * 3. 在需要时弹出 Modal 提示用户处理验证码
 */
export function CaptchaGuard({ compact = false, onStatusChange }: CaptchaGuardProps) {
  // ---- 值守模式状态 ----
  const [guardMode, setGuardModeState] = useState(false)
  const [vncReady, setVncReady] = useState(false)
  const [toggling, setToggling] = useState(false)

  // ---- 当前待处理验证码 ----
  const [pending, setPending] = useState<PendingCaptcha | null>(null)
  const [screenshotLoading, setScreenshotLoading] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [screenshotError, setScreenshotError] = useState<string | null>(null)

  // ---- 倒计时 ----
  const [remaining, setRemaining] = useState(DEFAULT_TIMEOUT)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const deadlineRef = useRef<number>(0)

  // ---- WS 引用 ----
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closedByUnmountRef = useRef(false)

  // 通知父组件状态变化
  useEffect(() => {
    onStatusChange?.({ guardMode, hasPending: pending !== null })
  }, [guardMode, pending, onStatusChange])

  // -----------------------------------------------------------------------
  // 初始化：拉取当前值守状态
  // -----------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const status = await getCaptchaStatus()
        if (cancelled) return
        setGuardModeState(status.guard_mode)
        setVncReady(status.vnc_ready)
      } catch {
        // 后端可能尚未启动 captcha 路由，静默失败
      }
    })()
    return () => { cancelled = true }
  }, [])

  // -----------------------------------------------------------------------
  // 切换值守模式
  // -----------------------------------------------------------------------
  const handleToggleGuard = useCallback(async (checked: boolean) => {
    setToggling(true)
    try {
      const resp = await apiSetGuardMode(checked)
      setGuardModeState(resp.guard_mode)
      setVncReady(resp.vnc_ready)
      message.success(resp.guard_mode ? '值守模式已开启，遇到验证码时将暂停等待处理' : '值守模式已关闭')
    } catch (e) {
      message.error(`切换值守模式失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setToggling(false)
    }
  }, [])

  // -----------------------------------------------------------------------
  // 拉取截图
  // -----------------------------------------------------------------------
  const fetchScreenshot = useCallback(async (sessionId: string) => {
    setScreenshotLoading(true)
    setScreenshotError(null)
    try {
      const resp = await getCaptchaScreenshot(sessionId)
      setPending(prev => {
        if (!prev || prev.sessionId !== sessionId) return prev
        return { ...prev, screenshot: resp.screenshot }
      })
    } catch (e) {
      setScreenshotError(e instanceof Error ? e.message : '截图获取失败')
    } finally {
      setScreenshotLoading(false)
    }
  }, [])

  // -----------------------------------------------------------------------
  // 打开 VNC 窗口
  // -----------------------------------------------------------------------
  const handleOpenVnc = useCallback(() => {
    window.open(VNC_URL, '_blank', 'width=1280,height=800')
  }, [])

  // -----------------------------------------------------------------------
  // "已完成验证"按钮
  // -----------------------------------------------------------------------
  const handleResolve = useCallback(async () => {
    if (!pending) return
    setResolving(true)
    try {
      await apiResolveCaptcha(pending.sessionId)
      message.success('已通知后端继续执行')
      // 不立即关闭 Modal，等 captcha.resolved 事件到达后关闭
    } catch (e) {
      message.error(`操作失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setResolving(false)
    }
  }, [pending])

  // -----------------------------------------------------------------------
  // 倒计时管理
  // -----------------------------------------------------------------------
  const startCountdown = useCallback((seconds: number) => {
    if (timerRef.current) clearInterval(timerRef.current)
    deadlineRef.current = Date.now() + seconds * 1000
    setRemaining(seconds)
    timerRef.current = setInterval(() => {
      const left = Math.max(0, Math.round((deadlineRef.current - Date.now()) / 1000))
      setRemaining(left)
      if (left <= 0 && timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }, 500)
  }, [])

  const stopCountdown = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  // 卸载时清理倒计时
  useEffect(() => {
    return () => stopCountdown()
  }, [stopCountdown])

  // -----------------------------------------------------------------------
  // System WebSocket 连接
  // -----------------------------------------------------------------------
  useEffect(() => {
    closedByUnmountRef.current = false
    let attempt = 0

    const connect = () => {
      if (closedByUnmountRef.current) return
      const url = buildSystemWsUrl()
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (closedByUnmountRef.current) return
        attempt = 0
      }

      ws.onmessage = (ev: MessageEvent) => {
        if (closedByUnmountRef.current) return
        let data: unknown
        try {
          data = JSON.parse(typeof ev.data === 'string' ? ev.data : '')
        } catch {
          return
        }
        const frame = data as Record<string, unknown>
        const type = typeof frame.type === 'string' ? frame.type : ''

        switch (type) {
          case 'ping':
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'pong', ts: frame.ts }))
            }
            return
          case 'pong':
          case 'system.ready':
            return
          case 'captcha.pending': {
            const p = frame.payload as CaptchaPendingPayload
            if (!p || !p.session_id) return
            const newPending: PendingCaptcha = {
              sessionId: p.session_id,
              url: p.url ?? '',
              captchaTypes: p.captcha_types ?? [],
              pageTitle: p.page_title ?? '',
              vncReady: p.vnc_ready ?? false,
              timeout: p.timeout ?? DEFAULT_TIMEOUT,
              screenshot: null,
            }
            setPending(newPending)
            startCountdown(p.timeout ?? DEFAULT_TIMEOUT)
            // 异步拉取截图
            void fetchScreenshot(p.session_id)
            break
          }
          case 'captcha.resolved':
          case 'captcha.timeout': {
            const payload = frame.payload as { session_id?: string } | undefined
            const sid = payload?.session_id
            setPending(prev => {
              // 若事件携带 session_id 且与当前不匹配，忽略
              if (sid && prev && prev.sessionId !== sid) return prev
              return null
            })
            stopCountdown()
            if (type === 'captcha.timeout') {
              message.warning('验证码等待超时，流程已自动跳过')
            }
            break
          }
          default:
            // 忽略其他事件（system.* 等）
            break
        }
      }

      ws.onerror = () => {
        // 静默处理，等待重连
      }

      ws.onclose = () => {
        if (closedByUnmountRef.current) return
        wsRef.current = null
        attempt += 1
        const delay = Math.min(1000 * Math.pow(2, Math.min(attempt - 1, 4)), 30000)
        reconnectTimerRef.current = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      closedByUnmountRef.current = true
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      const ws = wsRef.current
      if (ws) {
        ws.onopen = null
        ws.onmessage = null
        ws.onerror = null
        ws.onclose = null
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close()
        }
        wsRef.current = null
      }
    }
  }, [fetchScreenshot, startCountdown, stopCountdown])

  // -----------------------------------------------------------------------
  // 手动刷新截图
  // -----------------------------------------------------------------------
  const handleRefreshScreenshot = useCallback(() => {
    if (pending) {
      void fetchScreenshot(pending.sessionId)
    }
  }, [pending, fetchScreenshot])

  // -----------------------------------------------------------------------
  // 格式化剩余时间
  // -----------------------------------------------------------------------
  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return `${m}:${String(s).padStart(2, '0')}`
  }

  const timeoutSecs = pending?.timeout ?? DEFAULT_TIMEOUT
  const progressPct = timeoutSecs > 0 ? Math.max(0, (remaining / timeoutSecs) * 100) : 0
  const timeColor = remaining <= 30 ? '#ff4d4f' : remaining <= 60 ? '#faad14' : '#52c41a'

  // -----------------------------------------------------------------------
  // 紧凑模式：顶栏小开关（嵌入 AppShell 导航栏）
  // -----------------------------------------------------------------------
  if (compact) {
    return (
      <>
        <Space size={6} style={{ alignItems: 'center' }}>
          <Switch
            size="small"
            checked={guardMode}
            loading={toggling}
            onChange={handleToggleGuard}
            checkedChildren={<SafetyCertificateOutlined />}
            unCheckedChildren={<SafetyOutlined />}
          />
          <Tag
            color={guardMode ? (pending ? 'red' : 'green') : 'default'}
            style={{ margin: 0, fontSize: 12, lineHeight: '20px' }}
            icon={guardMode ? <SafetyCertificateOutlined /> : <SafetyOutlined />}
          >
            值守: {guardMode ? '开' : '关'}
            {pending && ' · 待处理'}
          </Tag>
        </Space>

        <CaptchaModal
          pending={pending}
          remaining={remaining}
          progressPct={progressPct}
          timeColor={timeColor}
          formatTime={formatTime}
          screenshotLoading={screenshotLoading}
          screenshotError={screenshotError}
          resolving={resolving}
          onRefreshScreenshot={handleRefreshScreenshot}
          onOpenVnc={handleOpenVnc}
          onResolve={handleResolve}
        />
      </>
    )
  }

  // -----------------------------------------------------------------------
  // 完整模式（带标签和说明）
  // -----------------------------------------------------------------------
  return (
    <>
      <Space size={8} style={{ alignItems: 'center' }}>
        <Switch
          checked={guardMode}
          loading={toggling}
          onChange={handleToggleGuard}
          checkedChildren="值守开"
          unCheckedChildren="值守关"
        />
        {guardMode ? (
          <Tag color={pending ? 'red' : 'green'} icon={<SafetyCertificateOutlined />}>
            值守模式{pending ? ' · 有验证码待处理' : ' · 就绪'}
          </Tag>
        ) : (
          <Tag color="default" icon={<SafetyOutlined />}>值守模式已关闭</Tag>
        )}
        {vncReady && guardMode && <Tag color="blue">VNC 就绪</Tag>}
      </Space>

      <CaptchaModal
        pending={pending}
        remaining={remaining}
        progressPct={progressPct}
        timeColor={timeColor}
        formatTime={formatTime}
        screenshotLoading={screenshotLoading}
        screenshotError={screenshotError}
        resolving={resolving}
        onRefreshScreenshot={handleRefreshScreenshot}
        onOpenVnc={handleOpenVnc}
        onResolve={handleResolve}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// CAPTCHA Modal 子组件
// ---------------------------------------------------------------------------

interface CaptchaModalProps {
  pending: PendingCaptcha | null
  remaining: number
  progressPct: number
  timeColor: string
  formatTime: (s: number) => string
  screenshotLoading: boolean
  screenshotError: string | null
  resolving: boolean
  onRefreshScreenshot: () => void
  onOpenVnc: () => void
  onResolve: () => void
}

function CaptchaModal({
  pending,
  remaining,
  progressPct,
  timeColor,
  formatTime,
  screenshotLoading,
  screenshotError,
  resolving,
  onRefreshScreenshot,
  onOpenVnc,
  onResolve,
}: CaptchaModalProps) {
  return (
    <Modal
      open={pending !== null}
      title={
        <Space>
          <SafetyCertificateOutlined style={{ color: '#ff4d4f' }} />
          <span>检测到验证码 — 需要人工处理</span>
        </Space>
      }
      width={720}
      footer={null}
      closable={false}
      maskClosable={false}
      centered
      destroyOnClose
    >
      {pending && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* 验证码类型与页面信息 */}
          <Alert
            type="warning"
            showIcon
            message={
              <Space wrap>
                <span>验证码类型：</span>
                {pending.captchaTypes.length > 0 ? (
                  pending.captchaTypes.map(t => (
                    <Tag key={t} color="orange">{t}</Tag>
                  ))
                ) : (
                  <Tag>未知</Tag>
                )}
              </Space>
            }
            description={
              <div style={{ marginTop: 4 }}>
                <div>
                  <GlobalOutlined /> <Text strong>{pending.pageTitle || '(无标题)'}</Text>
                </div>
                <Paragraph
                  ellipsis={{ rows: 1, expandable: true, symbol: '展开' }}
                  style={{ marginBottom: 0, fontSize: 12, color: 'var(--text-secondary, #888)' }}
                >
                  {pending.url}
                </Paragraph>
              </div>
            }
          />

          {/* 截图区域 */}
          <div
            style={{
              border: '1px solid var(--border, #d9d9d9)',
              borderRadius: 6,
              overflow: 'hidden',
              background: '#f5f5f5',
              minHeight: 200,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              position: 'relative',
            }}
          >
            {pending.screenshot ? (
              <Image
                src={pending.screenshot}
                alt="页面截图"
                style={{ maxWidth: '100%', maxHeight: 400 }}
                preview={{ mask: '点击查看大图' }}
              />
            ) : screenshotLoading ? (
              <div style={{ padding: 32, color: '#888' }}>正在加载截图...</div>
            ) : screenshotError ? (
              <div style={{ padding: 32, color: '#ff4d4f', textAlign: 'center' }}>
                <div>截图加载失败：{screenshotError}</div>
                <Button size="small" style={{ marginTop: 8 }} onClick={onRefreshScreenshot}>
                  <ReloadOutlined /> 重试
                </Button>
              </div>
            ) : (
              <div style={{ padding: 32, color: '#888' }}>暂无截图</div>
            )}
            {pending.screenshot && (
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={onRefreshScreenshot}
                loading={screenshotLoading}
                style={{ position: 'absolute', top: 8, right: 8 }}
              >
                刷新截图
              </Button>
            )}
          </div>

          {/* 倒计时进度 */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>剩余处理时间</Text>
              <Text strong style={{ color: timeColor, fontSize: 16, fontVariantNumeric: 'tabular-nums' }}>
                {formatTime(remaining)}
              </Text>
            </div>
            <Progress
              percent={progressPct}
              showInfo={false}
              strokeColor={{
                '0%': '#52c41a',
                '50%': '#faad14',
                '100%': '#ff4d4f',
              }}
              size="small"
            />
            {remaining <= 60 && (
              <div style={{ fontSize: 12, color: timeColor, marginTop: 4 }}>
                即将超时，请尽快处理
              </div>
            )}
          </div>

          {/* 操作按钮 */}
          <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
            <Button
              size="large"
              icon={<GlobalOutlined />}
              onClick={onOpenVnc}
              disabled={!pending.vncReady}
            >
              打开浏览器窗口手动处理
            </Button>
            <Button
              type="primary"
              size="large"
              icon={<CheckCircleOutlined />}
              onClick={onResolve}
              loading={resolving}
            >
              已完成验证
            </Button>
          </div>

          {!pending.vncReady && (
            <Alert
              type="info"
              showIcon
              message="VNC 环境正在启动中，请稍候..."
              style={{ fontSize: 12 }}
            />
          )}
        </div>
      )}
    </Modal>
  )
}
