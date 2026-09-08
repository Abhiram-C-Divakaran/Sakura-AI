/**
 * Sakura AI — Centralized Authentication & Token Management Client
 *
 * Consistently manages access token storage under 'access_token' and provides
 * authenticated fetch with automated Bearer headers and 401 session expiration handling.
 */

import { apiUrl } from './api';

const TOKEN_KEY = 'access_token';

export function getAccessToken(): string {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setAccessToken(token: string): void {
  if (typeof window === 'undefined') return;
  if (!token) {
    localStorage.removeItem(TOKEN_KEY);
  } else {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

export function clearAccessToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
  // Remove any legacy keys if present
  localStorage.removeItem('token');
}

export function isAuthenticated(): boolean {
  return Boolean(getAccessToken());
}

export interface AuthFetchOptions extends RequestInit {
  skipAuthRedirect?: boolean;
}

/**
 * Standardized fetch wrapper that injects Authorization Bearer header
 * and redirects to login on 401 Unauthorized responses.
 * All URLs are normalized through canonical apiUrl().
 */
export async function authFetch(
  url: string,
  options: AuthFetchOptions = {}
): Promise<Response> {
  const token = getAccessToken();
  const headers = new Headers(options.headers || {});

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const targetUrl = apiUrl(url);
  const response = await fetch(targetUrl, {
    ...options,
    headers
  });

  if (response.status === 401 && !options.skipAuthRedirect && typeof window !== 'undefined') {
    clearAccessToken();
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = '/login';
    }
  }

  return response;
}
