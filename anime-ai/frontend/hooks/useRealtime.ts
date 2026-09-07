import { useState, useEffect, useRef, useCallback } from 'react';
import { getAccessToken } from '../lib/auth';

export type RealtimeStatus = 'LIVE' | 'CONNECTING' | 'RECONNECTING' | 'DEGRADED' | 'OFFLINE';

export interface RealtimeMessage {
  type: string;
  data?: any;
  id?: string;
  timestamp?: number;
}

export interface UseRealtimeOptions {
  onMessage?: (msg: RealtimeMessage) => void;
  onStatusChange?: (status: RealtimeStatus) => void;
}

export function useRealtime(options: UseRealtimeOptions = {}) {
  const [status, setStatus] = useState<RealtimeStatus>('OFFLINE');
  const [lastHeartbeat, setLastHeartbeat] = useState<Date | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<any>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const updateStatus = useCallback((newStatus: RealtimeStatus) => {
    setStatus(newStatus);
    optionsRef.current.onStatusChange?.(newStatus);
  }, []);

  const connect = useCallback(() => {
    if (typeof window === 'undefined') return;
    const token = getAccessToken();
    if (!token) {
      updateStatus('OFFLINE');
      return;
    }

    setStatus(prev => {
      const next: RealtimeStatus = prev === 'OFFLINE' ? 'CONNECTING' : 'RECONNECTING';
      optionsRef.current.onStatusChange?.(next);
      return next;
    });

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/ws?token=${token}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      let pingInterval: any;

      ws.onopen = () => {
        updateStatus('LIVE');
        setLastHeartbeat(new Date());
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
          }
        }, 10000);
      };

      ws.onmessage = (event) => {
        setLastHeartbeat(new Date());
        if (event.data === 'pong') return;
        try {
          const msg = JSON.parse(event.data);
          optionsRef.current.onMessage?.(msg);
        } catch (err) {
          console.error('[WebSocket] JSON parse error:', err);
        }
      };

      ws.onclose = () => {
        updateStatus('OFFLINE');
        clearInterval(pingInterval);
        if (document.visibilityState !== 'hidden') {
          reconnectTimeoutRef.current = setTimeout(connect, 4000);
        }
      };

      ws.onerror = () => {
        updateStatus('DEGRADED');
      };
    } catch (e) {
      updateStatus('OFFLINE');
      reconnectTimeoutRef.current = setTimeout(connect, 5000);
    }
  }, [updateStatus]);

  useEffect(() => {
    connect();

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        if (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED) {
          connect();
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, [connect]);

  return {
    status,
    lastHeartbeat,
    reconnect: connect
  };
}
