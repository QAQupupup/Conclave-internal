import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { resolve } from 'node:path';

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'conclave-spa-fallback',
      configureServer(server) {
        server.middlewares.use((req, _res, next) => {
          const url = req.url || '/';
          if (
            !url.startsWith('/api') &&
            !url.startsWith('/ws') &&
            !url.startsWith('/legacy') &&
            !url.startsWith('/websockify') &&
            !url.includes('.') &&
            !url.startsWith('/node_modules')
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
      input: {
        app: resolve(__dirname, 'app.html'),
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
      '/ws': { target: process.env.VITE_WS_URL || 'ws://localhost:8000', ws: true },
      '/vnc.html': { target: process.env.VITE_VNC_URL || 'http://localhost:6080', ws: false },
      '/vnc': { target: process.env.VITE_VNC_URL || 'http://localhost:6080', ws: true },
      '/websockify': { target: process.env.VITE_VNC_URL || 'http://localhost:6080', ws: true },
      '/meetings': process.env.VITE_BACKEND_URL || 'http://localhost:8000',
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
    },
  },
});
