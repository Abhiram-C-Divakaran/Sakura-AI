import React from 'react';

export interface AttachmentItem {
  id: string;
  filename: string;
  size?: number;
  mime_type?: string;
  status: 'Uploading' | 'Processing' | 'Ready' | 'Failed';
  error?: string;
  file?: File;
  content?: string;
}

export type ActiveMode = 'create_image' | 'web_search' | 'deep_research' | 'analyze' | 'visualize' | 'code_workspace';

interface AttachmentChipsProps {
  activeModes: ActiveMode[];
  onRemoveMode: (mode: ActiveMode) => void;
  attachments: AttachmentItem[];
  onRemoveAttachment: (id: string) => void;
  editingImage?: { id?: string; filename?: string; url?: string; prompt?: string } | null;
  onClearEditingImage?: () => void;
}

export const AttachmentChips: React.FC<AttachmentChipsProps> = ({
  activeModes,
  onRemoveMode,
  attachments,
  onRemoveAttachment,
  editingImage,
  onClearEditingImage
}) => {
  if (activeModes.length === 0 && attachments.length === 0 && !editingImage) {
    return null;
  }

  const getModeDetails = (mode: ActiveMode) => {
    switch (mode) {
      case 'create_image':
        return { label: 'Create image', symbol: '✦', color: 'bg-[#2D1B36] text-[#E98297] border-[#5E2B68]' };
      case 'web_search':
        return { label: 'Web search', symbol: '◎', color: 'bg-[#182A3A] text-[#4A8EFF] border-[#254C70]' };
      case 'deep_research':
        return { label: 'Deep research', symbol: '◆', color: 'bg-[#2A2415] text-[#FFB340] border-[#664E1C]' };
      case 'analyze':
        return { label: 'Analyze', symbol: '◇', color: 'bg-[#1C2C26] text-[#35D0BA] border-[#2A5445]' };
      case 'visualize':
        return { label: 'Visualize', symbol: '⌘', color: 'bg-[#221A33] text-[#9880ED] border-[#443068]' };
      case 'code_workspace':
        return { label: 'Code workspace', symbol: '<>', color: 'bg-[#1F2228] text-[#70A5FF] border-[#36435C]' };
      default:
        return { label: mode, symbol: '•', color: 'bg-[#222222] text-[#F5F5F5] border-[#333333]' };
    }
  };

  const getStatusBadge = (status: AttachmentItem['status']) => {
    switch (status) {
      case 'Uploading':
        return <span className="text-[10px] text-[#FFB340] animate-pulse">Uploading…</span>;
      case 'Processing':
        return <span className="text-[10px] text-[#9880ED] animate-pulse">Processing…</span>;
      case 'Ready':
        return <span className="text-[10px] text-[#35D0BA]">Ready</span>;
      case 'Failed':
        return <span className="text-[10px] text-[#FF453A]">Failed</span>;
    }
  };

  return (
    <div className="flex flex-wrap gap-2 px-1 pb-2.5 pt-0.5">
      {/* Active Mode Chips */}
      {activeModes.map((mode) => {
        const details = getModeDetails(mode);
        return (
          <div
            key={mode}
            className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[12px] font-medium border transition-all ${details.color}`}
          >
            <span className="font-mono text-[11px]">{details.symbol}</span>
            <span>{details.label}</span>
            <button
              type="button"
              onClick={() => onRemoveMode(mode)}
              className="ml-1 text-[13px] opacity-70 hover:opacity-100 hover:text-white transition-opacity cursor-pointer leading-none"
              title={`Remove ${details.label} mode`}
            >
              ✕
            </button>
          </div>
        );
      })}

      {/* Editing Image Chip */}
      {editingImage && (
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[12px] bg-[#2A1828] border border-[#E98297]/50 text-[#F5F5F5] animate-in fade-in">
          <span className="text-[#E98297]">✏️</span>
          <span className="font-medium text-[#E98297]">Editing image</span>
          {editingImage.prompt && (
            <span className="max-w-[130px] truncate text-[#B8B8B8] text-[11px]">"{editingImage.prompt}"</span>
          )}
          <button
            type="button"
            onClick={onClearEditingImage}
            className="ml-1 text-[13px] opacity-70 hover:opacity-100 hover:text-white transition-opacity cursor-pointer leading-none"
            title="Cancel image edit"
          >
            ✕
          </button>
        </div>
      )}

      {/* File Attachment Chips */}
      {attachments.map((att) => (
        <div
          key={att.id}
          className={`inline-flex items-center gap-2 px-3 py-1 rounded-full text-[12px] bg-[#1E1E1E] border ${
            att.status === 'Failed'
              ? 'border-[#FF453A]/50 text-[#FF8585]'
              : 'border-[#333333] text-[#F5F5F5]'
          }`}
        >
          <svg className="w-3.5 h-3.5 text-[#888888]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <span className="max-w-[150px] truncate font-medium">{att.filename}</span>
          {getStatusBadge(att.status)}
          <button
            type="button"
            onClick={() => onRemoveAttachment(att.id)}
            className="ml-0.5 text-[12px] text-[#888888] hover:text-white transition-colors cursor-pointer"
            title={`Remove ${att.filename}`}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
};
