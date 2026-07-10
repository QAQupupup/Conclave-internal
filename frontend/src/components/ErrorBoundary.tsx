// 错误边界：捕获子树组件异常，渲染降级 UI 并提供重置按钮
// [CON-05 修复] 旧版没有 ErrorBoundary，组件异常会冒泡导致整页白屏
// 现在按"全页兜底 + 子树兜底"两层隔离：
//   1) ErrorBoundary（页面级）— 任何子组件抛错都降级到友好 UI，可重置或回首页
//   2) PanelErrorBoundary（面板级）— 只覆盖右侧浮窗类面板，避免单个面板挂掉整页
import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
  /** 降级 UI 标题，缺省为通用 "页面出错了" */
  fallbackTitle?: string
  /** 是否可重置（提供"重试"按钮） */
  resettable?: boolean
  /** 自定义降级渲染（高级用法，例如面板级 fallback） */
  renderFallback?: (args: { error: Error; reset: () => void }) => ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
  /** 第一次出错的 stack，方便定位 */
  componentStack: string
}

/**
 * 页面级 ErrorBoundary。
 *
 * 用法：
 *   <ErrorBoundary>
 *     <App />
 *   </ErrorBoundary>
 *
 * 设计要点：
 * 1. 内部维护 state（hasError），getDerivedStateFromProps 不会重新触发 error 状态。
 * 2. componentDidCatch 中记录 componentStack 到 console.error 便于线上排查。
 * 3. 提供"重试"和"返回首页"两个恢复路径，避免白屏后无法继续。
 * 4. 不向用户暴露 stack（生产环境），仅显示 error.message 的安全部分。
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
    error: null,
    componentStack: '',
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // 仅控制台输出，不向用户暴露
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] 捕获到组件异常:', error, info.componentStack)
    this.setState({ componentStack: info.componentStack ?? '' })
  }

  reset = (): void => {
    this.setState({ hasError: false, error: null, componentStack: '' })
  }

  goHome = (): void => {
    this.setState({ hasError: false, error: null, componentStack: '' })
    if (typeof window !== 'undefined') {
      window.location.href = '/'
    }
  }

  override render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children
    }

    // 自定义 fallback 优先
    if (this.props.renderFallback) {
      return this.props.renderFallback({
        error: this.state.error ?? new Error('未知错误'),
        reset: this.reset,
      })
    }

    const title = this.props.fallbackTitle ?? '页面出错了'
    const message = this.state.error?.message || '组件渲染时发生异常'
    const showReset = this.props.resettable !== false

    return (
      <div
        className="error-boundary-fallback"
        role="alert"
        aria-live="assertive"
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          padding: '48px 24px',
          textAlign: 'center',
          color: 'var(--text-primary, #1a1a1a)',
        }}
      >
        <div
          aria-hidden
          style={{
            width: 56,
            height: 56,
            borderRadius: '50%',
            background: 'var(--bg-elev, #f5f5f5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: 16,
            fontSize: 28,
            color: 'var(--danger, #d33)',
          }}
        >
          !
        </div>
        <h1 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 600 }}>{title}</h1>
        <p
          style={{
            margin: '0 0 24px',
            fontSize: 14,
            color: 'var(--text-secondary, #666)',
            maxWidth: 480,
            lineHeight: 1.6,
          }}
        >
          {message}
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          {showReset && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={this.reset}
              style={{
                padding: '8px 16px',
                borderRadius: 6,
                border: 'none',
                background: 'var(--accent, #1677ff)',
                color: '#fff',
                cursor: 'pointer',
                fontSize: 14,
              }}
            >
              重试
            </button>
          )}
          <button
            type="button"
            className="btn btn-ghost"
            onClick={this.goHome}
            style={{
              padding: '8px 16px',
              borderRadius: 6,
              border: '1px solid var(--border, #d9d9d9)',
              background: 'transparent',
              color: 'var(--text-primary, #1a1a1a)',
              cursor: 'pointer',
              fontSize: 14,
            }}
          >
            返回首页
          </button>
        </div>
      </div>
    )
  }
}

/**
 * 面板级 ErrorBoundary：仅包裹浮窗（介入/证据/产出等），失败时不影响主聊天流。
 *
 * 用法：
 *   <PanelErrorBoundary panel="evidence">
 *     <EvidencePanel ... />
 *   </PanelErrorBoundary>
 */
interface PanelErrorBoundaryProps {
  children: ReactNode
  panel: string
}

interface PanelErrorBoundaryState {
  hasError: boolean
  message: string
}

export class PanelErrorBoundary extends Component<PanelErrorBoundaryProps, PanelErrorBoundaryState> {
  state: PanelErrorBoundaryState = { hasError: false, message: '' }

  static getDerivedStateFromError(error: Error): Partial<PanelErrorBoundaryState> {
    return { hasError: true, message: error.message }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error(`[PanelErrorBoundary:${this.props.panel}]`, error, info.componentStack)
  }

  reset = (): void => {
    this.setState({ hasError: false, message: '' })
  }

  override render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children
    }
    return (
      <div
        className="panel-error-fallback"
        style={{
          padding: 24,
          textAlign: 'center',
          color: 'var(--text-secondary, #666)',
          fontSize: 13,
        }}
      >
        <p style={{ margin: '0 0 12px' }}>面板 {this.props.panel} 加载失败</p>
        <p style={{ margin: '0 0 16px', color: 'var(--text-tertiary, #999)' }}>{this.state.message}</p>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={this.reset}
          style={{
            padding: '4px 12px',
            borderRadius: 4,
            border: '1px solid var(--border, #d9d9d9)',
            background: 'transparent',
            color: 'var(--text-primary, #1a1a1a)',
            cursor: 'pointer',
            fontSize: 12,
          }}
        >
          重试
        </button>
      </div>
    )
  }
}
