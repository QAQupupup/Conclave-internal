// 值守状态图标按钮：放在顶部导航栏右侧
// - 未开启：灰色盾牌
// - 值守中：绿色盾牌
// - 有验证码待处理：绿色盾牌 + 红色脉冲角标
// - 点击：Popover 展开值守控制面板（开关 + 状态 + VNC入口）
import { useEffect, useState, useCallback } from 'react'
import { Button, Tooltip, Badge, Popover, Switch, Tag, Space, Typography, message } from 'antd'
import {
  SafetyCertificateOutlined,
  SafetyOutlined,
  GlobalOutlined,
  ReloadOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import {
  getCaptchaStatus,
  setGuardMode as apiSetGuardMode,
} from '../lib/api.ts'
import { STORAGE_KEYS } from '../constants.ts'

const { Text, Paragraph } = Typography

/** VNC noVNC 地址 */
const VNC_URL = '/vnc/vnc.html?autoconnect=true&resize=scale&view_clip=auto'

export function GuardButton() {
  const [guardMode, setGuardMode] = useState(false)
  const [pending, setPending] = useState(false)
  const [vncReady, setVncReady] = useState(false)
  const [loading, setLoading] = useState(false)
  const [popoverOpen, setPopoverOpen] = useState(false)

  // 拉取初始值守状态
  const fetchStatus = useCallback(async () => {
    try {
      const status = await getCaptchaStatus()
      setGuardMode(status.guard_mode)
      setPending((status.pending_count ?? 0) > 0)
      setVncReady(Boolean(status.vnc_ready))
    } catch {
      // ignore - 可能在非会议页面
    }
  }, [])

  useEffect(() => {
    fetchStatus()
    // 定期刷新状态
    const timer = setInterval(fetchStatus, 5000)
    return () => clearInterval(timer)
  }, [fetchStatus])

  // 监听 system WebSocket 事件（captcha.pending/resolved/timeout）
  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const base = `${proto}://${window.location.host}/ws/system`
    const params = new URLSearchParams()
    try {
      const token = localStorage.getItem(STORAGE_KEYS.authToken) || localStorage.getItem(STORAGE_KEYS.apiToken)
      if (token) params.set('token', token)
    } catch { /* ignore */ }
    const qs = params.toString()
    const ws = new WebSocket(qs ? `${base}?${qs}` : base)

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        if (data.type === 'captcha.pending') {
          setPending(true)
        } else if (data.type === 'captcha.resolved' || data.type === 'captcha.timeout') {
          setPending(false)
        }
      } catch { /* ignore */ }
    }

    return () => {
      ws.close()
    }
  }, [])

  const handleToggle = async (checked: boolean) => {
    setLoading(true)
    try {
      await apiSetGuardMode(checked)
      setGuardMode(checked)
      message.success(checked ? '值守模式已开启' : '值守模式已关闭')
    } catch {
      message.error('切换值守模式失败')
    } finally {
      setLoading(false)
    }
  }

  const handleOpenVnc = () => {
    window.open(VNC_URL, '_blank', 'width=1024,height=768')
  }

  const handleRefresh = () => {
    fetchStatus()
    message.info('已刷新值守状态')
  }

  // 按钮图标：值守中使用实心盾牌（带认证勾），未开启使用空心盾牌
  const icon = guardMode
    ? <SafetyCertificateOutlined />
    : <SafetyOutlined />

  // 值守中使用圆形按钮 + 脉冲动效，未开启使用普通text按钮
  const shape: 'circle' | 'default' = guardMode ? 'circle' : 'default'
  const btnClassName = guardMode
    ? (pending ? 'guard-btn-pending guard-btn-pulse' : 'guard-btn-active guard-btn-pulse')
    : 'guard-btn-off'

  // 待处理时显示红色角标
  const buttonContent = (
    <Button
      type={guardMode ? 'primary' : 'text'}
      size="small"
      shape={shape}
      icon={icon}
      loading={loading}
      className={btnClassName}
      onClick={() => setPopoverOpen(!popoverOpen)}
    />
  )

  const button = pending ? (
    <Badge dot color="red" offset={[-2, 2]}>
      {buttonContent}
    </Badge>
  ) : buttonContent

  const tooltipTitle = guardMode
    ? (pending ? '值守中 · 有验证码待处理' : '值守中 · 就绪')
    : '值守模式已关闭'

  const popoverContent = (
    <div style={{ width: 240 }}>
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Text strong>监管值守</Text>
          <Switch
            size="small"
            checked={guardMode}
            loading={loading}
            onChange={handleToggle}
            checkedChildren="开"
            unCheckedChildren="关"
          />
        </div>

        {guardMode ? (
          <>
            {pending ? (
              <Tag color="red" icon={<ExclamationCircleOutlined />} style={{ margin: 0 }}>
                有验证码待处理，请在弹窗中协助
              </Tag>
            ) : (
              <Tag color="green" icon={<SafetyCertificateOutlined />} style={{ margin: 0 }}>
                值守模式就绪
              </Tag>
            )}

            {vncReady && (
              <Tag color="blue" icon={<GlobalOutlined />} style={{ margin: 0 }}>
                VNC 浏览器就绪
              </Tag>
            )}

            <Paragraph type="secondary" style={{ fontSize: 12, margin: 0, lineHeight: 1.6 }}>
              开启后将自动处理Web搜索中的验证码。遇到无法自动处理的情况时，会弹出窗口请求您协助登录或输入验证码。
            </Paragraph>

            <Space size={4}>
              {vncReady && (
                <Button size="small" icon={<GlobalOutlined />} onClick={handleOpenVnc}>
                  打开 VNC
                </Button>
              )}
              <Button size="small" icon={<ReloadOutlined />} onClick={handleRefresh}>
                刷新状态
              </Button>
            </Space>
          </>
        ) : (
          <Paragraph type="secondary" style={{ fontSize: 12, margin: 0, lineHeight: 1.6 }}>
            开启监管值守后，系统将自动处理Web搜索过程中遇到的验证码和登录状态问题。
          </Paragraph>
        )}
      </Space>
    </div>
  )

  return (
    <Popover
      content={popoverContent}
      title={null}
      trigger="click"
      open={popoverOpen}
      onOpenChange={setPopoverOpen}
      placement="bottomRight"
      overlayStyle={{ zIndex: 'var(--z-popover, 1050)' }}
    >
      <Tooltip title={tooltipTitle} placement="bottom">
        {button}
      </Tooltip>
    </Popover>
  )
}
