import React, { useState, useEffect, useRef } from 'react';

export interface MenuItem {
  id: string;
  title: string;
  description: string;
  keywords: string[];
  actionType: 'upload' | 'library' | 'mode' | 'modal';
  modeId?: 'create_image' | 'web_search' | 'deep_research' | 'analyze' | 'visualize' | 'code_workspace';
  icon: (props: { className?: string }) => JSX.Element;
  badge?: string;
}

export const PLUS_MENU_ITEMS: MenuItem[] = [
  {
    id: 'upload_files',
    title: 'Add photos & files',
    description: 'Upload from this device',
    keywords: ['upload', 'photo', 'file', 'image', 'document', 'pdf', 'csv', 'attach'],
    actionType: 'upload',
    icon: ({ className = 'w-5 h-5' }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
      </svg>
    )
  },
  {
    id: 'library',
    title: 'Add from library',
    description: 'Browse your Sakura files',
    keywords: ['library', 'recent', 'docs', 'files', 'knowledge', 'storage', 'folder'],
    actionType: 'library',
    icon: ({ className = 'w-5 h-5' }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
        <path d="M6 6h10" />
        <path d="M6 10h10" />
        <path d="M6 14h6" />
      </svg>
    )
  },
  {
    id: 'create_image',
    title: 'Create image',
    description: 'Generate an image with Sakura AI',
    keywords: ['create image', 'generate image', 'picture', 'art', 'draw', 'dall-e', 'photo', 'render'],
    actionType: 'mode',
    modeId: 'create_image',
    badge: '✦ Mode',
    icon: ({ className = 'w-5 h-5' }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <rect width="18" height="18" x="3" y="3" rx="3" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <path d="m21 15-5-5L5 21" />
      </svg>
    )
  },
  {
    id: 'web_search',
    title: 'Web search',
    description: 'Search current information on the web',
    keywords: ['web search', 'search', 'internet', 'live', 'browse', 'news', 'google', 'duckduckgo'],
    actionType: 'mode',
    modeId: 'web_search',
    badge: '◎ Web',
    icon: ({ className = 'w-5 h-5' }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
        <path d="M2 12h20" />
      </svg>
    )
  },
  {
    id: 'deep_research',
    title: 'Deep research',
    description: 'Research a topic using multiple sources',
    keywords: ['deep research', 'research', 'investigate', 'multi-source', 'synthesis', 'report', 'study'],
    actionType: 'mode',
    modeId: 'deep_research',
    badge: '◆ Deep',
    icon: ({ className = 'w-5 h-5' }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2 2 12l10 10 10-10L12 2Z" />
        <path d="M12 8v8" />
        <path d="M8 12h8" />
      </svg>
    )
  },
  {
    id: 'analyze',
    title: 'Analyze',
    description: 'Analyze documents, data, code, or images',
    keywords: ['analyze', 'audit', 'inspect', 'metrics', 'dataset', 'document audit', 'sentiment'],
    actionType: 'mode',
    modeId: 'analyze',
    badge: '◇ Analyze',
    icon: ({ className = 'w-5 h-5' }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 20V10" />
        <path d="M18 20V4" />
        <path d="M6 20v-4" />
      </svg>
    )
  },
  {
    id: 'visualize',
    title: 'Visualize',
    description: 'Generate charts and interactive visualizations',
    keywords: ['visualize', 'chart', 'graph', 'diagram', 'mermaid', 'plots', 'visualization', 'bar chart'],
    actionType: 'mode',
    modeId: 'visualize',
    badge: '⌘ Chart',
    icon: ({ className = 'w-5 h-5' }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 3v18h18" />
        <path d="m19 9-5 5-4-4-3 3" />
      </svg>
    )
  },
  {
    id: 'code_workspace',
    title: 'Code workspace',
    description: 'Write, analyze, debug, or execute code',
    keywords: ['code', 'workspace', 'execute', 'debug', 'refactor', 'python', 'javascript', 'compiler'],
    actionType: 'mode',
    modeId: 'code_workspace',
    badge: '<> Code',
    icon: ({ className = 'w-5 h-5' }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </svg>
    )
  },
  {
    id: 'connect_apps',
    title: 'Connect apps',
    description: 'Access supported external services',
    keywords: ['connect', 'apps', 'integrations', 'github', 'drive', 'notion', 'slack', 'database', 'mcp'],
    actionType: 'modal',
    badge: '◉ Apps',
    icon: ({ className = 'w-5 h-5' }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <rect width="7" height="7" x="3" y="3" rx="1.5" />
        <rect width="7" height="7" x="14" y="3" rx="1.5" />
        <rect width="7" height="7" x="14" y="14" rx="1.5" />
        <rect width="7" height="7" x="3" y="14" rx="1.5" />
      </svg>
    )
  }
];

interface PlusMenuProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectUpload: () => void;
  onSelectLibrary: () => void;
  onToggleMode: (modeId: 'create_image' | 'web_search' | 'deep_research' | 'analyze' | 'visualize' | 'code_workspace') => void;
  onOpenConnectApps: () => void;
  activeModes: string[];
}

