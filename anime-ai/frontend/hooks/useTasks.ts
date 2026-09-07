import { useState, useEffect, useCallback } from 'react';
import { authFetch } from '../lib/auth';

export interface BackgroundTask {
  id: string;
  type: string;
  title: string;
  status: 'Queued' | 'Starting' | 'Running' | 'Completed' | 'Failed' | 'Cancelled' | 'Waiting';
  progress: number;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
  payload?: any;
}

export function useTasks() {
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [loading, setLoading] = useState<boolean>(false);

  const fetchTasks = useCallback(async () => {
    try {
      setLoading(true);
      const res = await authFetch('/api/v1/tasks');
      if (res.ok) {
        const data = await res.json();
        setTasks(data);
      }
    } catch (err) {
      console.error('Failed to fetch tasks:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const createTask = useCallback(async (title: string, type: string, payload: any = {}) => {
    try {
      const res = await authFetch('/api/v1/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, type, payload })
      });
      if (res.ok) {
        const newTask = await res.json();
        setTasks(prev => [newTask, ...prev]);
        return newTask;
      }
    } catch (err) {
      console.error('Failed to create task:', err);
    }
    return null;
  }, []);

  const cancelTask = useCallback(async (taskId: string) => {
    try {
      const res = await authFetch(`/api/v1/tasks/${taskId}/cancel`, { method: 'POST' });
      if (res.ok) {
        const updated = await res.json();
        setTasks(prev => prev.map(t => (t.id === taskId ? updated : t)));
      }
    } catch (err) {
      console.error('Failed to cancel task:', err);
    }
  }, []);

  const retryTask = useCallback(async (taskId: string) => {
    try {
      const res = await authFetch(`/api/v1/tasks/${taskId}/retry`, { method: 'POST' });
      if (res.ok) {
        const updated = await res.json();
        setTasks(prev => prev.map(t => (t.id === taskId ? updated : t)));
      }
    } catch (err) {
      console.error('Failed to retry task:', err);
    }
  }, []);

  const clearCompleted = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/tasks/clear_completed', { method: 'DELETE' });
      if (res.ok) {
        setTasks(prev => prev.filter(t => ['Queued', 'Starting', 'Running', 'Waiting'].includes(t.status)));
      }
    } catch (err) {
      console.error('Failed to clear completed tasks:', err);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  return {
    tasks,
    loading,
    fetchTasks,
    createTask,
    cancelTask,
    retryTask,
    clearCompleted,
    setTasks
  };
}
