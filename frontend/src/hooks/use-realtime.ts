import { useEffect, useRef, useCallback } from 'react';
import { wsClient } from '@/lib/ws';

export function useEventSource(meetingId: string | null | undefined) {
  useEffect(() => {
    if (!meetingId) return;
    wsClient.connect(meetingId);
    return () => {
      wsClient.disconnect();
    };
  }, [meetingId]);
}

export function useMeetingEvent(eventType: string, handler: (msg: Record<string, unknown>) => void) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const unsub = wsClient.on('message', (msg: unknown) => {
      if (typeof msg === 'object' && msg !== null && (msg as Record<string, unknown>).type === eventType) {
        handlerRef.current(msg as Record<string, unknown>);
      }
    });
    return () => unsub();
  }, [eventType]);
}

export function useDebouncedCallback<T extends (...args: unknown[]) => void>(
  callback: T,
  delay: number
): T {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  return useCallback(
    ((...args: unknown[]) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => callbackRef.current(...args), delay);
    }) as T,
    [delay]
  );
}

export function useThrottledCallback<T extends (...args: unknown[]) => void>(
  callback: T,
  limit: number
): T {
  const inThrottleRef = useRef(false);
  const lastArgsRef = useRef<unknown[] | null>(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  return useCallback(
    ((...args: unknown[]) => {
      if (!inThrottleRef.current) {
        callbackRef.current(...args);
        inThrottleRef.current = true;
        setTimeout(() => {
          inThrottleRef.current = false;
          if (lastArgsRef.current) {
            callbackRef.current(...lastArgsRef.current);
            lastArgsRef.current = null;
          }
        }, limit);
      } else {
        lastArgsRef.current = args;
      }
    }) as T,
    [limit]
  );
}