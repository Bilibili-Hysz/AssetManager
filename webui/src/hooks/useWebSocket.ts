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
  const onEventRef = useRef(onEvent);

  onEventRef.current = onEvent;

  useEffect(() => {
    let active = enabled;
    let retryCount = 0;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (!active) return;

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
      wsRef.current = ws;
      setStatus('connecting');

      ws.onopen = () => {
        if (!active || wsRef.current !== ws) return;
        setStatus('connected');
        retryCount = 0;
      };

      ws.onmessage = (event: MessageEvent) => {
        if (!active || wsRef.current !== ws) return;
        try {
          const data = JSON.parse(event.data) as { type: string };
          onEventRef.current?.(data.type, data as Record<string, unknown>);
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (!active || wsRef.current !== ws) return;
        setStatus('disconnected');
        wsRef.current = null;
        const delay = Math.min(1000 * Math.pow(2, retryCount), 30000);
        retryCount++;
        retryTimer = setTimeout(connect, delay);
      };

      ws.onerror = () => ws.close();
    };

    if (enabled) connect();
    else setStatus('disconnected');

    return () => {
      active = false;
      if (retryTimer) clearTimeout(retryTimer);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [enabled]);

  return { status };
}
