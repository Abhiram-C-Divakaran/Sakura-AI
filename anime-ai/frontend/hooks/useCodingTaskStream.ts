import { useState, useCallback, useRef, useEffect } from 'react';
import { authFetch } from '../lib/auth';
import { ToolExecutionProps } from '../components/coding/ToolExecution';
import { VerificationResult } from '../components/coding/VerificationSummary';

export interface CodingTaskEventItem {
  id?: string;
  taskId: string;
  jobId?: string | null;
  sequenceNumber: number;
  phase: string;
  eventType: string;
  toolName?: string | null;
  argumentsSummary?: string | null;
  stdoutPreview?: string | null;
  stderrPreview?: string | null;
  exitCode?: number | null;
  diffMetadata?: any;
  verificationMetadata?: any;
  message?: string | null;
  createdAt?: string | null;
}

export interface CodingTaskState {
  taskId: string;
  jobId?: string | null;
  workspaceId?: string | null;
  workspaceName?: string | null;
  title?: string;
  status: string;
  phase: string;
  lastSequence: number;
  events: CodingTaskEventItem[];
  tools: ToolExecutionProps[];
  diffText?: string;
  filesModified: string[];
  verification?: VerificationResult;
  error?: string | null;
  reconnecting: boolean;
  cancelRequested: boolean;
}

const TERMINAL_STATUSES = new Set([
  'COMPLETED',
  'COMPLETED_VERIFIED',
  'COMPLETED_UNVERIFIED',
  'FAILED',
  'CANCELLED',
  'CANCELED',
  'BLOCKED',
]);

export function isTerminalCodingStatus(status?: string | null): boolean {
  if (!status) return false;
  return TERMINAL_STATUSES.has(status.trim().toUpperCase());
}

/**
 * Deduplicates coding task events strictly by sequenceNumber and sorts ascending.
 */
export function mergeCodingEvents(
  existing: CodingTaskEventItem[],
  incoming: CodingTaskEventItem[]
): CodingTaskEventItem[] {
  const bySeq = new Map<number, CodingTaskEventItem>();
  for (const evt of existing) {
    if (typeof evt.sequenceNumber === 'number') {
      bySeq.set(evt.sequenceNumber, evt);
    }
  }
  for (const evt of incoming) {
    if (typeof evt.sequenceNumber === 'number') {
      bySeq.set(evt.sequenceNumber, evt);
    }
  }
  return Array.from(bySeq.values()).sort((a, b) => a.sequenceNumber - b.sequenceNumber);
}

/**
 * Converts persisted CodingTaskEventItem rows into CodingActivity tool execution rows.
 */
export function mapEventsToTools(events: CodingTaskEventItem[]): ToolExecutionProps[] {
  const tools: ToolExecutionProps[] = [];
  for (const evt of events) {
    if (!evt.toolName && evt.eventType !== 'tool_start' && evt.eventType !== 'tool_result') {
      continue;
    }
    const name = evt.toolName || evt.phase || 'tool';
    if (evt.eventType === 'tool_start') {
      tools.push({
        toolName: name,
        status: 'running',
        command: evt.argumentsSummary || undefined,
      });
    } else if (evt.eventType === 'tool_result') {
      const ok = evt.exitCode === null || evt.exitCode === undefined || evt.exitCode === 0;
      const existingIdx = [...tools]
        .reverse()
        .findIndex((t) => t.toolName === name && t.status === 'running');
      const stdout = evt.stdoutPreview || (!evt.stderrPreview ? evt.message || undefined : undefined);
      const stderr = evt.stderrPreview || undefined;
      const exitCode = typeof evt.exitCode === 'number' ? evt.exitCode : ok ? 0 : 1;
      if (existingIdx >= 0) {
        const realIdx = tools.length - 1 - existingIdx;
        tools[realIdx] = {
          ...tools[realIdx],
          status: ok ? 'success' : 'error',
          stdout,
          stderr,
          exitCode,
        };
      } else {
        tools.push({
          toolName: name,
          status: ok ? 'success' : 'error',
          command: evt.argumentsSummary || undefined,
          stdout,
          stderr,
          exitCode,
        });
      }
    }
  }
  return tools;
}

