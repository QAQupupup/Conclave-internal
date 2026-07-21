/* ConfirmModal — 替换浏览器原生 confirm()/alert()，风格统一于 Gen Speak 极简设计 */
import { useEffect } from 'react';

export interface ConfirmModalProps {
  open: boolean;
  title: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmModal({
  open, title, message, confirmText = '确认', cancelText = '取消', danger,
  onConfirm, onCancel,
}: ConfirmModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
      if (e.key === 'Enter') onConfirm();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onConfirm, onCancel]);

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onCancel} role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title" id="confirm-title">{title}</h3>
        {message && <p className="modal-msg">{message}</p>}
        <div className="modal-actions">
          <button className="ctrl-btn" onClick={onCancel}>{cancelText}</button>
          <button className={`ctrl-btn ${danger ? 'danger' : 'primary'}`} onClick={onConfirm} autoFocus>{confirmText}</button>
        </div>
      </div>
    </div>
  );
}

/* AlertModal — 单按钮提示（替换 alert()） */
export interface AlertModalProps {
  open: boolean;
  title: string;
  message?: string;
  buttonText?: string;
  onClose: () => void;
}

export function AlertModal({ open, title, message, buttonText = '知道了', onClose }: AlertModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' || e.key === 'Enter') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title">{title}</h3>
        {message && <p className="modal-msg">{message}</p>}
        <div className="modal-actions">
          <button className="ctrl-btn primary" onClick={onClose} autoFocus>{buttonText}</button>
        </div>
      </div>
    </div>
  );
}
