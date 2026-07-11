// 系统封面页：使用 AntD Button + Typography
import { useEffect, useState } from 'react'
import { Button, Typography } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'

interface LandingPageProps {
  onEnter: () => void
}

export function LandingPage({ onEnter }: LandingPageProps) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setVisible(true), 50)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className={`landing-page${visible ? ' visible' : ''}`}>
      <div className="landing-bg" />
      <div className="landing-content">
        <div className="landing-logo">
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
            <circle cx="24" cy="24" r="22" stroke="currentColor" strokeWidth="1.5" opacity="0.15" />
            <circle cx="24" cy="24" r="14" stroke="currentColor" strokeWidth="1.5" opacity="0.3" />
            <circle cx="24" cy="24" r="6" fill="currentColor" opacity="0.8" />
            <circle cx="24" cy="2" r="2.5" fill="currentColor" />
            <circle cx="24" cy="46" r="2.5" fill="currentColor" />
            <circle cx="2" cy="24" r="2.5" fill="currentColor" />
            <circle cx="46" cy="24" r="2.5" fill="currentColor" />
          </svg>
        </div>
        <Typography.Title level={1} className="landing-title" style={{ margin: '16px 0 8px' }}>
          Conclave
        </Typography.Title>
        <Typography.Paragraph className="landing-tagline" type="secondary" style={{ fontSize: 16, margin: '0 0 8px' }}>
          多智能体会议系统 · 结构化议题审议与决策
        </Typography.Paragraph>
        <Typography.Paragraph className="landing-desc" type="secondary" style={{ margin: '0 0 32px' }}>
          多角色智能体协作 · 六阶段审议流程 · 实时可观测
        </Typography.Paragraph>
        <Button
          type="primary"
          size="large"
          icon={<ArrowRightOutlined />}
          onClick={onEnter}
          className="landing-enter-btn"
        >
          进入系统
        </Button>
      </div>
    </div>
  )
}
