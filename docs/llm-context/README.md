# LLM Context — 关键依赖陷阱与正确模式

本目录存放 Conclave 项目中关键依赖库的**已知陷阱**和**正确使用模式**，供 AI 编码助手在修改相关代码前查阅。

## 何时阅读

当你需要修改以下模块的代码时，请先阅读对应的文档：

| 文件 | 适用场景 |
|---|---|
| `zustand-persist-patterns.md` | 修改 `frontend/src/stores/` 中任何使用 `persist` 中间件的 store；修改 `App.tsx` 中的 `AuthInit`；修改认证流程 |
| `fastapi-route-ordering.md` | 修改 `backend/app/routers/` 或 `backend/app/plugins/` 中任何 FastAPI 路由定义 |
| `auth-refresh-flow.md` | 修改认证相关代码（`auth.py`、`middleware.py`、`api.ts`、`auth-slice.ts`）；修改 CSRF 逻辑；修改 Token 过期时间 |

## 原则

1. **先查后写**：不要凭"看起来合理"猜测 API 用法，先读本目录文档
2. **同步更新**：如果发现新的陷阱或修复了已知问题，请更新对应文档
3. **不要复制兜底模式**：`AuthInit` 中的 3 秒兜底超时是 zustand persist 专用方案，不要复制到其他异步初始化场景
