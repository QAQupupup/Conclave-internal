import { useEffect, useRef, useCallback } from 'react';

export function useEventSource(meetingId: string | null | undefined) {
  const wsClientRef = useRef<{ connect: (id: string) => void; disconnect: () => void } | null>(null);

  useEffect(() => {
    if (!meetingId) return;
    let cancelled = false;
    import('@/lib/ws').then(({ wsClient }) => {
      if (cancelled) return;
      wsClientRef.current = wsClient;
      wsClient.connect(meetingId);
    });
    return () => {
      cancelled = true;
      wsClientRef.current?.disconnect();
      wsClientRef.current = null;
    };
  }, [meetingId]);
}

export function useMeetingEvent(eventType: string, handler: (...args: any[]) => void) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    let unsub: (() => void) | undefined;
    import('@/lib/ws').then(({ wsClient }) => {
      unsub = wsClient.on('message' as any, (msg: any) => {
        if (msg.type === eventType) {
          handlerRef.current(msg);
        }
      });
    });
    return () => unsub?.();
  }, [eventType]);
}

export function useDebouncedCallback<T extends (...args: any[]) => void>(
  callback: T,
  delay: number
): T {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  return useCallback(
    ((...args: any[]) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => callbackRef.current(...args), delay);
    }) as T,
    [delay]
  );
}

export function useThrottledCallback<T extends (...args: any[]) => void>(
  callback: T,
  limit: number
): T {
  const inThrottleRef = useRef(false);
  const lastArgsRef = useRef<any[] | null>(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  return useCallback(
    ((...args: any[]) => {
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
