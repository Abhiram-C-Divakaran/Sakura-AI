import React, { useState } from 'react';

export interface LibraryDocument {
  id: string;
  filename: string;
  mime_type?: string;
  created_at?: string;
  metadata?: {
    size?: number;
    indexing_status?: string;
    chunks?: number;
    error?: string;
  };
}

interface FileLibraryModalProps {
  isOpen: boolean;
  onClose: () => void;
  documents: LibraryDocument[];
  onSelectDocument: (doc: LibraryDocument) => void;
  attachedDocIds: string[];
}

export const FileLibraryModal: React.FC<FileLibraryModalProps> = ({
  isOpen,
  onClose,
  documents,
  onSelectDocument,
  attachedDocIds
}) => {
  const [searchQuery, setSearchQuery] = useState('');

  if (!isOpen) return null;

  const filteredDocs = documents.filter((doc) =>
    doc.filename.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const formatBytes = (bytes?: number) => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const getFileIcon = (filename: string) => {
    const ext = filename.split('.').pop()?.toLowerCase();
    if (['png', 'jpg', 'jpeg', 'webp', 'svg', 'gif'].includes(ext || '')) {
      return (
        <svg className="w-4 h-4 text-[#E98297]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect width="18" height="18" x="3" y="3" rx="2" />
          <circle cx="9" cy="9" r="2" />
          <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
        </svg>
      );
    }
    if (['csv', 'xlsx', 'xls', 'json'].includes(ext || '')) {
      return (
        <svg className="w-4 h-4 text-[#35D0BA]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 3v18h18" />
          <path d="m19 9-5 5-4-4-3 3" />
        </svg>
      );
    }
    if (['py', 'js', 'ts', 'tsx', 'jsx', 'html', 'css', 'rs', 'go', 'cpp'].includes(ext || '')) {
      return (
        <svg className="w-4 h-4 text-[#9880ED]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="16 18 22 12 16 6" />
          <polyline points="8 6 2 12 8 18" />
        </svg>
      );
    }
    return (
      <svg className="w-4 h-4 text-[#4A8EFF]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
        <polyline points="14 2 14 8 20 8" />
      </svg>
    );
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="library-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div className="bg-[#1C1C1C] border border-[#333333] rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        {/* Modal Header */}
        <div className="p-4 border-b border-[#2C2C2C] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#2A2A2A] flex items-center justify-center text-[#F5F5F5]">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
                <path d="M6 6h10" />
                <path d="M6 10h10" />
              </svg>
            </div>
            <div>
              <h3 id="library-modal-title" className="text-[15px] font-semibold text-white">
                Sakura File Library
              </h3>
              <p className="text-[11.5px] text-[#888888]">
                Select indexed documents & datasets to attach to the conversation
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-[#888888] hover:text-white hover:bg-[#2A2A2A] rounded-lg transition-colors cursor-pointer"
            aria-label="Close library modal"
          >
            ✕
          </button>
        </div>

        {/* Search Filter */}
        <div className="p-3 border-b border-[#282828] bg-[#161616]">
          <div className="flex items-center gap-2 bg-[#222222] border border-[#333333] rounded-xl px-3 py-1.5">
            <svg className="w-4 h-4 text-[#777777]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search library files..."
              className="flex-1 bg-transparent text-[13px] text-[#F5F5F5] placeholder:text-[#666666] focus:outline-none"
            />
          </div>
        </div>

        {/* Documents List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-1.5 min-h-[220px]">
          {filteredDocs.length === 0 ? (
            <div className="py-12 text-center text-[13px] text-[#777777] flex flex-col items-center gap-2">
              <svg className="w-8 h-8 text-[#444444]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
              </svg>
              <span>No documents found in your library.</span>
            </div>
          ) : (
            filteredDocs.map((doc) => {
              const isAttached = attachedDocIds.includes(doc.id);
              const status = doc.metadata?.indexing_status || 'Ready';

              return (
                <div
                  key={doc.id}
                  className="flex items-center justify-between p-2.5 bg-[#222222] hover:bg-[#2A2A2A] border border-[#2E2E2E] rounded-xl transition-colors"
                >
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <div className="w-8 h-8 rounded-lg bg-[#181818] border border-[#333333] flex items-center justify-center flex-shrink-0">
                      {getFileIcon(doc.filename)}
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="text-[13px] font-medium text-[#F5F5F5] truncate">
                        {doc.filename}
                      </span>
                      <div className="flex items-center gap-2 text-[11px] text-[#777777] font-mono">
                        <span>{formatBytes(doc.metadata?.size)}</span>
                        <span>•</span>
                        <span>{status}</span>
                      </div>
                    </div>
                  </div>

                  <button
                    type="button"
                    disabled={isAttached}
                    onClick={() => {
                      onSelectDocument(doc);
                      onClose();
                    }}
                    className={`px-3 py-1 text-[12px] font-medium rounded-lg transition-colors cursor-pointer ${
                      isAttached
                        ? 'bg-[#2A2A2A] text-[#666666] cursor-not-allowed'
                        : 'bg-[#35D0BA] text-black hover:bg-[#2EB8A4]'
                    }`}
                  >
                    {isAttached ? 'Attached' : 'Attach'}
                  </button>
                </div>
              );
            })
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-3 bg-[#161616] border-t border-[#282828] flex items-center justify-between text-[11.5px] text-[#888888]">
          <span>{documents.length} files in Sakura storage</span>
          <button
            onClick={onClose}
            className="px-3 py-1 text-[#CCCCCC] hover:text-white hover:bg-[#2A2A2A] rounded-lg transition-colors cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
