import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite 配置：React 插件 + 把后端 REST / WS / health 代理到 127.0.0.1:8000
// 前端 dev server 跑在 5173，API 请求走 proxy 不需要 CORS
export default defineConfig({
  plugins: [react()],
  build: {
    cssMinify: false,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('monaco-editor') || id.includes('@monaco-editor')) return 'monaco'
            if (id.includes('echarts')) return 'echarts'
            if (id.includes('@xterm')) return 'xterm'
            if (id.includes('d3-force')) return 'd3'
            if (id.includes('antd') || id.includes('@ant-design')) return 'antd-vendor'
            if (id.includes('react') || id.includes('scheduler')) return 'react-vendor'
          }
        },
      },
    },
    chunkSizeWarningLimit: 1000,
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      // REST 会议接口（POST /meetings, GET /meetings/:id, /run, /control, /documents）
      '/meetings': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 工作区接口（文件读写/命令执行/代码运行）
      '/workspace': {
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
      // CAPTCHA / API 接口（值守模式、截图等）
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 调试端点
      '/debug': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 指标端点
      '/metrics': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // Agent 角色管理
      '/agent-roles': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
