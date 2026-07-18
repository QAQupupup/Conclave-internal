/* ErrorBoundary — 捕获子组件未处理错误，展示友好降级 UI 而非白屏 */
import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props { children: ReactNode; fallback?: ReactNode }
interface State { hasError: boolean; error: Error | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 记录到控制台（后续可接入 Sentry 等错误监控）
    console.error('[ErrorBoundary] 组件渲染错误:', error, info);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="error-boundary">
          <div className="error-boundary-icon">!</div>
          <h3 className="error-boundary-title">页面出现错误</h3>
          <p className="error-boundary-msg">{this.state.error?.message || '组件渲染异常，请刷新页面重试'}</p>
          <button className="ctrl-btn primary" onClick={this.handleReset}>刷新页面</button>
        </div>
      );
    }
    return this.props.children;
  }
}
