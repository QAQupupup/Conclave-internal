import * as React from 'react';
import type { ToastProps } from '@/components/ui/toast';

type ToasterToast = ToastProps & {
  id: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
};

const TOAST_LIMIT = 5;
const TOAST_REMOVE_DELAY = 5000;

type State = { toasts: ToasterToast[] };

const listeners: Array<(state: State) => void> = [];
let memoryState: State = { toasts: [] };

function dispatch(action: { type: 'ADD'; toast: ToasterToast } | { type: 'REMOVE'; toastId: string }) {
  switch (action.type) {
    case 'ADD':
      memoryState = { toasts: [action.toast, ...memoryState.toasts].slice(0, TOAST_LIMIT) };
      break;
    case 'REMOVE':
      memoryState = { toasts: memoryState.toasts.filter((t) => t.id !== action.toastId) };
      break;
  }
  listeners.forEach((l) => l(memoryState));
}

let count = 0;
function genId() {
  count = (count + 1) % Number.MAX_SAFE_INTEGER;
  return `toast-${count}`;
}

type ToastInput = Omit<ToasterToast, 'id'>;

export function toast(props: ToastInput) {
  const id = genId();
  const dismiss = () => dispatch({ type: 'REMOVE', toastId: id });
  dispatch({
    type: 'ADD',
    toast: {
      ...props,
      id,
      open: true,
      duration: props.duration ?? TOAST_REMOVE_DELAY,
      onOpenChange: (open) => {
        if (!open) setTimeout(() => dispatch({ type: 'REMOVE', toastId: id }), 100);
      },
    },
  });
  return { id, dismiss };
}

export function useToast() {
  const [state, setState] = React.useState<State>(memoryState);
  React.useEffect(() => {
    listeners.push(setState);
    return () => {
      const idx = listeners.indexOf(setState);
      if (idx > -1) listeners.splice(idx, 1);
    };
  }, []);

  return {
    ...state,
    toast,
    dismiss: (toastId?: string) => {
      if (toastId) {
        dispatch({ type: 'REMOVE', toastId });
      } else {
        memoryState.toasts.forEach((t) => dispatch({ type: 'REMOVE', toastId: t.id }));
      }
    },
  };
}