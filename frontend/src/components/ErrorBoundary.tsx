// 错误边界：捕获子树组件异常，使用 AntD Result 组件渲染降级 UI
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Result, Button } from 'antd'

interface ErrorBoundaryProps {
  children: ReactNode
  fallbackTitle?: string
  resettable?: boolean
  renderFallback?: (args: { error: Error; reset: () => void }) => ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
  componentStack: string
}

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
      <div className="error-boundary-fallback" role="alert" aria-live="assertive">
        <Result
          status="error"
          title={title}
          subTitle={message}
          extra={[
            showReset && (
              <Button type="primary" key="reset" onClick={this.reset}>
                重试
              </Button>
            ),
            <Button key="home" onClick={this.goHome}>
              返回首页
            </Button>,
          ]}
        />
      </div>
    )
  }
}

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
      <div className="panel-error-fallback">
        <Result
          status="warning"
          title={`面板 ${this.props.panel} 加载失败`}
          subTitle={this.state.message}
          extra={
            <Button size="small" onClick={this.reset}>
              重试
            </Button>
          }
        />
      </div>
    )
  }
}
