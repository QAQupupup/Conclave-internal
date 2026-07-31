import { create } from 'zustand';
import type { WsConnectionStatus } from '@/types';

interface WSState {
  status: WsConnectionStatus;
  lastSeq: number;
  reconnectCount: number;
  error: string | null;
  setStatus: (status: WsConnectionStatus) => void;
  setLastSeq: (seq: number) => void;
  incReconnectCount: () => void;
  resetReconnectCount: () => void;
  setError: (error: string | null) => void;
}

export const useWSStore = create<WSState>((set) => ({
  status: 'disconnected',
  lastSeq: 0,
  reconnectCount: 0,
  error: null,
  setStatus: (status) => set({ status }),
  setLastSeq: (lastSeq) => set({ lastSeq }),
  incReconnectCount: () => set((s) => ({ reconnectCount: s.reconnectCount + 1 })),
  resetReconnectCount: () => set({ reconnectCount: 0, error: null }),
  setError: (error) => set({ error }),
}));
