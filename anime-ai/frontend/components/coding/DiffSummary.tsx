import React from 'react';
import { GitCommit, FileText, Plus, Minus } from 'lucide-react';

export interface ChangedFile {
  filename: string;
  status?: 'added' | 'modified' | 'deleted';
  additions: number;
  deletions: number;
}

export interface DiffSummaryProps {
  files?: ChangedFile[];
  commitMessage?: string;
  branch?: string;
}

export const DiffSummary: React.FC<DiffSummaryProps> = ({
  files = [],
  commitMessage,
  branch = 'main'
}) => {
  const totalAdditions = files.reduce((acc, f) => acc + (f.additions || 0), 0);
  const totalDeletions = files.reduce((acc, f) => acc + (f.deletions || 0), 0);

  if (files.length === 0 && !commitMessage) return null;

  return (
    <div className="rounded-xl border border-white/10 bg-[#0c0c0c] p-3 my-2 text-xs">
      <div className="flex items-center justify-between pb-2 border-b border-white/5">
        <div className="flex items-center gap-2">
          <GitCommit className="w-4 h-4 text-[#ff7597]" />
          <span className="font-medium text-neutral-200">
            {commitMessage || `${files.length} file${files.length !== 1 ? 's' : ''} changed`}
          </span>
        </div>
        <div className="flex items-center gap-2 font-mono">
          <span className="flex items-center gap-0.5 text-emerald-400">
            <Plus className="w-3 h-3" />
            {totalAdditions}
          </span>
          <span className="flex items-center gap-0.5 text-rose-400">
            <Minus className="w-3 h-3" />
            {totalDeletions}
          </span>
        </div>
      </div>

      {files.length > 0 && (
        <div className="mt-2 space-y-1">
          {files.map((file, idx) => (
            <div key={idx} className="flex items-center justify-between text-neutral-400 hover:text-neutral-200 transition-colors py-0.5 font-mono text-[11px]">
              <div className="flex items-center gap-1.5 truncate pr-2">
                <FileText className="w-3 h-3 text-neutral-500 shrink-0" />
                <span className="truncate">{file.filename}</span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {file.additions > 0 && <span className="text-emerald-400">+{file.additions}</span>}
                {file.deletions > 0 && <span className="text-rose-400">-{file.deletions}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
