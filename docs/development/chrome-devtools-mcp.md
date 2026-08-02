# Chrome DevTools MCP 开发者工具推荐

## 概述

Google 开源的 [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)（`@chrome-devtools/mcp`）是一个基于 Puppeteer + Chrome DevTools Protocol（CDP）的 MCP 服务器，为 AI 编码助手提供浏览器自动化和调试能力。

**结论：不集成到 Conclave 运行时，但推荐开发者在本地开发环境中使用。**

## 为什么不集成到 Conclave

1. **协议不匹配**：Chrome DevTools MCP 使用 MCP stdio 协议（面向 AI 编码助手的客户端-工具协议），而 Conclave 的工具系统基于 FastAPI + ToolPort 协议，两者架构不同
2. **功能重叠**：Conclave 已有完整的 Playwright 工具链（browser_tool.py、playwright_search.py），支持沙箱浏览器、反检测、CAPTCHA 处理等会议场景所需功能
3. **运行时不适用**：DevTools MCP 设计用于 AI 编码助手（如调试自己的代码），而非作为后端服务组件为会议讨论提供网页访问能力

## 为什么推荐开发者使用

在本地开发 Conclave 时，Chrome DevTools MCP 提供以下有价值的能力：

| 能力 | 用途 |
|------|------|
| Lighthouse 性能分析 | 分析前端性能瓶颈 |
| 网络请求拦截与分析 | 调试 API 调用、检查请求/响应 |
| DOM/CSS 检查 | 调试 UI 布局问题 |
| Console 日志读取 | 捕获浏览器端错误 |
| 性能追踪 | 识别渲染阻塞、内存泄漏 |
| 截图/快照 | 快速验证页面状态 |

## 安装方式

在你的 AI 编码助手（如 Trae）的 MCP 配置中添加：

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest"]
    }
  }
}
```

## 与 Conclave Playwright 的关系

| 维度 | Chrome DevTools MCP | Conclave Playwright 工具 |
|------|---------------------|--------------------------|
| 使用场景 | 开发调试 | 会议运行时网页访问 |
| 运行位置 | 开发者本地 IDE | Conclave Docker 沙箱 |
| 浏览器控制 | Puppeteer + CDP | Playwright + 反检测 |
| 反检测 | 无 | stealth_js + fingerprint 随机化 |
| CAPTCHA 处理 | 无 | CaptchaGuard + VNC 人工介入 |
| 多租户隔离 | 不需要 | Docker 容器级隔离 |

两者互补，不替代。
