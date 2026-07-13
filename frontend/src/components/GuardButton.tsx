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

  if (path === '/') return null

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const handleMouseEnter = () => {
    clearTimer()
    setExpanded(true)
  }

  const handleMouseLeave = () => {
    timerRef.current = setTimeout(() => setExpanded(false), 800)
  }

  useEffect(() => {
    return () => { clearTimer() }
  }, [])

  const active = guardStatus.guardMode
  const pending = guardStatus.hasPending
  const shieldColor = pending ? '#ff4d4f' : active ? '#0958d9' : '#1677ff'
  const shieldBg = pending ? '#fff2f0' : active ? '#e6f4ff' : '#f0f7ff'

  return (
    <div
      data-testid="guard-button"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{
        position: 'fixed',
        top: 56,
        right: 0,
        zIndex: 1100,
        display: 'flex',
        alignItems: 'center',
        width: expanded ? 260 : 28,
        height: 28,
        padding: expanded ? '5px 10px' : '5px 0 5px 5px',
        background: 'var(--bg, #fff)',
        border: '1px solid var(--border, #e5e7eb)',
        borderRight: 'none',
        borderRadius: '6px 0 0 6px',
        boxShadow: expanded ? '0 2px 8px rgba(0,0,0,0.08)' : '-2px 0 6px rgba(0,0,0,0.04)',
        overflow: 'hidden',
        whiteSpace: 'nowrap',
        transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
        cursor: 'pointer',
      }}
    >
      <div
        data-testid="guard-shield"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 18,
          height: 18,
          borderRadius: '50%',
          background: shieldBg,
          color: shieldColor,
          flexShrink: 0,
          transition: 'all 0.25s ease',
        }}
        title={active ? (pending ? '值守中 · 有待处理验证码' : '值守中') : '值守已关闭'}
      >
        {active ? <SafetyCertificateOutlined style={{ fontSize: 11 }} /> : <SafetyOutlined style={{ fontSize: 11 }} />}
      </div>

      <div
        data-testid="guard-panel"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginLeft: 8,
          opacity: expanded ? 1 : 0,
          transition: 'opacity 0.2s ease',
        }}
      >
        <CaptchaGuard compact onStatusChange={setGuardStatus} />
      </div>
    </div>
  )
}
