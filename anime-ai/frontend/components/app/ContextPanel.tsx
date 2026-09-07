import React, { useState } from 'react';
import {
  Cpu, BookMarked, Paperclip, CheckCircle2,
  XCircle, Clock, RotateCcw, X, Plus, Trash2, Loader2
} from 'lucide-react';
import { BackgroundTask } from '../../hooks/useTasks';

export interface ContextPanelProps {
  isOpen: boolean;
  onClose: () => void;
  tasks: BackgroundTask[];
  onCancelTask: (id: string) => void;
  onRetryTask: (id: string) => void;
  onClearCompletedTasks: () => void;
  memories?: any[];
  documents?: any[];
}

export const ContextPanel: React.FC<ContextPanelProps> = ({
  isOpen,
  onClose,
  tasks,
  onCancelTask,
  onRetryTask,
  onClearCompletedTasks,
  memories = [],
  documents = []
}) => {
  const [activeTab, setActiveTab] = useState<'tasks' | 'memories' | 'files'>('tasks');

  if (!isOpen) return null;

  const runningTasks = tasks.filter(t => ['Running', 'Starting', 'Queued'].includes(t.status));

  return (
    <aside className="w-80 shrink-0 h-full border-l border-white/10 bg-[#050505] flex flex-col text-xs select-none">
      {/* Header Tabs */}
      <div className="flex items-center justify-between p-3 border-b border-white/10 bg-[#080808]">
        <div className="flex items-center gap-1 bg-[#121212] p-0.5 rounded-lg border border-white/5">
          <button
            onClick={() => setActiveTab('tasks')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-colors ${
              activeTab === 'tasks' ? 'bg-[#ff7597]/20 text-[#ff7597] font-semibold' : 'text-neutral-400 hover:text-white'
            }`}
          >
            <Cpu className="w-3.5 h-3.5" />
            <span>Tasks</span>
            {runningTasks.length > 0 && (
              <span className="w-1.5 h-1.5 rounded-full bg-[#ff7597] animate-pulse" />
            )}
          </button>

          <button
            onClick={() => setActiveTab('memories')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-colors ${
              activeTab === 'memories' ? 'bg-[#ff7597]/20 text-[#ff7597] font-semibold' : 'text-neutral-400 hover:text-white'
            }`}
          >
            <BookMarked className="w-3.5 h-3.5" />
            <span>Memory</span>
          </button>

          <button
            onClick={() => setActiveTab('files')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-colors ${
              activeTab === 'files' ? 'bg-[#ff7597]/20 text-[#ff7597] font-semibold' : 'text-neutral-400 hover:text-white'
            }`}
          >
            <Paperclip className="w-3.5 h-3.5" />
            <span>Files</span>
          </button>
        </div>

        <button
          onClick={onClose}
          className="p-1.5 rounded-lg text-neutral-500 hover:text-neutral-200 hover:bg-white/5 transition-colors"
          title="Close panel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Panel Content */}
      <div className="flex-1 overflow-y-auto sidebar-scroll p-3 space-y-3">
        {activeTab === 'tasks' && (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-[11px] text-neutral-400">
              <span className="font-semibold text-neutral-300">Background Tasks ({tasks.length})</span>
              {tasks.some(t => ['Completed', 'Failed', 'Cancelled'].includes(t.status)) && (
                <button
                  onClick={onClearCompletedTasks}
                  className="text-[10px] text-neutral-500 hover:text-neutral-300 transition-colors"
                >
                  Clear Done
                </button>
              )}
            </div>

            {tasks.length === 0 ? (
              <div className="p-4 text-center text-neutral-600 italic">No background tasks</div>
            ) : (
              tasks.map(task => (
                <div
                  key={task.id}
                  className="p-2.5 rounded-xl border border-white/5 bg-[#0a0a0a] space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-neutral-200 truncate pr-2 text-xs">
                      {task.title || task.type}
                    </span>
                    <TaskStatusBadge status={task.status} />
                  </div>

                  {task.error && (
                    <div className="text-[10px] text-rose-400 line-clamp-2 bg-rose-950/20 p-1.5 rounded">
                      {task.error}
                    </div>
                  )}

                  <div className="flex items-center justify-between text-[10px] text-neutral-500 pt-1">
                    <span>{new Date(task.created_at).toLocaleTimeString()}</span>
                    <div className="flex items-center gap-1.5">
                      {['Running', 'Starting', 'Queued'].includes(task.status) && (
                        <button
                          onClick={() => onCancelTask(task.id)}
                          className="text-neutral-400 hover:text-rose-400"
                        >
                          Cancel
                        </button>
                      )}
                      {['Failed', 'Cancelled'].includes(task.status) && (
                        <button
                          onClick={() => onRetryTask(task.id)}
                          className="flex items-center gap-0.5 text-neutral-400 hover:text-white"
                        >
                          <RotateCcw className="w-2.5 h-2.5" />
                          <span>Retry</span>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'memories' && (
          <div className="space-y-2">
            <span className="text-[11px] font-semibold text-neutral-300">Long-term Memories</span>
            {memories.length === 0 ? (
              <div className="p-4 text-center text-neutral-600 italic">No stored memories</div>
            ) : (
              memories.map((m, idx) => (
                <div key={idx} className="p-2.5 rounded-xl border border-white/5 bg-[#0a0a0a] text-neutral-300 text-[11px] leading-relaxed">
                  {m.content || m.text}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'files' && (
          <div className="space-y-2">
            <span className="text-[11px] font-semibold text-neutral-300">Attached Documents</span>
            {documents.length === 0 ? (
              <div className="p-4 text-center text-neutral-600 italic">No documents attached</div>
            ) : (
              documents.map((doc, idx) => (
                <div key={idx} className="p-2.5 rounded-xl border border-white/5 bg-[#0a0a0a] flex items-center justify-between text-neutral-300 text-[11px]">
                  <span className="truncate">{doc.filename}</span>
                  <span className="text-[10px] text-neutral-500">{doc.indexing_status || 'READY'}</span>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </aside>
  );
};

const TaskStatusBadge: React.FC<{ status: string }> = ({ status }) => {
  switch (status) {
    case 'Running':
    case 'Starting':
      return (
        <span className="flex items-center gap-1 text-[10px] text-amber-400 font-mono">
          <Loader2 className="w-3 h-3 animate-spin" />
          {status}
        </span>
      );
    case 'Completed':
      return (
        <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-mono">
          <CheckCircle2 className="w-3 h-3" />
          Done
        </span>
      );
    case 'Failed':
      return (
        <span className="flex items-center gap-1 text-[10px] text-rose-400 font-mono">
          <XCircle className="w-3 h-3" />
          Failed
        </span>
      );
    default:
      return <span className="text-[10px] text-neutral-500 font-mono">{status}</span>;
  }
};
