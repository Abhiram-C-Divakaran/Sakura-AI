import React, { useState } from 'react';
import {
  Plus, Search, Pin, MessageSquare, BookOpen, FolderGit2,
  Calendar, Puzzle, ChevronDown, ChevronRight, MoreHorizontal,
  Pencil, Trash2, Share2, PanelLeftClose, PanelLeft
} from 'lucide-react';
import { Conversation } from '../../hooks/useConversation';
import { SakuraBrandHeader } from '../SakuraLogo';

export interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  conversations: Conversation[];
  activeConvId: string | null;
  onSelectConversation: (id: string) => void;
  onNewChat: () => void;
  onOpenSearch: () => void;
  activeView: 'chat' | 'library' | 'projects' | 'scheduled' | 'plugins';
  onSelectView: (view: 'chat' | 'library' | 'projects' | 'scheduled' | 'plugins') => void;
  onPinConversation: (id: string, isPinned: boolean) => void;
  onRenameConversation: (id: string, currentTitle: string) => void;
  onDeleteConversation: (id: string, title: string) => void;
  onShareConversation: (id: string, title: string) => void;
  isMobile?: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onToggle,
  conversations,
  activeConvId,
  onSelectConversation,
  onNewChat,
  onOpenSearch,
  activeView,
  onSelectView,
  onPinConversation,
  onRenameConversation,
  onDeleteConversation,
  onShareConversation,
  isMobile = false
}) => {
  const [pinnedOpen, setPinnedOpen] = useState(true);
  const [recentsOpen, setRecentsOpen] = useState(true);
  const [hoveredChatId, setHoveredChatId] = useState<string | null>(null);
  const [menuChatId, setMenuChatId] = useState<string | null>(null);

  const pinnedConversations = conversations.filter(c => c.is_pinned);
  const recentConversations = conversations.filter(c => !c.is_pinned);

  if (!isOpen) {
    return (
      <button
        onClick={onToggle}
        className="fixed top-3 left-3 z-40 p-2 rounded-xl bg-[#111111] border border-white/10 text-neutral-400 hover:text-white transition-colors"
        title="Open Sidebar"
      >
        <PanelLeft className="w-4 h-4" />
      </button>
    );
  }

  return (
    <>
      {/* Mobile Backdrop */}
      {isMobile && (
        <div
          className="fixed inset-0 bg-black/70 backdrop-blur-sm z-40 transition-opacity"
          onClick={onToggle}
        />
      )}

      <aside
        className={`${
          isMobile ? 'fixed inset-y-0 left-0 z-50 w-72' : 'relative w-64'
        } shrink-0 h-screen flex flex-col bg-[#000000] border-r border-white/10 text-xs select-none transition-all duration-200`}
      >
        {/* Top Header */}
        <div className="flex items-center justify-between p-3.5 border-b border-white/5">
          <SakuraBrandHeader />
          <button
            onClick={onToggle}
            className="p-1.5 rounded-lg text-neutral-500 hover:text-neutral-200 hover:bg-white/5 transition-colors"
            title="Collapse Sidebar"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        </div>

        {/* Action Controls */}
        <div className="p-3 space-y-2 border-b border-white/5">
          <button
            onClick={onNewChat}
            className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-white text-black font-semibold hover:bg-neutral-200 transition-all shadow-sm"
          >
            <Plus className="w-4 h-4" />
            <span>New Chat</span>
          </button>

          <button
            onClick={onOpenSearch}
            className="w-full flex items-center justify-between px-3 py-1.5 rounded-lg bg-[#0e0e0e] border border-white/5 text-neutral-400 hover:text-neutral-200 hover:border-white/10 transition-colors"
          >
            <div className="flex items-center gap-2">
              <Search className="w-3.5 h-3.5 text-neutral-500" />
              <span>Search chats...</span>
            </div>
            <span className="text-[10px] font-mono text-neutral-600 bg-white/5 px-1 rounded">⌘K</span>
          </button>
        </div>

        {/* Navigation Lists */}
        <div className="flex-1 overflow-y-auto sidebar-scroll p-2 space-y-4">
          {/* Pinned Chats */}
          {pinnedConversations.length > 0 && (
            <div>
              <div
                className="flex items-center justify-between px-2 py-1 text-[10px] uppercase font-semibold tracking-wider text-neutral-500 cursor-pointer"
                onClick={() => setPinnedOpen(!pinnedOpen)}
              >
                <div className="flex items-center gap-1.5">
                  <Pin className="w-3 h-3 text-[#ff7597]" />
                  <span>Pinned</span>
                </div>
                {pinnedOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              </div>

              {pinnedOpen && (
                <div className="mt-1 space-y-0.5">
                  {pinnedConversations.map(conv => (
                    <ConversationItem
                      key={conv.id}
                      conv={conv}
                      isActive={activeView === 'chat' && activeConvId === conv.id}
                      onSelect={() => {
                        onSelectView('chat');
                        onSelectConversation(conv.id);
                        if (isMobile) onToggle();
                      }}
                      onPin={() => onPinConversation(conv.id, true)}
                      onRename={() => onRenameConversation(conv.id, conv.title)}
                      onDelete={() => onDeleteConversation(conv.id, conv.title)}
                      onShare={() => onShareConversation(conv.id, conv.title)}
                      isMenuOpen={menuChatId === conv.id}
                      setMenuOpen={(val) => setMenuChatId(val ? conv.id : null)}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Recent Chats */}
          <div>
            <div
              className="flex items-center justify-between px-2 py-1 text-[10px] uppercase font-semibold tracking-wider text-neutral-500 cursor-pointer"
              onClick={() => setRecentsOpen(!recentsOpen)}
            >
              <span>Recent Chats</span>
              {recentsOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            </div>

            {recentsOpen && (
              <div className="mt-1 space-y-0.5">
                {recentConversations.length === 0 ? (
                  <div className="px-3 py-2 text-[11px] text-neutral-600 italic">No recent chats</div>
                ) : (
                  recentConversations.map(conv => (
                    <ConversationItem
                      key={conv.id}
                      conv={conv}
                      isActive={activeView === 'chat' && activeConvId === conv.id}
                      onSelect={() => {
                        onSelectView('chat');
                        onSelectConversation(conv.id);
                        if (isMobile) onToggle();
                      }}
                      onPin={() => onPinConversation(conv.id, false)}
                      onRename={() => onRenameConversation(conv.id, conv.title)}
                      onDelete={() => onDeleteConversation(conv.id, conv.title)}
                      onShare={() => onShareConversation(conv.id, conv.title)}
                      isMenuOpen={menuChatId === conv.id}
                      setMenuOpen={(val) => setMenuChatId(val ? conv.id : null)}
                    />
                  ))
                )}
              </div>
            )}
          </div>
        </div>

        {/* Bottom Primary Views Navigation */}
        <div className="p-2 border-t border-white/5 space-y-0.5 bg-[#030303]">
          <NavItem
            icon={<MessageSquare className="w-3.5 h-3.5" />}
            label="Chat"
            isActive={activeView === 'chat'}
            onClick={() => {
              onSelectView('chat');
              if (isMobile) onToggle();
            }}
          />
          <NavItem
            icon={<BookOpen className="w-3.5 h-3.5" />}
            label="Library"
            isActive={activeView === 'library'}
            onClick={() => {
              onSelectView('library');
              if (isMobile) onToggle();
            }}
          />
          <NavItem
            icon={<FolderGit2 className="w-3.5 h-3.5" />}
            label="Projects"
            isActive={activeView === 'projects'}
            onClick={() => {
              onSelectView('projects');
              if (isMobile) onToggle();
            }}
          />
          <NavItem
            icon={<Calendar className="w-3.5 h-3.5" />}
            label="Scheduled"
            isActive={activeView === 'scheduled'}
            onClick={() => {
              onSelectView('scheduled');
              if (isMobile) onToggle();
            }}
          />
          <NavItem
            icon={<Puzzle className="w-3.5 h-3.5" />}
            label="Plugins"
            isActive={activeView === 'plugins'}
            onClick={() => {
              onSelectView('plugins');
              if (isMobile) onToggle();
            }}
          />
        </div>
      </aside>
    </>
  );
};

interface ConversationItemProps {
  conv: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onPin: () => void;
  onRename: () => void;
  onDelete: () => void;
  onShare: () => void;
  isMenuOpen: boolean;
  setMenuOpen: (val: boolean) => void;
}

const ConversationItem: React.FC<ConversationItemProps> = ({
  conv,
  isActive,
  onSelect,
  onPin,
  onRename,
  onDelete,
  onShare,
  isMenuOpen,
  setMenuOpen
}) => {
  return (
    <div
      className={`group relative flex items-center justify-between px-2.5 py-1.5 rounded-lg cursor-pointer transition-colors ${
        isActive
          ? 'bg-[#151515] text-white font-medium border border-white/10'
          : 'text-neutral-400 hover:text-neutral-200 hover:bg-[#0c0c0c]'
      }`}
      onClick={onSelect}
    >
      <div className="flex items-center gap-2 truncate pr-2">
        <MessageSquare className={`w-3.5 h-3.5 shrink-0 ${isActive ? 'text-[#ff7597]' : 'text-neutral-600'}`} />
        <span className="truncate text-xs">{conv.title || 'Untitled Conversation'}</span>
      </div>

      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={(e) => {
            e.stopPropagation();
            setMenuOpen(!isMenuOpen);
          }}
          className="p-1 rounded hover:bg-white/10 text-neutral-400 hover:text-white"
          title="Options"
        >
          <MoreHorizontal className="w-3 h-3" />
        </button>
      </div>

      {/* Popover Menu */}
      {isMenuOpen && (
        <div
          className="absolute right-2 top-8 w-36 rounded-xl border border-white/10 bg-[#121212] shadow-2xl z-30 p-1 divide-y divide-white/5 text-[11px] animate-in fade-in zoom-in-95 duration-100"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="space-y-0.5 pb-1">
            <button
              onClick={() => {
                setMenuOpen(false);
                onPin();
              }}
              className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-white/5 text-neutral-300 hover:text-white"
            >
              <Pin className="w-3 h-3 text-[#ff7597]" />
              <span>{conv.is_pinned ? 'Unpin' : 'Pin'}</span>
            </button>
            <button
              onClick={() => {
                setMenuOpen(false);
                onRename();
              }}
              className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-white/5 text-neutral-300 hover:text-white"
            >
              <Pencil className="w-3 h-3" />
              <span>Rename</span>
            </button>
            <button
              onClick={() => {
                setMenuOpen(false);
                onShare();
              }}
              className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-white/5 text-neutral-300 hover:text-white"
            >
              <Share2 className="w-3 h-3" />
              <span>Share</span>
            </button>
          </div>
          <div className="pt-1">
            <button
              onClick={() => {
                setMenuOpen(false);
                onDelete();
              }}
              className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-rose-950/30 text-rose-400 hover:text-rose-300"
            >
              <Trash2 className="w-3 h-3" />
              <span>Delete</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

interface NavItemProps {
  icon: React.ReactNode;
  label: string;
  isActive: boolean;
  onClick: () => void;
}

const NavItem: React.FC<NavItemProps> = ({ icon, label, isActive, onClick }) => (
  <button
    onClick={onClick}
    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl transition-all text-xs font-medium text-left ${
      isActive
        ? 'bg-[#181818] text-white border border-white/10 shadow-sm'
        : 'text-neutral-400 hover:text-neutral-200 hover:bg-[#0c0c0c]'
    }`}
  >
    <span className={isActive ? 'text-[#ff7597]' : 'text-neutral-500'}>{icon}</span>
    <span>{label}</span>
  </button>
);
