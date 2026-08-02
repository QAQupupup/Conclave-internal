import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/inter/400.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import App from './App';
import './app.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
