import { useState, useEffect, useRef, useCallback } from 'react';
import { getAccessToken } from '../lib/auth';
import { websocketUrl, apiUrl } from '../lib/api';

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
  const attemptRef = useRef(0);
  const isMountedRef = useRef(true);
  const isConnectingRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const updateStatus = useCallback((newStatus: RealtimeStatus) => {
    if (!isMountedRef.current) return;
    setStatus(newStatus);
    optionsRef.current.onStatusChange?.(newStatus);
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (!isMountedRef.current) return;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    const attempt = attemptRef.current;
    attemptRef.current += 1;
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s... capped at 30s with random jitter
    const baseDelay = Math.min(1000 * Math.pow(2, attempt), 30000);
    const jitter = Math.floor(Math.random() * 1000);
    const delay = Math.min(baseDelay + jitter, 30000);

    reconnectTimeoutRef.current = setTimeout(() => {
      if (isMountedRef.current) {
        connect();
      }
    }, delay);
  }, []);

  const connect = useCallback(async () => {
    if (typeof window === 'undefined' || !isMountedRef.current) return;
    if (isConnectingRef.current) return;

    const token = getAccessToken();
    if (!token) {
      updateStatus('OFFLINE');
      return;
    }

    // Don't reconnect if existing socket is OPEN or CONNECTING
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    isConnectingRef.current = true;
    updateStatus(attemptRef.current === 0 ? 'CONNECTING' : 'RECONNECTING');

    // 1. Fetch single-use ticket from backend
    let ticket: string | null = null;
    try {
      const ticketRes = await fetch(apiUrl('/api/v1/auth/ws-ticket'), {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      if (ticketRes.ok) {
        const ticketData = await ticketRes.json();
        ticket = ticketData.ticket;
      }
    } catch {
      // If ticket endpoint fails, will fall back to token query param
    }

    if (!isMountedRef.current) {
      isConnectingRef.current = false;
      return;
    }

    const queryParam = ticket
      ? `ticket=${encodeURIComponent(ticket)}`
      : `token=${encodeURIComponent(token)}`;
    const wsUrl = websocketUrl(`/api/v1/ws?${queryParam}`);

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      let pingInterval: any;

      ws.onopen = () => {
        isConnectingRef.current = false;
        if (!isMountedRef.current) {
          ws.close();
          return;
        }
        attemptRef.current = 0;
        updateStatus('LIVE');
        setLastHeartbeat(new Date());

        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
          }
        }, 10000);
      };

      ws.onmessage = (event) => {
        if (!isMountedRef.current) return;
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
        isConnectingRef.current = false;
        clearInterval(pingInterval);
        if (!isMountedRef.current) return;
        updateStatus('OFFLINE');
        if (document.visibilityState !== 'hidden') {
          scheduleReconnect();
        }
      };

      ws.onerror = () => {
        isConnectingRef.current = false;
        if (!isMountedRef.current) return;
        updateStatus('DEGRADED');
      };
    } catch (e) {
      isConnectingRef.current = false;
      if (!isMountedRef.current) return;
      updateStatus('OFFLINE');
      scheduleReconnect();
    }
  }, [updateStatus, scheduleReconnect]);

  useEffect(() => {
    isMountedRef.current = true;
    connect();

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && isMountedRef.current) {
        if (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED) {
          attemptRef.current = 0;
          connect();
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      isMountedRef.current = false;
      isConnectingRef.current = false;
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };
  }, [connect]);

  return {
    status,
    lastHeartbeat,
    reconnect: () => {
      attemptRef.current = 0;
      connect();
    }
  };
}
