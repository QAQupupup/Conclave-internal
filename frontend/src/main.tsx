import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/global.css';

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('#root not found');

// 启动时恢复主题偏好
try {
  const t = localStorage.getItem('conclave_theme');
  if (t) document.documentElement.setAttribute('data-theme', t);
} catch { /* ignore */ }

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
