import { useEffect, useRef, useState } from 'react';

type WebSocketStatus = 'connecting' | 'connected' | 'disconnected';

interface UseWebSocketOptions {
  onEvent?: (type: string, data: Record<string, unknown>) => void;
  enabled?: boolean;
}

interface UseWebSocketReturn {
  status: WebSocketStatus;
}

export function useWebSocket({ onEvent, enabled = true }: UseWebSocketOptions): UseWebSocketReturn {
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    let disposed = false;
    const clearRetry = () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = null;
    };
    const connect = () => {
      clearRetry();
      if (disposed || !enabled) {
        setStatus('disconnected');
        return;
      }
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      setStatus('connecting');
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
      wsRef.current = ws;
      ws.onopen = () => {
        if (!disposed) {
          setStatus('connected');
          retryRef.current = 0;
        }
      };
      ws.onmessage = event => {
        try {
          const data = JSON.parse(event.data) as { type: string };
          onEventRef.current?.(data.type, data as Record<string, unknown>);
        } catch { /* ignore malformed messages */ }
      };
      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        if (disposed || !enabled) return;
        setStatus('disconnected');
        const delay = Math.min(1000 * 2 ** retryRef.current++, 30000);
        timerRef.current = setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      disposed = true;
      clearRetry();
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close();
    };
  }, [enabled]);

  return { status };
}
