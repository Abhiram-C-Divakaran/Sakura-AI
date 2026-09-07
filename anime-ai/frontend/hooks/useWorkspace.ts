import { useState, useEffect, useCallback } from 'react';
import { authFetch } from '../lib/auth';

export interface Workspace {
  id: string;
  name: string;
  repository_url?: string;
  branch?: string;
  status: 'READY' | 'CLONING' | 'ERROR';
  created_at?: string;
  last_commit?: string;
}

export function useWorkspace() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const activeWorkspace = workspaces.find(w => w.id === activeWorkspaceId) || null;

  const fetchWorkspaces = useCallback(async () => {
    try {
      setLoading(true);
      const res = await authFetch('/api/v1/workspaces');
      if (res.ok) {
        const data = await res.json();
        setWorkspaces(data);
        if (data.length > 0 && !activeWorkspaceId) {
          setActiveWorkspaceId(data[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to fetch workspaces:', err);
    } finally {
      setLoading(false);
    }
  }, [activeWorkspaceId]);

  const selectWorkspace = useCallback((id: string) => {
    setActiveWorkspaceId(id);
  }, []);

  const createWorkspace = useCallback(async (name: string, repositoryUrl?: string, branch: string = 'main') => {
    try {
      const res = await authFetch('/api/v1/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          repository_url: repositoryUrl,
          branch,
          clone_existing: Boolean(repositoryUrl)
        })
      });
      if (res.ok) {
        const created = await res.json();
        setWorkspaces(prev => [created, ...prev]);
        setActiveWorkspaceId(created.id);
        return created;
      }
    } catch (err) {
      console.error('Failed to create workspace:', err);
    }
    return null;
  }, []);

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  return {
    workspaces,
    activeWorkspaceId,
    activeWorkspace,
    loading,
    fetchWorkspaces,
    selectWorkspace,
    createWorkspace
  };
}