export function extractVerificationResult(
  statusPayload?: any,
  events: CodingTaskEventItem[] = []
): VerificationResult | undefined {
  const vs = statusPayload?.verificationState;
  if (vs && typeof vs === 'object' && Object.keys(vs).length > 0) {
    const passed = Boolean(
      vs.passed ??
      vs.verified ??
      (String(statusPayload?.status || '').toUpperCase() === 'COMPLETED_VERIFIED')
    );
    return {
      passed,
      totalTests: typeof vs.total_tests === 'number' ? vs.total_tests : vs.totalTests,
      passedTests: typeof vs.passed_tests === 'number' ? vs.passed_tests : vs.passedTests,
      failedTests: typeof vs.failed_tests === 'number' ? vs.failed_tests : vs.failedTests,
      durationMs: typeof vs.duration_ms === 'number' ? vs.duration_ms : vs.durationMs,
      command: vs.command,
      summary: vs.summary || vs.message,
    };
  }
  for (let i = events.length - 1; i >= 0; i--) {
    const vm = events[i].verificationMetadata;
    if (vm && typeof vm === 'object') {
      return {
        passed: Boolean(vm.passed ?? vm.verified),
        summary: vm.summary || events[i].message || undefined,
      };
    }
  }
  return undefined;
}

export function mapCodingStatusToActivity(
  status: string
): 'queued' | 'executing' | 'completed' | 'failed' | 'cancelled' {
  const upper = (status || '').trim().toUpperCase();
  if (upper === 'QUEUED') return 'queued';
  if (upper === 'CANCELLED' || upper === 'CANCELED' || upper === 'CANCELLING') return 'cancelled';
  if (upper === 'FAILED' || upper === 'BLOCKED') return 'failed';
  if (upper.startsWith('COMPLETED')) return 'completed';
  return 'executing';
}

export interface AttachCodingTaskOptions {
  taskId: string;
  jobId?: string | null;
  workspaceId?: string | null;
  workspaceName?: string | null;
  eventsStreamUrl?: string | null;
}

