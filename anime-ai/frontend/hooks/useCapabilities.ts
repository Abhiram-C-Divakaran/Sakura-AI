import { useState, useEffect, useCallback } from 'react';
import { authFetch } from '../lib/auth';

export interface ProviderHealth {
  name: string;
  configured: boolean;
  healthy: boolean;
  status: 'operational' | 'degraded' | 'unavailable';
}

export interface SystemCapabilities {
  status: 'OPERATIONAL' | 'DEGRADED' | 'NOT_READY';
  version: string;
  environment: string;
  providers: Record<string, ProviderHealth>;
  tools: {
    coding: boolean;
    sandbox: boolean;
    rag: boolean;
    web_search: boolean;
    image_gen: boolean;
  };
  image_features: {
    image_conditioned_edit: boolean;
    true_upscale: boolean;
    available_styles: string[];
  };
}

export function useCapabilities() {
  const [capabilities, setCapabilities] = useState<SystemCapabilities | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCapabilities = useCallback(async () => {
    try {
      setLoading(true);
      const res = await authFetch('/api/v1/capabilities');
      if (res.ok) {
        const data = await res.json();
        setCapabilities(data);
        setError(null);
      } else {
        setError(`Failed to fetch capabilities (HTTP ${res.status})`);
      }
    } catch (err: any) {
      setError(err.message || 'Error connecting to capabilities API');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCapabilities();
  }, [fetchCapabilities]);

  return {
    capabilities,
    loading,
    error,
    refresh: fetchCapabilities,
    isOperational: capabilities?.status === 'OPERATIONAL'
  };
}
