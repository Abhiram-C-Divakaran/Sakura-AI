import React, { useState } from 'react';
import { Terminal, Code, Cpu, ChevronDown, ChevronRight, CheckCircle2, Loader2 } from 'lucide-react';
import { ToolExecution, ToolExecutionProps } from './ToolExecution';
import { DiffViewer } from './DiffViewer';
import { DiffSummary, ChangedFile } from './DiffSummary';
import { VerificationSummary, VerificationResult } from './VerificationSummary';

export interface CodingActivityProps {
  status?: 'executing' | 'completed' | 'error';
  title?: string;
  step?: string;
  tools?: ToolExecutionProps[];
  diffText?: string;
  diffFiles?: ChangedFile[];
  verification?: VerificationResult;
  workspaceName?: string;
}

export const CodingActivity: React.FC<CodingActivityProps> = ({
  status = 'completed',
  title = 'Repository Coding Task',
  step,
  tools = [],
  diffText,
  diffFiles = [],
  verification,
  workspaceName
}) => {
  const [isExpanded, setIsExpanded] = useState(true);

  const isRunning = status === 'executing';

  return (
    <div className="rounded-xl border border-white/10 bg-[#0a0a0a] my-3 overflow-hidden shadow-lg">
      {/* Top Header Banner */}
      <div
        className="flex items-center justify-between px-3.5 py-2.5 bg-[#121212] border-b border-white/5 cursor-pointer select-none hover:bg-[#151515] transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2.5">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-neutral-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-neutral-400" />
          )}

          <div className="p-1 rounded bg-[#ff7597]/10 text-[#ff7597]">
            <Cpu className="w-3.5 h-3.5" />
          </div>

          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-xs text-neutral-200">{title}</span>
              {workspaceName && (
                <span className="px-1.5 py-0.5 rounded bg-white/5 text-[10px] text-neutral-400 font-mono">
                  {workspaceName}
                </span>
              )}
            </div>
            {step && <span className="text-[10px] text-neutral-500">{step}</span>}
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs">
          {isRunning ? (
            <span className="flex items-center gap-1 text-amber-400 text-[11px] font-medium">
              <Loader2 className="w-3 h-3 animate-spin" />
              Coding in Sandbox...
            </span>
          ) : (
            <span className="flex items-center gap-1 text-emerald-400 text-[11px] font-medium">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Completed
            </span>
          )}
        </div>
      </div>

      {/* Expanded body containing tools, diffs, and verification */}
      {isExpanded && (
        <div className="p-3 space-y-2.5 bg-[#070707]">
          {/* Tool Invocations */}
          {tools.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] uppercase font-semibold text-neutral-500 tracking-wider mb-1">
                Execution Steps ({tools.length})
              </div>
              {tools.map((tool, idx) => (
                <ToolExecution key={idx} {...tool} />
              ))}
            </div>
          )}

          {/* Diffs */}
          {(diffFiles.length > 0 || diffText) && (
            <div>
              <div className="text-[10px] uppercase font-semibold text-neutral-500 tracking-wider mb-1">
                Code Changes
              </div>
              {diffFiles.length > 0 && <DiffSummary files={diffFiles} />}
              {diffText && <DiffViewer diffText={diffText} />}
            </div>
          )}

          {/* Verification Results */}
          {verification && (
            <div>
              <div className="text-[10px] uppercase font-semibold text-neutral-500 tracking-wider mb-1">
                Automated Verification
              </div>
              <VerificationSummary result={verification} />
            </div>
          )}
        </div>
      )}
    </div>
  );
};