export const PlusMenu: React.FC<PlusMenuProps> = ({
  isOpen,
  onClose,
  onSelectUpload,
  onSelectLibrary,
  onToggleMode,
  onOpenConnectApps,
  activeModes
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const filteredItems = PLUS_MENU_ITEMS.filter((item) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      item.title.toLowerCase().includes(q) ||
      item.description.toLowerCase().includes(q) ||
      item.keywords.some((k) => k.toLowerCase().includes(q))
    );
  });

  // Reset selection index when query changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [searchQuery]);

  // Focus search when opened
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => {
        searchInputRef.current?.focus();
      }, 50);
    } else {
      setSearchQuery('');
    }
  }, [isOpen]);

  // Outside click listener
  useEffect(() => {
    if (!isOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, onClose]);

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1 < filteredItems.length ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 >= 0 ? prev - 1 : filteredItems.length - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filteredItems[selectedIndex]) {
        handleSelectItem(filteredItems[selectedIndex]);
      }
    }
  };

  const handleSelectItem = (item: MenuItem) => {
    if (item.actionType === 'upload') {
      onSelectUpload();
      onClose();
    } else if (item.actionType === 'library') {
      onSelectLibrary();
      onClose();
    } else if (item.actionType === 'modal') {
      onOpenConnectApps();
      onClose();
    } else if (item.actionType === 'mode' && item.modeId) {
      onToggleMode(item.modeId);
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label="Tools, attachments and skills menu"
      onKeyDown={handleKeyDown}
      className="absolute bottom-full left-0 right-0 mb-3 mx-auto w-full max-w-[48rem] bg-[#282828] border border-[#3A3A3A] rounded-2xl shadow-2xl overflow-hidden z-50 animate-in fade-in slide-in-from-bottom-2 duration-150 flex flex-col"
      style={{
        boxShadow: '0 12px 36px -4px rgba(0, 0, 0, 0.75), 0 0 0 1px rgba(255, 255, 255, 0.05)',
      }}
    >
      {/* Search Bar at Top */}
      <div className="p-2.5 border-b border-[#383838] bg-[#222222] flex items-center gap-2">
        <svg className="w-4 h-4 text-[#888888] flex-shrink-0 ml-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          ref={searchInputRef}
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search tools, files, connectors & skills..."
          className="flex-1 bg-transparent text-[13px] text-[#F5F5F5] placeholder:text-[#888888] focus:outline-none px-1 py-1"
          aria-label="Search tools, files, connectors and skills"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="p-1 text-[#888888] hover:text-[#F5F5F5] rounded text-xs transition-colors"
            title="Clear search"
          >
            ✕
          </button>
        )}
      </div>

      {/* Item List */}
      <div className="max-h-[340px] overflow-y-auto p-1.5 space-y-0.5" role="none">
        {filteredItems.length === 0 ? (
          <div className="py-8 text-center text-[13px] text-[#888888]">
            No matching tools or actions found.
          </div>
        ) : (
          filteredItems.map((item, index) => {
            const isSelected = index === selectedIndex;
            const isModeActive = item.modeId && activeModes.includes(item.modeId);
            const Icon = item.icon;

            return (
              <button
                key={item.id}
                role="menuitem"
                onClick={() => handleSelectItem(item)}
                onMouseEnter={() => setSelectedIndex(index)}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-left transition-colors cursor-pointer group ${
                  isSelected ? 'bg-[#444444]' : 'hover:bg-[#383838]'
                }`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div
                    className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 transition-colors ${
                      isModeActive
                        ? 'bg-[#35D0BA]/20 text-[#35D0BA]'
                        : isSelected
                        ? 'bg-[#555555] text-[#F5F5F5]'
                        : 'bg-[#333333] text-[#D0D0D0] group-hover:text-white'
                    }`}
                  >
                    <Icon className="w-4 h-4" />
                  </div>
                  <div className="flex flex-col min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13.5px] font-medium text-[#F5F5F5] tracking-tight truncate">
                        {item.title}
                      </span>
                      {isModeActive && (
                        <span className="text-[9px] font-semibold bg-[#35D0BA]/20 text-[#35D0BA] px-1.5 py-0.5 rounded border border-[#35D0BA]/30">
                          Active
                        </span>
                      )}
                    </div>
                    <span className="text-[11.5px] text-[#A5A5A5] truncate group-hover:text-[#D0D0D0]">
                      {item.description}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                  {item.badge && !isModeActive && (
                    <span className="text-[10px] text-[#888888] font-mono group-hover:text-[#BBBBBB]">
                      {item.badge}
                    </span>
                  )}
                  {isSelected && (
                    <span className="text-[10px] font-mono text-[#AAAAAA] border border-[#555555] rounded px-1.5 py-0.5 bg-[#333333]">
                      ↵
                    </span>
                  )}
                </div>
              </button>
            );
          })
        )}
      </div>

      {/* Keyboard Helper Footer */}
      <div className="px-3 py-2 bg-[#202020] border-t border-[#333333] flex items-center justify-between text-[10.5px] text-[#888888] font-mono">
        <div className="flex items-center gap-2">
          <span>↑↓ Navigate</span>
          <span>•</span>
          <span>↵ Select</span>
          <span>•</span>
          <span>Esc Close</span>
        </div>
        <span>Sakura Multi-Tool Core</span>
      </div>
    </div>
  );
};
