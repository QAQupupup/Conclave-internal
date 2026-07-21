import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

// Conclave 前端 React 工程配置
// 入口为 app.html（对应 nginx 的 /app 路由）。
// dev 模式下通过中间件实现 /app/* 路径回退到 app.html（historyApiFallback）。
export default defineConfig({
  plugins: [
    react(),
    // Dev 模式 history fallback：所有 /app 开头的非文件请求回退到 app.html
    {
      name: 'conclave-app-fallback',
      configureServer(server) {
        server.middlewares.use((req, _res, next) => {
          const url = req.url || '/';
          // 只处理 /app 开头，且不是静态资源（不含 .）且不是 API/WebSocket 代理路径
          if (
            url.startsWith('/app') &&
            !url.includes('.') &&
            !url.startsWith('/app.html')
          ) {
            req.url = '/app.html';
          }
          next();
        });
      },
    },
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: resolve(__dirname, 'app.html'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/meetings': 'http://localhost:8000',
      '/workspace': 'http://localhost:8000',
      '/ws': { target: 'http://localhost:8000', ws: true },
      '/health': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/agent-roles': 'http://localhost:8000',
      '/preferences': 'http://localhost:8000',
      '/llm': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/metrics': 'http://localhost:8000',
      '/audit': 'http://localhost:8000',
      '/debug': 'http://localhost:8000',
      '/captcha': 'http://localhost:8000',
      '/config': 'http://localhost:8000',
      '/documents': 'http://localhost:8000',
      '/net-auth': 'http://localhost:8000',
      '/docker-hosts': 'http://localhost:8000',
      '/regression': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
