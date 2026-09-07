import React, { useState } from 'react';
import {
  Share2, Files, PanelRightClose, PanelRightOpen,
  CheckCircle, AlertCircle, Pencil, Check, X
} from 'lucide-react';
import { AccountMenu } from './AccountMenu';
import { WorkspaceSelector } from '../coding/WorkspaceSelector';
import { Workspace } from '../../hooks/useWorkspace';
import { SystemCapabilities } from '../../hooks/useCapabilities';

export interface TopBarProps {
  title: string;
  conversationId: string | null;
  onRenameTitle?: (newTitle: string) => void;
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  onSelectWorkspace: (id: string) => void;
  capabilities: SystemCapabilities | null;
  rightPanelOpen: boolean;
  onToggleRightPanel: () => void;
  onOpenShareModal: () => void;
  onOpenFilesSheet: () => void;
  currentUser: string | null;
  onLogout: () => void;
  onOpenSettings?: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  title,
  conversationId,
  onRenameTitle,
  workspaces,
  activeWorkspaceId,
  onSelectWorkspace,
  capabilities,
  rightPanelOpen,
  onToggleRightPanel,
  onOpenShareModal,
  onOpenFilesSheet,
  currentUser,
  onLogout,
  onOpenSettings
}) => {
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editedTitle, setEditedTitle] = useState(title);
  const [showAccountMenu, setShowAccountMenu] = useState(false);

  const handleSaveTitle = () => {
    if (editedTitle.trim() && editedTitle !== title && onRenameTitle) {
      onRenameTitle(editedTitle.trim());
    }
    setIsEditingTitle(false);
  };

  const isOperational = capabilities?.status === 'OPERATIONAL';
  const displayName = !currentUser || currentUser === 'Operator' ? 'Account' : currentUser;

  return (
    <header className="h-14 border-b border-white/10 bg-[#000000] px-4 flex items-center justify-between shrink-0 select-none z-20">
      {/* Left Title / Workspace Area */}
      <div className="flex items-center gap-3 min-w-0">
        {isEditingTitle ? (
          <div className="flex items-center gap-1.5">
            <input
              type="text"
              value={editedTitle}
              onChange={(e) => setEditedTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveTitle();
                if (e.key === 'Escape') setIsEditingTitle(false);
              }}
              autoFocus
              className="bg-[#111111] border border-white/20 rounded px-2 py-0.5 text-xs text-white focus:outline-none focus:border-[#ff7597]"
            />
            <button
              onClick={handleSaveTitle}
              className="p-1 rounded hover:bg-white/10 text-emerald-400"
            >
              <Check className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setIsEditingTitle(false)}
              className="p-1 rounded hover:bg-white/10 text-neutral-500"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 group cursor-pointer" onClick={() => conversationId && setIsEditingTitle(true)}>
            <h2 className="text-sm font-semibold text-neutral-100 truncate max-w-xs md:max-w-md">
              {title}
            </h2>
            {conversationId && (
              <Pencil className="w-3 h-3 text-neutral-600 opacity-0 group-hover:opacity-100 transition-opacity" />
            )}
          </div>
        )}

        {/* Workspace Selector */}
        {workspaces.length > 0 && (
          <div className="hidden sm:block ml-2 border-l border-white/10 pl-3">
            <WorkspaceSelector
              workspaces={workspaces}
              activeWorkspaceId={activeWorkspaceId}
              onSelectWorkspace={onSelectWorkspace}
            />
          </div>
        )}
      </div>

      {/* Right Controls */}
      <div className="flex items-center gap-2">
        {/* Truthful Capabilities Health Indicator */}
        <div
          className="hidden md:flex items-center gap-1.5 px-2 py-1 rounded-full bg-white/5 border border-white/5 text-[11px]"
          title={capabilities ? `System: ${capabilities.status}` : 'Checking capability status...'}
        >
          <span
            className={`w-2 h-2 rounded-full ${
              isOperational ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]' : 'bg-amber-400'
            }`}
          />
          <span className="text-neutral-400 font-medium">
            {isOperational ? 'Operational' : capabilities?.status || 'Connecting'}
          </span>
        </div>

        {/* Conversation Files Sheet Trigger */}
        <button
          onClick={onOpenFilesSheet}
          className="p-2 rounded-xl text-neutral-400 hover:text-white hover:bg-white/5 transition-colors"
          title="Conversation Files"
        >
          <Files className="w-4 h-4" />
        </button>

        {/* Share Button */}
        {conversationId && (
          <button
            onClick={onOpenShareModal}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl border border-white/10 bg-[#0e0e0e] hover:bg-[#151515] text-neutral-300 hover:text-white transition-colors text-xs font-medium"
            title="Share Conversation"
          >
            <Share2 className="w-3.5 h-3.5 text-[#ff7597]" />
            <span className="hidden sm:inline">Share</span>
          </button>
        )}

        {/* Right Panel Toggle */}
        <button
          onClick={onToggleRightPanel}
          className="p-2 rounded-xl text-neutral-400 hover:text-white hover:bg-white/5 transition-colors"
          title={rightPanelOpen ? 'Collapse Context Panel' : 'Expand Context Panel'}
        >
          {rightPanelOpen ? (
            <PanelRightClose className="w-4 h-4" />
          ) : (
            <PanelRightOpen className="w-4 h-4" />
          )}
        </button>

        {/* User Avatar Menu Trigger */}
        <div className="relative ml-1">
          <button
            onClick={() => setShowAccountMenu(!showAccountMenu)}
            className="w-7 h-7 rounded-full bg-gradient-to-tr from-[#ff7597] to-[#ff2d78] flex items-center justify-center text-white font-bold text-xs shadow hover:opacity-90 transition-opacity"
            title="Account Menu"
          >
            {displayName[0]?.toUpperCase() || 'A'}
          </button>

          <AccountMenu
            currentUser={displayName}
            isOpen={showAccountMenu}
            onClose={() => setShowAccountMenu(false)}
            onLogout={onLogout}
            onOpenSettings={onOpenSettings}
          />
        </div>
      </div>
    </header>
  );
};
