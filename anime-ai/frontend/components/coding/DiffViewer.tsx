import React, { useState } from 'react';
import { Copy, Check, FileCode, ChevronDown, ChevronRight } from 'lucide-react';

export interface DiffViewerProps {
  diffText?: string;
  filename?: string;
  additions?: number;
  deletions?: number;
  collapsible?: boolean;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({
  diffText = '',
  filename = 'changes.patch',
  additions = 0,
  deletions = 0,
  collapsible = true
}) => {
  const [copied, setCopied] = useState(false);
  const [isExpanded, setIsExpanded] = useState(true);

  const handleCopy = () => {
    navigator.clipboard.writeText(diffText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const lines = diffText.split('\n');

  return (
    <div className="rounded-xl border border-white/10 bg-[#0a0a0a] overflow-hidden my-3 text-xs font-mono">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-[#121212] border-b border-white/5">
        <div
          className={`flex items-center gap-2 ${collapsible ? 'cursor-pointer select-none' : ''}`}
          onClick={() => collapsible && setIsExpanded(!isExpanded)}
        >
          {collapsible && (
            isExpanded ? <ChevronDown className="w-3.5 h-3.5 text-neutral-400" /> : <ChevronRight className="w-3.5 h-3.5 text-neutral-400" />
          )}
          <FileCode className="w-3.5 h-3.5 text-[#ff7597]" />
          <span className="text-neutral-200 font-medium">{filename}</span>
          {(additions > 0 || deletions > 0) && (
            <div className="flex items-center gap-1.5 ml-2">
              {additions > 0 && <span className="text-emerald-400 font-semibold">+{additions}</span>}
              {deletions > 0 && <span className="text-rose-400 font-semibold">-{deletions}</span>}
            </div>
          )}
        </div>

        <button
          onClick={handleCopy}
          className="flex items-center gap-1 px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-neutral-400 hover:text-neutral-200 transition-colors"
          title="Copy diff patch"
        >
          {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
          <span className="text-[10px]">{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>

      {/* Code diff lines */}
      {isExpanded && (
        <div className="overflow-x-auto max-h-80 overflow-y-auto p-2 bg-[#050505]">
          <pre className="m-0 leading-relaxed font-mono">
            {lines.map((line, idx) => {
              let lineStyle = 'text-neutral-400';
              let bgStyle = '';
              let prefix = line[0] || ' ';

              if (line.startsWith('+') && !line.startsWith('+++')) {
                lineStyle = 'text-emerald-300';
                bgStyle = 'bg-emerald-950/25 -mx-2 px-2';
              } else if (line.startsWith('-') && !line.startsWith('---')) {
                lineStyle = 'text-rose-300';
                bgStyle = 'bg-rose-950/25 -mx-2 px-2';
              } else if (line.startsWith('@@')) {
                lineStyle = 'text-cyan-400 font-semibold';
                bgStyle = 'bg-cyan-950/15 -mx-2 px-2';
              }

              return (
                <div key={idx} className={`flex items-start ${bgStyle}`}>
                  <span className="w-8 text-neutral-600 select-none text-right pr-3 shrink-0">
                    {idx + 1}
                  </span>
                  <span className={`${lineStyle} whitespace-pre`}>{line}</span>
                </div>
              );
            })}
          </pre>
        </div>
      )}
    </div>
  );
};
