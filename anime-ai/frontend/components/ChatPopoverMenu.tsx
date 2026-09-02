import React, { useEffect, useRef } from 'react';

interface ChatPopoverMenuProps {
  isOpen: boolean;
  onClose: () => void;
  isPinned?: boolean;
  onShare: () => void;
  onRename: () => void;
  onTogglePin: () => void;
  onArchive: () => void;
  onDelete: () => void;
  anchorRect?: DOMRect | null;
}

export const ChatPopoverMenu: React.FC<ChatPopoverMenuProps> = ({
  isOpen,
  onClose,
  isPinned = false,
  onShare,
  onRename,
  onTogglePin,
  onArchive,
  onDelete,
  anchorRect
}) => {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const handleOutsideClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleOutsideClick);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // Calculate position adjacent to three-dot button with boundary checking
  let top = 0;
  let left = 0;
  if (anchorRect) {
    top = anchorRect.bottom + 4;
    left = anchorRect.left - 140; // Align neatly under/next to button

    if (typeof window !== 'undefined') {
      const menuHeight = 220;
      const menuWidth = 190;

      // Vertical overflow check
      if (top + menuHeight > window.innerHeight) {
        top = Math.max(8, anchorRect.top - menuHeight - 4);
      }
      // Horizontal overflow check
      if (left + menuWidth > window.innerWidth) {
        left = window.innerWidth - menuWidth - 12;
      }
      if (left < 8) {
        left = 8;
      }
    }
  }

  return (
    <div
      ref={menuRef}
      style={{
        position: 'fixed',
        top: `${top}px`,
        left: `${left}px`,
        zIndex: 9999
      }}
      className="w-[185px] bg-theme-popover border border-theme-border rounded-[18px] shadow-2xl p-1.5 flex flex-col text-theme-text animate-in fade-in zoom-in-95 duration-100 select-none"
      onClick={(e) => e.stopPropagation()}
    >
      {/* Share */}
      <button
        type="button"
        onClick={() => {
          onShare();
          onClose();
        }}
        className="w-full flex items-center gap-3 px-3 py-2 text-[14px] text-theme-text font-normal rounded-[10px] hover:bg-theme-hover transition-colors cursor-pointer text-left"
      >
        <svg className="w-4 h-4 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
          <polyline points="16 6 12 2 8 6" />
          <line x1="12" y1="2" x2="12" y2="15" />
        </svg>
        <span>Share</span>
      </button>

      {/* Rename */}
      <button
        type="button"
        onClick={() => {
          onRename();
          onClose();
        }}
        className="w-full flex items-center gap-3 px-3 py-2 text-[14px] text-theme-text font-normal rounded-[10px] hover:bg-theme-hover transition-colors cursor-pointer text-left"
      >
        <svg className="w-4 h-4 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
          <path d="m15 5 4 4" />
        </svg>
        <span>Rename</span>
      </button>

      {/* Pin / Unpin */}
      <button
        type="button"
        onClick={() => {
          onTogglePin();
          onClose();
        }}
        className="w-full flex items-center gap-3 px-3 py-2 text-[14px] text-theme-text font-normal rounded-[10px] hover:bg-theme-hover transition-colors cursor-pointer text-left"
      >
        <svg className="w-4 h-4 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <line x1="12" y1="17" x2="12" y2="22" />
          <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.76V6h1a1 1 0 0 0 0-2H8a1 1 0 0 0 0 2h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
        </svg>
        <span>{isPinned ? 'Unpin' : 'Pin'}</span>
      </button>

      {/* Archive */}
      <button
        type="button"
        onClick={() => {
          onArchive();
          onClose();
        }}
        className="w-full flex items-center gap-3 px-3 py-2 text-[14px] text-theme-text font-normal rounded-[10px] hover:bg-theme-hover transition-colors cursor-pointer text-left"
      >
        <svg className="w-4 h-4 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <rect width="20" height="5" x="2" y="3" rx="1" />
          <path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" />
          <path d="M10 12h4" />
        </svg>
        <span>Archive</span>
      </button>

      <div className="h-[1px] bg-theme-border my-1" />

      {/* Delete */}
      <button
        type="button"
        onClick={() => {
          onDelete();
          onClose();
        }}
        className="w-full flex items-center gap-3 px-3 py-2 text-[14px] text-red-500 font-normal rounded-[10px] hover:bg-red-500/10 transition-colors cursor-pointer text-left"
      >
        <svg className="w-4 h-4 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 6h18" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
        </svg>
        <span>Delete</span>
      </button>
    </div>
  );
};
