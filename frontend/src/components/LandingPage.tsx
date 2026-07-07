// 系统封面页：优雅极简入口，点击"进入"后跳转至任务看板
import { useEffect, useState } from 'react'

interface LandingPageProps {
  onEnter: () => void
}

export function LandingPage({ onEnter }: LandingPageProps) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    // 入场动画
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
        <h1 className="landing-title">Conclave</h1>
        <p className="landing-tagline">
          多智能体会议系统 · 结构化议题审议与决策
        </p>
        <p className="landing-desc">
          多角色智能体协作 · 六阶段审议流程 · 实时可观测
        </p>
        <button
          type="button"
          className="btn btn-primary landing-enter-btn"
          onClick={onEnter}
        >
          进入系统
        </button>
      </div>
    </div>
  )
}
