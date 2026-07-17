import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

// Conclave 前端 React 工程配置
// 入口为 app.html（对应 nginx 的 /app 路由）。portal(index.html) 与 demo.html
// 放在 public/ 下，构建时原样拷贝到 dist 根，由 nginx 分别在 / 与 /demo 提供。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  // MPA 模式：portal(index.html)、app.html、demo.html 各自独立入口
  appType: 'mpa',
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: resolve(__dirname, 'app.html'),
    },
  },
  server: {
    port: 5173,
    // 确保刷新 /app/board 等前端路由时返回 app.html
    // Vite dev 默认对 .html 入口做 history fallback
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
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
