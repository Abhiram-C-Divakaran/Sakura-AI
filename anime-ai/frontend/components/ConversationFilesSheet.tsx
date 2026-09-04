import React, { useState, useEffect } from 'react';
import { X, Download, Eye, Paperclip, FileText, Image as ImageIcon, Code, FileSpreadsheet, Film } from 'lucide-react';
import { authFetch } from '../lib/auth';

export interface ConversationFile {
  id: string;
  conversation_id: string;
  name: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  thumbnail?: string;
  url?: string;
  source: 'uploaded' | 'generated';
  created_at?: string;
}

interface ConversationFilesSheetProps {
  isOpen: boolean;
  onClose: () => void;
  conversationId: string | null;
  conversationTitle?: string;
  onAttachToChat?: (file: any) => void;
  apiBase?: string;
}

export const ConversationFilesSheet: React.FC<ConversationFilesSheetProps> = ({
  isOpen,
  onClose,
  conversationId,
  conversationTitle = 'Chat',
  onAttachToChat,
  apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
}) => {
  const [files, setFiles] = useState<ConversationFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewImage, setPreviewImage] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !conversationId) {
      setFiles([]);
      return;
    }

    const fetchFiles = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await authFetch(`${apiBase}/api/v1/conversations/${conversationId}/files`);

        if (res.ok) {
          const data = await res.json();
          setFiles(data);
        } else {
          setError('Could not load files for this chat.');
        }
      } catch (err: any) {
        console.error('Failed to fetch conversation files:', err);
        setError('Network error while loading files.');
      } finally {
        setLoading(false);
      }
    };

    fetchFiles();
  }, [isOpen, conversationId, apiBase]);

  // Handle ESC key to close
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (previewImage) {
          setPreviewImage(null);
        } else {
          onClose();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, previewImage, onClose]);

  if (!isOpen) return null;

  const formatBytes = (bytes: number) => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const formatDate = (isoStr?: string) => {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  };

  const getFileIcon = (mimeType: string = '', filename: string = '') => {
    if (mimeType.startsWith('image/')) return <ImageIcon className="w-5 h-5 text-[#35D0BA]" />;
    if (mimeType.startsWith('video/')) return <Film className="w-5 h-5 text-[#9880ED]" />;
    if (mimeType.includes('pdf')) return <FileText className="w-5 h-5 text-[#FF5A5A]" />;
    if (mimeType.includes('csv') || mimeType.includes('sheet') || filename.endsWith('.csv')) return <FileSpreadsheet className="w-5 h-5 text-[#4CD964]" />;
    if (mimeType.includes('json') || filename.endsWith('.py') || filename.endsWith('.js') || filename.endsWith('.ts')) return <Code className="w-5 h-5 text-[#5AC8FA]" />;
    return <FileText className="w-5 h-5 text-[#8E8E8E]" />;
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        onClick={onClose}
        className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity duration-200"
      />

      {/* Slide-over Drawer */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Files in this chat"
        className="relative w-full max-w-[420px] bg-[#1C1C1C] border-l border-[#2E2E2E] shadow-2xl flex flex-col h-full z-10 animate-in slide-in-from-right duration-200"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#282828] flex-shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <h2 className="text-[16px] font-semibold text-white tracking-tight">Files in this chat</h2>
            <span className="text-[12px] bg-[#2A2A2A] text-[#8E8E8E] font-medium px-2 py-0.5 rounded-full">
              {files.length}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 text-[#8E8E8E] hover:text-white hover:bg-[#2A2A2A] rounded-lg transition-colors cursor-pointer"
            aria-label="Close panel"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-2 sidebar-scroll">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-20 text-[#8E8E8E] gap-2">
              <div className="w-6 h-6 border-2 border-[#35D0BA] border-t-transparent rounded-full animate-spin" />
              <span className="text-[13px]">Loading files...</span>
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center py-20 text-[#FF5A5A] text-center px-4">
              <span className="text-[13px]">{error}</span>
            </div>
          ) : files.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-24 text-center px-6 text-[#777777]">
              <div className="w-12 h-12 rounded-full bg-[#242424] flex items-center justify-center mb-3">
                <FileText className="w-6 h-6 text-[#555555]" />
              </div>
              <h3 className="text-[15px] font-medium text-[#D0D0D0] mb-1">No files in this chat</h3>
              <p className="text-[13px] leading-relaxed">
                Photos, documents, datasets, or images generated in this conversation will be listed here.
              </p>
            </div>
          ) : (
            files.map((file) => (
              <div
                key={file.id}
                className="group flex items-center justify-between p-2.5 rounded-xl bg-[#242424] hover:bg-[#2A2A2A] border border-[#2E2E2E] hover:border-[#383838] transition-all"
              >
                <div className="flex items-center gap-3 min-w-0 flex-1">
                  {/* Thumbnail / Icon */}
                  {file.thumbnail ? (
                    <div
                      onClick={() => setPreviewImage(file.url || file.thumbnail || null)}
                      className="w-10 h-10 rounded-lg overflow-hidden bg-black flex-shrink-0 cursor-pointer border border-white/[0.08]"
                    >
                      <img src={file.thumbnail} alt={file.name} className="w-full h-full object-cover" />
                    </div>
                  ) : (
                    <div className="w-10 h-10 rounded-lg bg-[#181818] flex items-center justify-center flex-shrink-0 border border-white/[0.05]">
                      {getFileIcon(file.mime_type, file.filename)}
                    </div>
                  )}

                  {/* File Info */}
                  <div className="flex flex-col min-w-0 flex-1">
                    <span className="text-[13.5px] font-medium text-[#EDEDED] truncate" title={file.name}>
                      {file.name}
                    </span>
                    <div className="flex items-center gap-2 text-[11.5px] text-[#7A7A7A]">
                      <span>{formatBytes(file.size_bytes)}</span>
                      {file.created_at && (
                        <>
                          <span>•</span>
                          <span>{formatDate(file.created_at)}</span>
                        </>
                      )}
                      <span className="capitalize text-[10.5px] bg-[#181818] px-1.5 py-0.2 rounded text-[#8E8E8E]">
                        {file.source}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition-opacity ml-2 flex-shrink-0">
                  {file.thumbnail && (
                    <button
                      type="button"
                      onClick={() => setPreviewImage(file.url || file.thumbnail || null)}
                      title="Preview image"
                      className="p-1.5 text-[#8E8E8E] hover:text-white hover:bg-[#333333] rounded-lg transition-colors cursor-pointer"
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                  )}

                  {file.url && (
                    <a
                      href={file.url}
                      download={file.filename}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Download file"
                      className="p-1.5 text-[#8E8E8E] hover:text-white hover:bg-[#333333] rounded-lg transition-colors cursor-pointer"
                    >
                      <Download className="w-4 h-4" />
                    </a>
                  )}

                  {onAttachToChat && (
                    <button
                      type="button"
                      onClick={() => {
                        onAttachToChat(file);
                        onClose();
                      }}
                      title="Attach again to composer"
                      className="p-1.5 text-[#8E8E8E] hover:text-white hover:bg-[#333333] rounded-lg transition-colors cursor-pointer"
                    >
                      <Paperclip className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Lightweight Fullscreen Image Preview */}
      {previewImage && (
        <div
          onClick={() => setPreviewImage(null)}
          className="fixed inset-0 z-60 bg-black/80 flex items-center justify-center p-4 cursor-zoom-out animate-in fade-in duration-150"
        >
          <img
            src={previewImage}
            alt="Preview"
            className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-2xl border border-white/10"
          />
        </div>
      )}
    </div>
  );
};