export function useCodingTaskStream() {
  const [codingTasks, setCodingTasks] = useState<Record<string, CodingTaskState>>({});
  const [activeCodingTaskId, setActiveCodingTaskId] = useState<string | null>(null);

  const controllersRef = useRef<Map<string, AbortController>>(new Map());
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const mountedRef = useRef<boolean>(true);
  const lastSeqRef = useRef<Map<string, number>>(new Map());

  const detachAll = useCallback(() => {
    controllersRef.current.forEach((ctrl) => ctrl.abort());
    controllersRef.current.clear();
    timersRef.current.forEach((timer) => clearTimeout(timer));
    timersRef.current.clear();
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      detachAll();
    };
  }, [detachAll]);

  const fetchFinalDiff = useCallback(async (taskId: string, workspaceId?: string | null) => {
    if (!workspaceId) return;
    try {
      const diffRes = await authFetch(`/api/v1/coding/workspaces/${workspaceId}/diff`);
      if (diffRes.ok && mountedRef.current) {
        const diffData = await diffRes.json();
        setCodingTasks((prev) => {
          const cur = prev[taskId];
          if (!cur) return prev;
          return {
            ...prev,
            [taskId]: {
              ...cur,
              diffText: diffData.diff || cur.diffText,
            },
          };
        });
      }
    } catch {
      // Diff fetch is best-effort after task completion
    }
  }, []);

  const refreshTaskStatus = useCallback(
    async (taskId: string) => {
      const statusRes = await authFetch(`/api/v1/coding/tasks/${taskId}`);
      if (!statusRes.ok) return null;
      const statusData = await statusRes.json();
      if (!mountedRef.current) return statusData;

      const resolvedWsId = statusData.workspaceId || statusData.workspace_id || null;
      const resolvedStatus = statusData.status || 'QUEUED';
      setCodingTasks((prev) => {
        const cur: CodingTaskState = prev[taskId] || {
          taskId,
          status: resolvedStatus,
          phase: resolvedStatus,
          lastSequence: 0,
          events: [],
          tools: [],
          filesModified: [],
          reconnecting: false,
          cancelRequested: false,
        };
        const verification = extractVerificationResult(statusData, cur.events);
        return {
          ...prev,
          [taskId]: {
            ...cur,
            jobId: statusData.id || cur.jobId,
            workspaceId: resolvedWsId || cur.workspaceId,
            title: statusData.title || cur.title,
            status: resolvedStatus,
            phase: isTerminalCodingStatus(resolvedStatus) ? resolvedStatus : cur.phase,
            filesModified: Array.isArray(statusData.filesModified) ? statusData.filesModified : cur.filesModified,
            verification: verification || cur.verification,
            error: statusData.error || cur.error,
            cancelRequested: Boolean(statusData.cancelRequested ?? cur.cancelRequested),
            reconnecting: isTerminalCodingStatus(resolvedStatus) ? false : cur.reconnecting,
          },
        };
      });
      if (isTerminalCodingStatus(resolvedStatus) && resolvedWsId) {
        fetchFinalDiff(taskId, resolvedWsId);
      }
      return statusData;
    },
    [fetchFinalDiff]
  );

  const subscribeStream = useCallback(
    async (taskId: string, workspaceId?: string | null, attempt = 0) => {
      if (!mountedRef.current) return;

      // Cancel any existing controller for this task
      const prevCtrl = controllersRef.current.get(taskId);
      if (prevCtrl) prevCtrl.abort();

      const ctrl = new AbortController();
      controllersRef.current.set(taskId, ctrl);

      const afterSeq = lastSeqRef.current.get(taskId) || 0;
      const url = `/api/v1/coding/tasks/${taskId}/events/stream?after_sequence=${afterSeq}`;

      let reachedTerminal = false;
      try {
        const res = await authFetch(url, { signal: ctrl.signal });
        if (!res.ok) {
          throw new Error(`Coding event stream returned HTTP ${res.status}`);
        }
        if (mountedRef.current) {
          setCodingTasks((prev) =>
            prev[taskId] ? { ...prev, [taskId]: { ...prev[taskId], reconnecting: false } } : prev
          );
        }

        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        if (reader) {
          let buffer = '';
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const line of lines) {
              const trimmed = line.trim();
              if (!trimmed.startsWith('data: ')) continue;
              try {
                const evt: CodingTaskEventItem = JSON.parse(trimmed.slice(6));
                if (typeof evt.sequenceNumber === 'number') {
                  const prevMax = lastSeqRef.current.get(taskId) || 0;
                  if (evt.sequenceNumber > prevMax) {
                    lastSeqRef.current.set(taskId, evt.sequenceNumber);
                  }
                }
                if (isTerminalCodingStatus(evt.phase)) {
                  reachedTerminal = true;
                }
                if (mountedRef.current) {
                  setCodingTasks((prev) => {
                    const cur = prev[taskId];
                    if (!cur) return prev;
                    const merged = mergeCodingEvents(cur.events, [evt]);
                    const maxSeq = merged.length > 0 ? merged[merged.length - 1].sequenceNumber : cur.lastSequence;
                    return {
                      ...prev,
                      [taskId]: {
                        ...cur,
                        status: isTerminalCodingStatus(evt.phase) ? evt.phase : (cur.status === 'QUEUED' ? 'RUNNING' : cur.status),
                        phase: evt.phase || cur.phase,
                        lastSequence: maxSeq,
                        events: merged,
                        tools: mapEventsToTools(merged),
                        reconnecting: false,
                      },
                    };
                  });
                }
              } catch {
                // Ignore malformed keepalive frames
              }
            }
          }
        }
      } catch (err: any) {
        if (err?.name === 'AbortError' || !mountedRef.current) {
          return;
        }
      } finally {
        if (controllersRef.current.get(taskId) === ctrl) {
          controllersRef.current.delete(taskId);
        }
      }

      if (!mountedRef.current) return;

      // Always reconcile authoritative task status after stream closes or drops
      const latestStatus = await refreshTaskStatus(taskId);
      const isDone = reachedTerminal || isTerminalCodingStatus(latestStatus?.status);
      if (isDone) {
        const wsId = latestStatus?.workspaceId || workspaceId;
        await fetchFinalDiff(taskId, wsId);
        return;
      }

      // Schedule bounded exponential-backoff reconnect from lastSequence
      if (attempt < 8) {
        const delayMs = Math.min(1000 * Math.pow(2, attempt), 8000);
        setCodingTasks((prev) =>
          prev[taskId] ? { ...prev, [taskId]: { ...prev[taskId], reconnecting: true } } : prev
        );
        const timer = setTimeout(() => {
          timersRef.current.delete(taskId);
          subscribeStream(taskId, latestStatus?.workspaceId || workspaceId, attempt + 1);
        }, delayMs);
        timersRef.current.set(taskId, timer);
      }
    },
    [fetchFinalDiff, refreshTaskStatus]
  );

  const attachCodingTask = useCallback(
    async (opts: AttachCodingTaskOptions) => {
      const { taskId, jobId, workspaceId, workspaceName } = opts;
      if (!taskId) return;

      setActiveCodingTaskId(taskId);
      setCodingTasks((prev) => {
        if (prev[taskId]) {
          return {
            ...prev,
            [taskId]: {
              ...prev[taskId],
              jobId: jobId || prev[taskId].jobId,
              workspaceId: workspaceId || prev[taskId].workspaceId,
              workspaceName: workspaceName || prev[taskId].workspaceName,
            },
          };
        }
        return {
          ...prev,
          [taskId]: {
            taskId,
            jobId: jobId || null,
            workspaceId: workspaceId || null,
            workspaceName: workspaceName || null,
            status: 'QUEUED',
            phase: 'QUEUED',
            lastSequence: 0,
            events: [],
            tools: [],
            filesModified: [],
            reconnecting: false,
            cancelRequested: false,
          },
        };
      });

      // 1. Recover persisted status + events history (covers refresh & reopen)
      const [statusData, eventsRes] = await Promise.all([
        refreshTaskStatus(taskId).catch(() => null),
        authFetch(`/api/v1/coding/tasks/${taskId}/events?after_sequence=0`).catch(() => null),
      ]);

      let historyEvents: CodingTaskEventItem[] = [];
      if (eventsRes && eventsRes.ok) {
        historyEvents = await eventsRes.json();
      }

      if (!mountedRef.current) return;

      if (historyEvents.length > 0) {
        const maxSeq = historyEvents[historyEvents.length - 1].sequenceNumber || 0;
        const prevMax = lastSeqRef.current.get(taskId) || 0;
        if (maxSeq > prevMax) lastSeqRef.current.set(taskId, maxSeq);

        setCodingTasks((prev) => {
          const cur = prev[taskId];
          if (!cur) return prev;
          const merged = mergeCodingEvents(cur.events, historyEvents);
          const lastEvt = merged[merged.length - 1];
          return {
            ...prev,
            [taskId]: {
              ...cur,
              events: merged,
              tools: mapEventsToTools(merged),
              lastSequence: lastEvt?.sequenceNumber || cur.lastSequence,
              phase: lastEvt?.phase || cur.phase,
              verification: extractVerificationResult(statusData, merged) || cur.verification,
            },
          };
        });
      }

      const resolvedStatus = statusData?.status || 'QUEUED';
      const resolvedWsId = statusData?.workspaceId || workspaceId || null;

      if (isTerminalCodingStatus(resolvedStatus)) {
        await fetchFinalDiff(taskId, resolvedWsId);
        return;
      }

      // 2. Open live SSE stream from last recovered sequence if not already streaming
      if (!controllersRef.current.has(taskId)) {
        subscribeStream(taskId, resolvedWsId, 0);
      }
    },
    [fetchFinalDiff, refreshTaskStatus, subscribeStream]
  );

  const cancelCodingTask = useCallback(async (taskId: string) => {
    try {
      const res = await authFetch(`/api/v1/coding/tasks/${taskId}/cancel`, { method: 'POST' });
      if (res.ok && mountedRef.current) {
        const data = await res.json();
        setCodingTasks((prev) => {
          const cur = prev[taskId];
          if (!cur) return prev;
          return {
            ...prev,
            [taskId]: {
              ...cur,
              status: data.status || 'CANCELLING',
              phase: data.status || cur.phase,
              cancelRequested: true,
            },
          };
        });
      }
    } catch (err) {
      console.error(`Failed to cancel coding task ${taskId}:`, err);
    }
  }, []);

  const resetCodingTasks = useCallback(() => {
    detachAll();
    lastSeqRef.current.clear();
    setActiveCodingTaskId(null);
    setCodingTasks({});
  }, [detachAll]);

  const activeCodingTask = activeCodingTaskId ? codingTasks[activeCodingTaskId] || null : null;

  return {
    codingTasks,
    activeCodingTask,
    attachCodingTask,
    cancelCodingTask,
    resetCodingTasks,
  };
}
