// 应用入口：挂载 React 根节点
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { ErrorBoundary } from './components/ErrorBoundary.tsx'
import { initAuthToken } from './lib/api.ts'
import './index.css'

// [CON-03 修复] 启动前先初始化认证 token：localStorage → URL query → 后端 /debug/auth-info → env
// 必须 await，否则 React 组件挂载后发 API 请求时 token 还没就绪 → 401
initAuthToken()
  .catch(() => {
    // 静默失败：用户后续会看到登录/输入 token 提示
  })
  .finally(() => {
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        {/* [CON-05 修复] 顶层 ErrorBoundary：任何子组件抛错都降级到友好 UI。
            嵌套使用：main.tsx 的 ErrorBoundary 是最后一道兜底，
            App.tsx 内对浮窗面板用 PanelErrorBoundary 做局部隔离。 */}
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </StrictMode>,
    )
  })
