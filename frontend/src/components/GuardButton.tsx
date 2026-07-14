// 右侧吸边值守按钮：常态显示浅蓝色小盾牌，悬停展开为值守开关
import { useEffect, useRef, useState } from 'react'
import { SafetyCertificateOutlined, SafetyOutlined } from '@ant-design/icons'
import { CaptchaGuard } from './CaptchaGuard.tsx'

interface GuardButtonProps {
  /** 当前路由路径；首页不渲染 */
  path: string
}

export function GuardButton({ path }: GuardButtonProps) {
  const [expanded, setExpanded] = useState(false)
  const [guardStatus, setGuardStatus] = useState<{ guardMode: boolean; hasPending: boolean }>({
    guardMode: false,
    hasPending: false,
  })
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  useEffect(() => {
    return () => { clearTimer() }
  }, [])

  if (path === '/') return null

  const handleMouseEnter = () => {
    clearTimer()
    setExpanded(true)
  }

  const handleMouseLeave = () => {
    timerRef.current = setTimeout(() => setExpanded(false), 800)
  }

  const active = guardStatus.guardMode
  const pending = guardStatus.hasPending
  const shieldColor = pending ? '#ff4d4f' : active ? '#0958d9' : '#1677ff'
  const shieldBg = pending ? '#fff2f0' : active ? '#e6f4ff' : '#f0f7ff'

  return (
    <div
      data-testid="guard-button"
      className="guard-button"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{
        width: expanded ? 260 : 32,
        padding: expanded ? '5px 10px' : '5px 5px',
        boxShadow: expanded ? '0 2px 8px rgba(0,0,0,0.08)' : '-2px 0 6px rgba(0,0,0,0.04)',
      }}
    >
      <div
        data-testid="guard-shield"
        className="guard-shield"
        style={{ background: shieldBg, color: shieldColor }}
        title={active ? (pending ? '值守中 · 有待处理验证码' : '值守中') : '值守已关闭'}
      >
        {active ? <SafetyCertificateOutlined className="guard-icon" /> : <SafetyOutlined className="guard-icon" />}
      </div>

      <div
        data-testid="guard-panel"
        className="guard-panel"
        style={{ opacity: expanded ? 1 : 0 }}
      >
        <CaptchaGuard compact onStatusChange={setGuardStatus} />
      </div>
    </div>
  )
}
