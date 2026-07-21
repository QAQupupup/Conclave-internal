/* Toast 通知系统 — 轻量、自动消失，风格统一于 Gen Speak 极简设计 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

export type ToastKind = 'success' | 'error' | 'warning' | 'info';
interface ToastItem { id: number; kind: ToastKind; msg: string; duration: number }
interface ToastApi { show: (msg: string, kind?: ToastKind, duration?: number) => void }

const Ctx = createContext<ToastApi | null>(null);
export function useToast(): ToastApi {
  const v = useContext(Ctx);
  if (!v) throw new Error('useToast must be used within ToastProvider');
  return v;
}

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const show = useCallback((msg: string, kind: ToastKind = 'info', duration = 4000) => {
    const id = nextId++;
    setItems((prev) => [...prev, { id, kind, msg, duration }]);
  }, []);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <Ctx.Provider value={{ show }}>
      {children}
      <div className="toast-container" role="region" aria-live="polite">
        {items.map((t) => (
          <ToastCard key={t.id} item={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </Ctx.Provider>
  );
}

function ToastCard({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, item.duration);
    return () => clearTimeout(timer);
  }, [item.duration, onDismiss]);
  return (
    <div className={`toast toast-${item.kind}`} role="alert">
      <span className="toast-icon">{item.kind === 'success' ? '✓' : item.kind === 'error' ? '✕' : item.kind === 'warning' ? '!' : 'i'}</span>
      <span className="toast-msg">{item.msg}</span>
      <button className="toast-close" onClick={onDismiss} aria-label="关闭">×</button>
    </div>
  );
}
