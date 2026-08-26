# Zustand Persist 正确模式

## 核心陷阱

### 陷阱 1：onRehydrateStorage 中调用异步函数会阻塞 hydration

**错误模式**：
```typescript
// ❌ 错误：在 onRehydrateStorage 中调用 fetchUser() 等异步函数
onRehydrateStorage: () => async (state) => {
  await state?.fetchUser();  // 这会阻塞 hydration 完成信号！
}
```

**正确模式**：
```typescript
// ✅ 正确：onRehydrateStorage 只做同步标记
onRehydrateStorage: () => (state, error) => {
  if (error) {
    useAuthStore.setState({ hasHydrated: true, isLoading: false });
    return;
  }
  useAuthStore.setState({ hasHydrated: true });
}
```

异步认证逻辑放在组件层 `useEffect` 中处理（见 `App.tsx` 的 `AuthInit` 组件）。

### 陷阱 2：无限等待 hydration 完成

zustand persist 的 hydration 是异步的，在以下边缘情况下可能**永远不完成**：
- 浏览器隐私模式限制 localStorage
- 存储配额接近上限
- 浏览器扩展干扰（如隐私保护扩展阻断 storage API）
- `createJSONStorage` 的 Promise 链不 resolve

**正确模式**：使用 `onFinishHydration` 监听 + 超时兜底。参考 `App.tsx` 中 `AuthInit` 的实现：
1. 先检查 `persist.hasHydrated()` 是否已完成
2. 否则监听 `persist.onFinishHydration()` 回调
3. 设置超时（`VITE_AUTH_HYDRATION_TIMEOUT_MS`，默认 3000ms）
4. 超时后手动从 `localStorage.getItem('conclave:auth')` 读取，**必须检查 version 字段**
5. 读取失败时清除 auth state，标记 hydration 完成

### 陷阱 3：手动 localStorage 读取绕过版本控制

persist 中间件使用 `version` 字段进行 schema 迁移。手动读取 localStorage 时必须检查版本：

```typescript
// ✅ 正确：检查 version 是否匹配
const PERSIST_VERSION = 1; // 必须与 persist 配置中的 version 一致
const parsed = JSON.parse(raw);
if (parsed && parsed.version === PERSIST_VERSION) {
  const token = parsed?.state?.token;
  // 使用 token
}
```

如果版本不匹配，**丢弃数据**，不要注入 store——否则旧版数据结构可能导致运行时错误。

### 陷阱 4：persist 的 storage 默认行为

不要自定义 `createJSONStorage` 除非有特殊需求。默认 `storage: createJSONStorage(() => localStorage)` 已足够。自定义 wrapper 可能引入额外的 Promise 链导致 hydration 不 resolve。

## AuthInit 组件说明

`frontend/src/App.tsx` 中的 `AuthInit` 是认证初始化的唯一入口。**不要在其他地方重复实现 hydration 等待逻辑**。

流程：
1. 等待 zustand persist hydration 完成（含超时兜底）
2. token 存在 → `fetchUser()` 验证 token
3. token 无效或过期 → `silentRefresh()` 用 refresh_token cookie 刷新
4. 无 token → `silentRefresh()` 尝试 cookie 刷新
5. 全部失败 → 清除认证状态，`ProtectedRoute` 重定向到登录页

**重要**：AuthInit 的超时兜底是**专用方案**，不适用于其他异步初始化场景（如 WebSocket 连接、IndexedDB 加载）。其他场景应使用标准 React Suspense 或 loading 状态。

## persist 配置参考

```typescript
persist(
  (set, get) => ({ /* store implementation */ }),
  {
    name: 'conclave:auth',        // localStorage key
    version: 1,                    // schema version，手动 localStorage 读取时必须匹配
    partialize: (state) => ({ token: state.token }),  // 只持久化 token，不持久化 user/isLoading
    onRehydrateStorage: () => (state, error) => {
      // 只做同步标记！
      if (error) { useAuthStore.setState({ hasHydrated: true, isLoading: false }); return; }
      useAuthStore.setState({ hasHydrated: true });
    },
    migrate: (persistedState, version) => {
      // 版本迁移逻辑
      if (version < 1) return { token: (persistedState as any)?.token ?? null };
      return persistedState;
    },
  }
)
```

## 修改 persist 配置时的检查清单

1. 修改 `version` 后，同步更新 `App.tsx` 中 `AuthInit` 的 `PERSIST_VERSION` 常量
2. 添加 `migrate` 函数处理旧版数据
3. 不要在 `onRehydrateStorage` 中调用任何异步函数
4. 不要持久化 `user` 对象或 `isLoading` 状态（通过 `partialize` 控制）
5. 修改后测试：正常登录 → 刷新页面 → 隐私模式刷新 → 清除 localStorage 后刷新
