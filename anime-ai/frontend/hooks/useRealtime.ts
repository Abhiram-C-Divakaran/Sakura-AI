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

const MAX_RECONNECT_ATTEMPTS = 8;

export function useRealtime(options: UseRealtimeOptions = {}) {
  const [status, setStatus] = useState<RealtimeStatus>('OFFLINE');
  const [lastHeartbeat, setLastHeartbeat] = useState<Date | null>(null);
  const [degradedReason, setDegradedReason] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const isMountedRef = useRef(true);
  const isConnectingRef = useRef(false);
  const hadSocketErrorRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const updateStatus = useCallback((newStatus: RealtimeStatus) => {
    if (!isMountedRef.current) return;
    setStatus(newStatus);
    optionsRef.current.onStatusChange?.(newStatus);
  }, []);

  const connectRef = useRef<() => Promise<void>>(async () => {});

  const scheduleReconnect = useCallback(() => {
    if (!isMountedRef.current) return;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    const attempt = attemptRef.current;
    if (attempt >= MAX_RECONNECT_ATTEMPTS) {
      updateStatus('DEGRADED');
      setDegradedReason('Realtime updates temporarily unavailable. Standard HTTP features continue normally.');
      return;
    }

    attemptRef.current += 1;
    // Bounded exponential backoff: 1s, 2s, 4s, 8s, 16s, capped at 30s with jitter
    const baseDelay = Math.min(1000 * Math.pow(2, attempt), 30000);
    const jitter = Math.floor(Math.random() * 1000);
    const delay = Math.min(baseDelay + jitter, 30000);

    reconnectTimeoutRef.current = setTimeout(() => {
      if (isMountedRef.current) {
        connectRef.current();
      }
    }, delay);
  }, [updateStatus]);

  const connect = useCallback(async () => {
    if (typeof window === 'undefined' || !isMountedRef.current) return;
    if (isConnectingRef.current) return;

    const token = getAccessToken();
    if (!token) {
      updateStatus('OFFLINE');
      return;
    }

    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    isConnectingRef.current = true;
    hadSocketErrorRef.current = false;
    updateStatus(attemptRef.current === 0 ? 'CONNECTING' : 'RECONNECTING');

    // Ticket-only WebSocket authentication: NEVER place access JWT in WebSocket URL
    let ticket: string | null = null;
    try {
      const ticketRes = await fetch(apiUrl('/api/v1/auth/ws-ticket'), {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (ticketRes.status === 401) {
        isConnectingRef.current = false;
        setDegradedReason('Session authentication required for realtime updates.');
        updateStatus('OFFLINE');
        return;
      }

      if (ticketRes.ok) {
        const ticketData = await ticketRes.json();
        if (ticketData && typeof ticketData.ticket === 'string' && ticketData.ticket.startsWith('wst_')) {
          ticket = ticketData.ticket;
        }
      }
    } catch {
      ticket = null;
    }

    if (!isMountedRef.current) {
      isConnectingRef.current = false;
      return;
    }

    if (!ticket) {
      isConnectingRef.current = false;
      setDegradedReason('Could not obtain WebSocket ticket; realtime updates degraded while HTTP remains available.');
      updateStatus('DEGRADED');
      if (document.visibilityState !== 'hidden') {
        scheduleReconnect();
      }
      return;
    }

    const wsUrl = websocketUrl(`/api/v1/ws?ticket=${encodeURIComponent(ticket)}`);

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      let pingInterval: ReturnType<typeof setInterval> | null = null;

      ws.onopen = () => {
        isConnectingRef.current = false;
        if (!isMountedRef.current) {
          ws.close();
          return;
        }
        attemptRef.current = 0;
        hadSocketErrorRef.current = false;
        setDegradedReason(null);
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

      ws.onerror = () => {
        isConnectingRef.current = false;
        hadSocketErrorRef.current = true;
        if (!isMountedRef.current) return;
        setDegradedReason('Realtime connection interrupted.');
        updateStatus('DEGRADED');
      };

      ws.onclose = () => {
        isConnectingRef.current = false;
        if (pingInterval) {
          clearInterval(pingInterval);
          pingInterval = null;
        }
        if (!isMountedRef.current) return;
        updateStatus(hadSocketErrorRef.current ? 'DEGRADED' : 'OFFLINE');
        if (document.visibilityState !== 'hidden') {
          scheduleReconnect();
        }
      };
    } catch {
      isConnectingRef.current = false;
      if (!isMountedRef.current) return;
      setDegradedReason('Realtime socket initialization failed.');
      updateStatus('DEGRADED');
      scheduleReconnect();
    }
  }, [updateStatus, scheduleReconnect]);

  connectRef.current = connect;

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
    degradedReason,
    lastHeartbeat,
    reconnect: () => {
      attemptRef.current = 0;
      setDegradedReason(null);
      connect();
    },
  };
}
