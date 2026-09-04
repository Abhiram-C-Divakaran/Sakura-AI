import React, { useState, useEffect } from 'react';
import { authFetch } from '../lib/auth';

export interface LibraryFile {
  id: string;
  name: string;
  filename: string;
  mime_type: string;
  category: string;
  source: string;
  status: string;
  size_bytes: number;
  size: number;
  is_knowledge_base: boolean;
  chunks: number;
  created_at: string;
  modified_at: string;
  error?: string;
  metadata?: any;
}

interface FilePreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  file: LibraryFile | null;
  onAttachToChat: (file: LibraryFile) => void;
  onToggleKnowledgeBase: (file: LibraryFile) => void;
  onDeleteFile: (file: LibraryFile) => void;
  onRenameFile: (file: LibraryFile, newName: string) => void;
  apiBase?: string;
}

export const FilePreviewModal: React.FC<FilePreviewModalProps> = ({
  isOpen,
  onClose,
  file,
  onAttachToChat,
  onToggleKnowledgeBase,
  onDeleteFile,
  onRenameFile,
  apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
}) => {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [isEditingName, setIsEditingName] = useState(false);
  const [editName, setEditName] = useState('');

  useEffect(() => {
    if (!isOpen || !file) {
      setContent(null);
      setIsEditingName(false);
      return;
    }

    setEditName(file.name);

    if (file.category === 'code' || file.category === 'documents' || file.category === 'data') {
      fetchFileContent(file.id);
    }
  }, [isOpen, file]);

  const fetchFileContent = async (fileId: string) => {
    setLoading(true);
    try {
      const res = await authFetch(`${apiBase}/api/v1/library/files/${fileId}/content`);
      if (res.ok) {
        const data = await res.json();
        setContent(data.content);
      }
    } catch (e) {
      console.error('Failed to load file preview content:', e);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen || !file) return null;

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const handleSaveRename = () => {
    if (editName.trim() && editName.trim() !== file.name) {
      onRenameFile(file, editName.trim());
    }
    setIsEditingName(false);
  };

  const renderContentBody = () => {
    if (loading) {
      return (
        <div className="flex flex-col items-center justify-center h-72 gap-3 text-[#888888]">
          <svg className="w-6 h-6 animate-spin text-[#35D0BA]" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          <span className="text-[13px]">Loading file content...</span>
        </div>
      );
    }

    // Image preview
    if (file.category === 'images') {
      const imgUrl = `${apiBase}/api/v1/library/files/${file.id}/download`;
      return (
        <div className="flex flex-col items-center justify-center p-6 bg-[#080808] rounded-xl overflow-hidden min-h-[300px] border border-[#222222]">
          <img
            src={imgUrl}
            alt={file.name}
            className="max-h-[500px] max-w-full object-contain rounded-lg shadow-2xl"
          />
        </div>
      );
    }

    // CSV / Table preview
    if (file.mime_type === 'text/csv' || file.name.endsWith('.csv')) {
      if (!content) {
        return <div className="text-center py-12 text-[#777777]">Empty CSV dataset</div>;
      }
      const lines = content.trim().split('\n');
      const header = lines[0]?.split(',').map((c) => c.trim()) || [];
      const rows = lines.slice(1, 40).map((l) => l.split(',').map((c) => c.trim()));

      return (
        <div className="overflow-x-auto rounded-xl border border-[#262626] bg-[#0E0E0E]">
          <table className="w-full text-left text-[12.5px] font-mono">
            <thead className="bg-[#181818] border-b border-[#262626] text-white">
              <tr>
                {header.map((col, idx) => (
                  <th key={idx} className="px-3 py-2 font-medium">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1A1A1A]">
              {rows.map((r, ri) => (
                <tr key={ri} className="hover:bg-[#141414]">
                  {r.map((c, ci) => (
                    <td key={ci} className="px-3 py-1.5 text-[#CCCCCC]">
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {lines.length > 40 && (
            <div className="p-2 text-center text-[11px] text-[#666666] border-t border-[#222222] bg-[#121212]">
              Showing first 40 rows of {lines.length} total rows
            </div>
          )}
        </div>
      );
    }

    // Code & Text preview
    if (content !== null) {
      return (
        <div className="bg-[#0A0A0A] rounded-xl border border-[#262626] overflow-hidden">
          <div className="px-3 py-1.5 bg-[#141414] border-b border-[#222222] text-[11px] font-mono text-[#888888] flex justify-between">
            <span>{file.mime_type}</span>
            <span>{content.length} characters</span>
          </div>
          <pre className="p-4 text-[13px] text-[#E0E0E0] font-mono leading-relaxed overflow-x-auto max-h-[460px] whitespace-pre-wrap">
            <code>{content}</code>
          </pre>
        </div>
      );
    }

    // Default metadata viewer (e.g. PDF or binary)
    return (
      <div className="p-8 bg-[#0D0D0D] border border-[#222222] rounded-xl flex flex-col items-center justify-center text-center gap-3">
        <svg className="w-12 h-12 text-[#4A8EFF]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
        <span className="text-[14px] font-medium text-white">{file.name}</span>
        <span className="text-[12px] text-[#888888] font-mono">
          {file.mime_type} • {formatBytes(file.size_bytes)}
        </span>
        <p className="text-[12px] text-[#666666] max-w-sm">
          Binary document preview. You can attach this file directly to Sakura AI conversations or download it.
        </p>
      </div>
    );
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="preview-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-md animate-in fade-in duration-150"
    >
      <div className="bg-[#181818] border border-[#333333] rounded-2xl w-full max-w-3xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="p-4 border-b border-[#282828] flex items-center justify-between bg-[#141414]">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <div className="w-9 h-9 rounded-xl bg-[#222222] border border-[#333333] flex items-center justify-center text-[#F5F5F5] flex-shrink-0">
              {file.category === 'images' ? (
                <svg className="w-5 h-5 text-[#E98297]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect width="18" height="18" x="3" y="3" rx="2" />
                  <circle cx="9" cy="9" r="2" />
                  <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
                </svg>
              ) : file.category === 'code' ? (
                <svg className="w-5 h-5 text-[#9880ED]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="16 18 22 12 16 6" />
                  <polyline points="8 6 2 12 8 18" />
                </svg>
              ) : file.category === 'data' ? (
                <svg className="w-5 h-5 text-[#35D0BA]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 3v18h18" />
                  <path d="m19 9-5 5-4-4-3 3" />
                </svg>
              ) : (
                <svg className="w-5 h-5 text-[#4A8EFF]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
              )}
            </div>

            <div className="flex flex-col min-w-0 flex-1">
              {isEditingName ? (
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleSaveRename();
                      if (e.key === 'Escape') setIsEditingName(false);
                    }}
                    autoFocus
                    className="bg-[#242424] text-white text-[14px] px-2 py-0.5 rounded border border-[#444444] focus:outline-none focus:border-[#35D0BA]"
                  />
                  <button
                    onClick={handleSaveRename}
                    className="text-[11px] text-[#35D0BA] font-semibold hover:underline"
                  >
                    Save
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <h3 id="preview-modal-title" className="text-[15px] font-semibold text-white truncate">
                    {file.name}
                  </h3>
                  <button
                    onClick={() => setIsEditingName(true)}
                    className="text-[#777777] hover:text-white p-0.5 rounded transition-colors"
                    title="Rename file"
                  >
                    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                    </svg>
                  </button>
                </div>
              )}
              <div className="flex items-center gap-2 text-[11px] text-[#888888] font-mono mt-0.5">
                <span>{formatBytes(file.size_bytes)}</span>
                <span>•</span>
                <span>{file.category}</span>
                <span>•</span>
                <span>{file.is_knowledge_base ? 'Indexed for AI' : 'Not indexed'}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="p-1.5 text-[#888888] hover:text-white hover:bg-[#2A2A2A] rounded-lg transition-colors cursor-pointer"
              aria-label="Close preview modal"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-4">{renderContentBody()}</div>

        {/* Action Footer */}
        <div className="p-3 bg-[#141414] border-t border-[#282828] flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <button
              onClick={() => onToggleKnowledgeBase(file)}
              className={`px-3 py-1.5 text-[12px] font-medium rounded-lg transition-colors cursor-pointer border ${
                file.is_knowledge_base
                  ? 'bg-[#1C2C26] text-[#35D0BA] border-[#35D0BA]/30 hover:bg-[#243B33]'
                  : 'bg-[#222222] text-[#CCCCCC] border-[#333333] hover:bg-[#2C2C2C]'
              }`}
            >
              {file.is_knowledge_base ? '✓ Indexed in AI Memory' : '+ Add to AI Memory'}
            </button>

            <a
              href={`${apiBase}/api/v1/library/files/${file.id}/download`}
              download={file.name}
              className="px-3 py-1.5 text-[12px] font-medium rounded-lg transition-colors cursor-pointer bg-[#222222] text-[#CCCCCC] hover:bg-[#2C2C2C] border border-[#333333] flex items-center gap-1.5"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" x2="12" y1="15" y2="3" />
              </svg>
              <span>Download</span>
            </a>

            <button
              onClick={() => onDeleteFile(file)}
              className="px-3 py-1.5 text-[12px] font-medium rounded-lg transition-colors cursor-pointer bg-[#261515] text-[#FF6B6B] hover:bg-[#381B1B] border border-[#522222]"
            >
              Delete
            </button>
          </div>

          <button
            onClick={() => {
              onAttachToChat(file);
              onClose();
            }}
            className="px-4 py-1.5 text-[12.5px] font-semibold text-black bg-[#35D0BA] hover:bg-[#2EB8A4] rounded-lg transition-colors cursor-pointer flex items-center gap-1.5 shadow-md"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
            <span>Attach to Chat</span>
          </button>
        </div>
      </div>
    </div>
  );
};
