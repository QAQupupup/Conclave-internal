import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite 配置：React 插件 + 把后端 REST / WS / health 代理到 127.0.0.1:8000
// 前端 dev server 跑在 5173，API 请求走 proxy 不需要 CORS
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      // REST 会议接口（POST /meetings, GET /meetings/:id, /run, /control, /documents）
      '/meetings': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // WebSocket 端点 /ws/meetings/{meeting_id}
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
      // 健康检查
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
