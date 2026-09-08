/**
 * Sakura AI — Centralized Frontend API & WebSocket Client Utilities
 *
 * Exposes canonical API base resolution and URL builders for HTTP and WebSockets,
 * ensuring uniform routing across development, Docker Compose, and split-port production.
 */

export const API_BASE = (
  (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_URL) ||
  'http://localhost:8000'
).replace(/\/+$/, '');

/**
 * Builds a canonical HTTP API URL from a relative or absolute path.
 */
export function apiUrl(path: string): string {
  if (!path) return API_BASE;
  if (/^https?:\/\//i.test(path)) return path;
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE}${cleanPath}`;
}

/**
 * Builds a canonical WebSocket URL from a relative or absolute path,
 * deriving from NEXT_PUBLIC_WS_URL, API_BASE, or window.location.
 */
export function websocketUrl(path: string): string {
  if (!path) return '';
  if (/^wss?:\/\//i.test(path)) return path;
  const cleanPath = path.startsWith('/') ? path : `/${path}`;

  // 1. Explicit WS URL override
  if (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_WS_URL) {
    const wsBase = process.env.NEXT_PUBLIC_WS_URL.replace(/\/+$/, '');
    return `${wsBase}${cleanPath}`;
  }

  // 2. Derive protocol and host from API_BASE
  if (/^https:\/\//i.test(API_BASE)) {
    return `${API_BASE.replace(/^https:/i, 'wss:')}${cleanPath}`;
  }
  if (/^http:\/\//i.test(API_BASE)) {
    return `${API_BASE.replace(/^http:/i, 'ws:')}${cleanPath}`;
  }

  // 3. Fallback to browser location
  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}${cleanPath}`;
  }

  return `ws://localhost:8000${cleanPath}`;
}
