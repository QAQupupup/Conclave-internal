import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { resolve } from 'node:path';

/**
 * 将长期稳定、始终首屏加载的 vendor 依赖拆分为独立 chunk：
 * - 降低单 chunk 体积（消除 >500kB 构建告警）
 * - 提升缓存命中率（vendor 变化频率远低于业务代码）
 * 仅拆"必然首屏加载"的包，不触碰 lazy 加载的模块（如 react-markdown），
 * 避免破坏现有 React.lazy 路由级代码分割。
 */
function manualChunks(id: string): string | undefined {
  if (!id.includes('node_modules')) return undefined;
  const segments = id.split('node_modules/')[1].split('/');
  const pkg = segments[0].startsWith('@') ? `${segments[0]}/${segments[1]}` : segments[0];

  if (['react', 'react-dom', 'scheduler', 'react-router', 'react-router-dom'].includes(pkg)) {
    return 'react-vendor';
  }
  if (pkg.startsWith('@tanstack/')) return 'tanstack-vendor';
  if (pkg === 'cmdk') return 'cmdk-vendor';
  return undefined;
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'conclave-spa-fallback',
      configureServer(server) {
        // 后端 API 前缀（注意：只匹配子路径，不匹配精确路径，因为 /admin、/meetings 等同时是前端路由）
        // 浏览器页面导航通过 Accept: text/html 判断（见下方），XHR/fetch 请求不会带 text/html
        const API_SUBPATHS = [
          '/api/', '/ws/', '/legacy/', '/websockify/',
          '/setup/', '/auth/', '/workspace/', '/health',
          '/agent-roles/', '/preferences/', '/tenants/', '/metrics/',
          '/audit/', '/debug/', '/captcha/', '/config/', '/documents/',
          '/net-auth/', '/docker-hosts/', '/regression/', '/system/', '/admin/',
          '/graph/', '/llm/', '/vnc.html', '/vnc/', '/meetings/', '/artifacts/',
        ];
        server.middlewares.use((req, _res, next) => {
          const url = req.url || '/';
          const method = (req.method || 'GET').toUpperCase();

          // 非 GET 请求不做 SPA fallback（POST/PUT/DELETE 等都是 API 调用）
          if (method !== 'GET') return next();

          // WebSocket 升级请求不拦截
          if (req.headers.upgrade === 'websocket') return next();

          // 静态文件不拦截
          const isStatic = url.includes('.') || url.startsWith('/node_modules');
          if (isStatic) return next();

          const accept = (req.headers.accept as string) || '';
          const isPageNav = accept.includes('text/html');

          if (isPageNav) {
            // 浏览器页面导航：始终返回 app.html（SPA 入口），由前端路由处理
            req.url = '/app.html';
            return next();
          }

          // XHR/fetch 请求（Accept: */* 或 application/json）：只对 API 子路径代理
          const isApi = API_SUBPATHS.some((p) => url.startsWith(p)) ||
            // /health 精确匹配是 API
            url === '/health' ||
            // /meetings 精确匹配且带查询参数（如 ?page_size=20）是 API；无查询时可能是前端导航，但非 text/html 就是 API
            (url.startsWith('/meetings') && !isPageNav) ||
            (url.startsWith('/admin') && !isPageNav);

          if (!isApi) {
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
      input: {
        app: resolve(__dirname, 'app.html'),
      },
      output: {
        manualChunks,
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/setup': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/ws': { target: process.env.VITE_WS_URL || 'ws://localhost:8000', ws: true },
      '/vnc.html': { target: process.env.VITE_VNC_URL || 'http://localhost:6080', ws: false },
      '/vnc': { target: process.env.VITE_VNC_URL || 'http://localhost:6080', ws: true },
      '/websockify': { target: process.env.VITE_VNC_URL || 'http://localhost:6080', ws: true },
      '/meetings': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      // ADR-017 Phase 1：产物查询 API（列表/单条/血缘）
      '/artifacts': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      // ADR-017 Phase 2：项目与议题池挂 /api 前缀（裸路径 /projects 是前端 SPA 路由）
      '/workspace': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/health': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/agent-roles': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/preferences': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/llm': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/auth': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/tenants': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/admin': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/graph': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/metrics': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/audit': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/debug': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/captcha': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/config': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/documents': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/net-auth': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/docker-hosts': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/regression': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/system': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
    },
  },
});
