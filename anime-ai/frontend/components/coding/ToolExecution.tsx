import React, { useState } from 'react';
import { Terminal, CheckCircle2, XCircle, Loader2, ChevronDown, ChevronRight, AlertTriangle } from 'lucide-react';

export interface ToolExecutionProps {
  toolName: string;
  command?: string;
  args?: Record<string, any>;
  status?: 'running' | 'success' | 'error';
  stdout?: string;
  stderr?: string;
  exitCode?: number;
  durationMs?: number;
  truncated?: boolean;
}

export const ToolExecution: React.FC<ToolExecutionProps> = ({
  toolName,
  command,
  args,
  status = 'success',
  stdout,
  stderr,
  exitCode = 0,
  durationMs,
  truncated
}) => {
  const [isExpanded, setIsExpanded] = useState(status === 'error');

  const displayCommand = command || (args?.command ? String(args.command) : '');
  const hasOutput = Boolean(stdout?.trim() || stderr?.trim());

  return (
    <div className="rounded-xl border border-white/10 bg-[#080808] overflow-hidden my-2.5 text-xs font-mono">
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2 bg-[#101010] cursor-pointer select-none hover:bg-[#141414] transition-colors"
        onClick={() => hasOutput && setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2 min-w-0">
          {hasOutput ? (
            isExpanded ? <ChevronDown className="w-3.5 h-3.5 text-neutral-400 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-neutral-400 shrink-0" />
          ) : (
            <div className="w-3.5" />
          )}
          <Terminal className="w-3.5 h-3.5 text-[#ff7597] shrink-0" />
          <span className="font-semibold text-neutral-200 shrink-0">{toolName}</span>
          {displayCommand && (
            <span className="text-neutral-400 truncate max-w-md text-[11px] font-normal">
              {displayCommand}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {durationMs !== undefined && (
            <span className="text-[10px] text-neutral-500">{durationMs}ms</span>
          )}
          {status === 'running' && (
            <span className="flex items-center gap-1 text-amber-400 text-[11px]">
              <Loader2 className="w-3 h-3 animate-spin" />
              Running
            </span>
          )}
          {status === 'success' && (
            <span className="flex items-center gap-1 text-emerald-400 text-[11px]">
              <CheckCircle2 className="w-3 h-3" />
              Done
            </span>
          )}
          {status === 'error' && (
            <span className="flex items-center gap-1 text-rose-400 text-[11px]">
              <XCircle className="w-3 h-3" />
              Failed {exitCode !== undefined && `(${exitCode})`}
            </span>
          )}
        </div>
      </div>

      {/* Output details */}
      {isExpanded && hasOutput && (
        <div className="p-3 bg-[#030303] border-t border-white/5 space-y-2">
          {stdout && (
            <div>
              <div className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">stdout</div>
              <pre className="text-neutral-300 whitespace-pre-wrap break-all leading-relaxed max-h-60 overflow-y-auto bg-[#0a0a0a] p-2 rounded border border-white/5">
                {stdout}
              </pre>
            </div>
          )}
          {stderr && (
            <div>
              <div className="text-[10px] text-rose-400 uppercase tracking-wider mb-1">stderr</div>
              <pre className="text-rose-300 whitespace-pre-wrap break-all leading-relaxed max-h-40 overflow-y-auto bg-rose-950/20 p-2 rounded border border-rose-900/30">
                {stderr}
              </pre>
            </div>
          )}
          {truncated && (
            <div className="flex items-center gap-1.5 text-[10px] text-amber-400">
              <AlertTriangle className="w-3 h-3" />
              <span>Output exceeded capture limit and was truncated.</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
