import React from 'react';
import { GitBranch, FolderGit2, ChevronDown } from 'lucide-react';
import { Workspace } from '../../hooks/useWorkspace';

export interface WorkspaceSelectorProps {
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  onSelectWorkspace: (id: string) => void;
  onOpenNewWorkspaceModal?: () => void;
}

export const WorkspaceSelector: React.FC<WorkspaceSelectorProps> = ({
  workspaces,
  activeWorkspaceId,
  onSelectWorkspace,
  onOpenNewWorkspaceModal
}) => {
  const activeWorkspace = workspaces.find(w => w.id === activeWorkspaceId);

  return (
    <div className="relative inline-block text-left">
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-white/10 bg-[#111111] hover:bg-[#161616] transition-colors text-xs">
        <FolderGit2 className="w-3.5 h-3.5 text-[#ff7597]" />
        <select
          value={activeWorkspaceId || ''}
          onChange={(e) => onSelectWorkspace(e.target.value)}
          className="bg-transparent text-neutral-200 focus:outline-none cursor-pointer pr-4 font-medium text-xs appearance-none"
        >
          {workspaces.length === 0 && (
            <option value="" disabled>No workspaces</option>
          )}
          {workspaces.map(w => (
            <option key={w.id} value={w.id} className="bg-[#111111] text-white">
              {w.name} ({w.branch || 'main'})
            </option>
          ))}
        </select>
        <ChevronDown className="w-3 h-3 text-neutral-500 pointer-events-none -ml-3" />

        {activeWorkspace?.branch && (
          <div className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-white/5 text-[10px] text-neutral-400 ml-1 font-mono">
            <GitBranch className="w-2.5 h-2.5 text-[#ff7597]" />
            <span>{activeWorkspace.branch}</span>
          </div>
        )}
      </div>
    </div>
  );
};
