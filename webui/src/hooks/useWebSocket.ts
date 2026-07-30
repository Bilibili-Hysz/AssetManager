import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected';

interface UseWebSocketOptions {
  onEvent?: (type: string, data: Record<string, unknown>) => void;
  enabled?: boolean;
}

interface UseWebSocketReturn {
  status: WebSocketStatus;
}

type TransportBridge = {
  status: WebSocketStatus;
  subscribe: (onEvent?: (type: string, data: Record<string, unknown>) => void) => () => void;
};

const WebSocketTransportContext = createContext<TransportBridge | null>(null);

export function useWebSocket({ onEvent, enabled = true }: UseWebSocketOptions): UseWebSocketReturn {
  const bridge = useContext(WebSocketTransportContext);
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (bridge) return bridge.subscribe((type, data) => onEventRef.current?.(type, data));
    let disposed = false;
    const clearRetry = () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = null;
    };
    const scheduleReconnect = () => {
      if (disposed || !enabled || timerRef.current !== null) return;
      const delay = Math.min(1000 * 2 ** retryRef.current, 30000);
      retryRef.current += 1;
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        connect();
      }, delay);
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
        if (!disposed && wsRef.current === ws) {
          retryRef.current = 0;
          setStatus('connected');
        }
      };
      ws.onmessage = event => {
        if (disposed || wsRef.current !== ws) return;
        try {
          const data = JSON.parse(event.data) as { type: string };
          onEventRef.current?.(data.type, data as Record<string, unknown>);
        } catch { /* ignore malformed messages */ }
      };
      ws.onclose = () => {
        if (wsRef.current !== ws || disposed || !enabled) return;
        wsRef.current = null;
        setStatus('disconnected');
        scheduleReconnect();
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      disposed = true;
      clearRetry();
      retryRef.current = 0;
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close();
    };
  }, [bridge, enabled]);

  return { status: bridge?.status ?? status };
}

export function WebSocketTransportHost({
  enabled,
  onEvent,
  children,
  onStatus,
}: {
  enabled: boolean;
  onEvent?: (type: string, data: Record<string, unknown>) => void;
  children: ReactNode;
  onStatus?: (status: WebSocketStatus) => void;
}) {
  const listenersRef = useRef(new Set<(type: string, data: Record<string, unknown>) => void>());
  const eventRef = useRef(onEvent);
  eventRef.current = onEvent;
  const subscribe = (consumer?: (type: string, data: Record<string, unknown>) => void) => {
    if (!consumer) return () => {};
    listenersRef.current.add(consumer);
    return () => listenersRef.current.delete(consumer);
  };
  const fanout = useCallback((type: string, data: Record<string, unknown>) => {
    eventRef.current?.(type, data);
    for (const listener of listenersRef.current) {
      try {
        listener(type, data);
      } catch {
        // One legacy consumer must not block the remaining listeners.
      }
    }
  }, []);
  const transport = useWebSocket({ enabled, onEvent: fanout });
  const bridge = useMemo(() => ({ status: transport.status, subscribe }), [transport.status]);
  useEffect(() => onStatus?.(transport.status), [onStatus, transport.status]);
  return createElement(WebSocketTransportContext.Provider, { value: bridge }, children);
}
