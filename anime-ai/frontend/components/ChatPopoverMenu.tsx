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
      className="w-[185px] bg-[#323232] border border-[#444444] rounded-[18px] shadow-2xl p-1.5 flex flex-col text-[#F5F5F5] animate-in fade-in zoom-in-95 duration-100 select-none"
      onClick={(e) => e.stopPropagation()}
    >
      {/* Share */}
      <button
        type="button"
        onClick={() => {
          onShare();
          onClose();
        }}
        className="w-full flex items-center gap-3 px-3 py-2 text-[14px] text-[#F5F5F5] font-normal rounded-[10px] hover:bg-[#454545] transition-colors cursor-pointer text-left"
      >
        <svg className="w-4 h-4 text-[#CCCCCC]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
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
        className="w-full flex items-center gap-3 px-3 py-2 text-[14px] text-[#F5F5F5] font-normal rounded-[10px] hover:bg-[#454545] transition-colors cursor-pointer text-left"
      >
        <svg className="w-4 h-4 text-[#CCCCCC]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
        </svg>
        <span>Rename</span>
      </button>

      {/* Thin Divider */}
      <div className="h-px bg-[#484848] my-1 mx-2" />

      {/* Pin chat / Unpin chat */}
      <button
        type="button"
        onClick={() => {
          onTogglePin();
          onClose();
        }}
        className="w-full flex items-center gap-3 px-3 py-2 text-[14px] text-[#F5F5F5] font-normal rounded-[10px] hover:bg-[#454545] transition-colors cursor-pointer text-left"
      >
        <svg className="w-4 h-4 text-[#CCCCCC]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <line x1="12" y1="17" x2="12" y2="22" />
          <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a1 1 0 0 0 0-2H8a1 1 0 0 0 0 2h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z" />
        </svg>
        <span>{isPinned ? 'Unpin chat' : 'Pin chat'}</span>
      </button>

      {/* Archive */}
      <button
        type="button"
        onClick={() => {
          onArchive();
          onClose();
        }}
        className="w-full flex items-center gap-3 px-3 py-2 text-[14px] text-[#F5F5F5] font-normal rounded-[10px] hover:bg-[#454545] transition-colors cursor-pointer text-left"
      >
        <svg className="w-4 h-4 text-[#CCCCCC]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <rect width="20" height="18" x="2" y="3" rx="4" />
          <path d="M9 10h6" />
        </svg>
        <span>Archive</span>
      </button>

      {/* Delete */}
      <button
        type="button"
        onClick={() => {
          onDelete();
          onClose();
        }}
        className="w-full flex items-center gap-3 px-3 py-2 text-[14px] text-[#FF4242] font-normal rounded-[10px] hover:bg-[#454545] transition-colors cursor-pointer text-left"
      >
        <svg className="w-4 h-4 text-[#FF4242]" viewBox="0 0 24 24" fill="none" stroke="#FF4242" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 6h18" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          <line x1="10" y1="11" x2="10" y2="17" />
          <line x1="14" y1="11" x2="14" y2="17" />
        </svg>
        <span>Delete</span>
      </button>
    </div>
  );
};
