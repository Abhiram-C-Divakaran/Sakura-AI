import React, { useState, useEffect, useRef, useCallback } from 'react';
import { FilePreviewModal, LibraryFile } from './FilePreviewModal';
import { CreateDocumentModal } from './CreateDocumentModal';
import { GenerateImageModal } from './GenerateImageModal';
import { getAccessToken, authFetch } from '../lib/auth';

interface LibraryViewProps {
  onAttachToChat: (file: LibraryFile) => void;
  onNavigateToChat: () => void;
  apiBase?: string;
}

type CategoryFilter = 'all' | 'images' | 'documents' | 'code' | 'data';
type SortField = 'name' | 'modified' | 'size' | 'type';
type SortOrder = 'asc' | 'desc';
type ViewMode = 'list' | 'grid';

export const LibraryView: React.FC<LibraryViewProps> = ({
  onAttachToChat,
  onNavigateToChat,
  apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
}) => {
  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [category, setCategory] = useState<CategoryFilter>('all');
  const [sortField, setSortField] = useState<SortField>('modified');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [viewMode, setViewMode] = useState<ViewMode>('list');

  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [activeMenuFileId, setActiveMenuFileId] = useState<string | null>(null);
  const [previewFile, setPreviewFile] = useState<LibraryFile | null>(null);

  const [isNewMenuOpen, setIsNewMenuOpen] = useState(false);
  const [isCreateDocOpen, setIsCreateDocOpen] = useState(false);
  const [isGenerateImgOpen, setIsGenerateImgOpen] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ name: string; progress: string } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const newMenuRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Load preferred view mode from localStorage
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('sakura_library_view_mode');
      if (saved === 'grid' || saved === 'list') {
        setViewMode(saved as ViewMode);
      }
    }
  }, []);

  const handleToggleViewMode = (mode: ViewMode) => {
    setViewMode(mode);
    if (typeof window !== 'undefined') {
      localStorage.setItem('sakura_library_view_mode', mode);
    }
  };

  // Debounce search query
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(searchQuery);
    }, 250);
    return () => clearTimeout(handler);
  }, [searchQuery]);

  // Fetch files from real database
  const fetchFiles = useCallback(async () => {
    try {
      const token = getAccessToken();
      if (!token) return;

      const params = new URLSearchParams();
      if (category !== 'all') params.append('category', category);
      if (debouncedSearch.trim()) params.append('q', debouncedSearch.trim());
      params.append('sort_by', sortField);
      params.append('order', sortOrder);

      const res = await authFetch(`${apiBase}/api/v1/library/files?${params.toString()}`);

      if (res.ok) {
        const data = await res.json();
        setFiles(data);
      }
    } catch (e) {
      console.error('Failed to fetch library files:', e);
    } finally {
      setLoading(false);
    }
  }, [apiBase, category, debouncedSearch, sortField, sortOrder]);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  // Connect WebSocket for real-time multi-device sync
  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;

    const wsUrl = apiBase.replace('http', 'ws') + '/api/v1/ws?token=' + token;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'library_update') {
          const { action, data } = msg;
          if (action === 'created') {
            setFiles((prev) => [data, ...prev.filter((f) => f.id !== data.id)]);
          } else if (action === 'updated') {
            setFiles((prev) => prev.map((f) => (f.id === data.id ? { ...f, ...data } : f)));
            setPreviewFile((curr) => (curr && curr.id === data.id ? { ...curr, ...data } : curr));
          } else if (action === 'deleted') {
            setFiles((prev) => prev.filter((f) => f.id !== data.id));
            setPreviewFile((curr) => (curr && curr.id === data.id ? null : curr));
          }
        }
      } catch {}
    };

    return () => {
      try {
        ws.close();
      } catch {}
    };
  }, [apiBase]);

  // Close menus on outside click
  useEffect(() => {
    const handleDocClick = (e: MouseEvent) => {
      if (newMenuRef.current && !newMenuRef.current.contains(e.target as Node)) {
        setIsNewMenuOpen(false);
      }
      setActiveMenuFileId(null);
    };
    document.addEventListener('mousedown', handleDocClick);
    return () => document.removeEventListener('mousedown', handleDocClick);
  }, []);

  // Sort toggle handler
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortOrder('desc');
    }
  };

  // Upload handler
  const handleUploadFiles = async (filesToUpload: FileList | File[]) => {
    const fileList = Array.from(filesToUpload);
    if (fileList.length === 0) return;

    for (const file of fileList) {
      setUploadProgress({ name: file.name, progress: 'Uploading…' });
      const formData = new FormData();
      formData.append('file', file);
      formData.append('auto_index', 'true');

      try {
        const res = await authFetch(`${apiBase}/api/v1/library/upload`, {
          method: 'POST',
          body: formData
        });

        if (res.ok) {
          setUploadProgress({ name: file.name, progress: 'Ready' });
          fetchFiles();
        }
      } catch (err) {
        console.error('File upload error:', err);
      }
    }

    setTimeout(() => setUploadProgress(null), 2000);
  };

  // Drag and Drop
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleUploadFiles(e.dataTransfer.files);
    }
  };

  // Document creation handler
  const handleCreateDocument = async (filename: string, content: string, cat: string) => {
    const res = await authFetch(`${apiBase}/api/v1/library/create-document`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ filename, content, category: cat })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to create file');
    }
    fetchFiles();
  };

  // Image generator handler
  const handleGenerateImage = async (prompt: string, filename?: string) => {
    const res = await authFetch(`${apiBase}/api/v1/library/generate-image`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ prompt, filename })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to generate image');
    }
    fetchFiles();
  };

  // Rename handler
  const handleRename = async (file: LibraryFile, newName: string) => {
    try {
      const res = await authFetch(`${apiBase}/api/v1/library/files/${file.id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name: newName })
      });
      if (res.ok) {
        fetchFiles();
      }
    } catch (e) {
      console.error('Rename failed:', e);
    }
  };

  // Delete handler
  const handleDelete = async (file: LibraryFile) => {
    if (!confirm(`Are you sure you want to permanently delete "${file.name}"?`)) return;
    try {
      const res = await authFetch(`${apiBase}/api/v1/library/files/${file.id}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        setFiles((prev) => prev.filter((f) => f.id !== file.id));
        if (previewFile?.id === file.id) setPreviewFile(null);
      }
    } catch (e) {
      console.error('Delete failed:', e);
    }
  };

  // Toggle Knowledge Base indexing
  const handleToggleKnowledgeBase = async (file: LibraryFile) => {
    const method = file.is_knowledge_base ? 'DELETE' : 'POST';
    try {
      const res = await authFetch(`${apiBase}/api/v1/library/files/${file.id}/index`, {
        method: method
      });
      if (res.ok) {
        fetchFiles();
      }
    } catch (e) {
      console.error('Failed to toggle knowledge base:', e);
    }
  };

  // Format Helpers
  const formatBytes = (bytes?: number) => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const formatRelativeDate = (dateStr: string) => {
    if (!dateStr) return '—';
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffSec = Math.floor(diffMs / 1000);
      const diffMin = Math.floor(diffSec / 60);
      const diffHour = Math.floor(diffMin / 60);
      const diffDay = Math.floor(diffHour / 24);

      if (diffSec < 60) return 'Just now';
      if (diffMin < 60) return `${diffMin}m ago`;
      if (diffHour < 24) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      if (diffDay === 1) return 'Yesterday';
      if (diffDay < 7) return `${diffDay}d ago`;
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } catch {
      return dateStr;
    }
  };

  const getFileIcon = (file: LibraryFile, className = 'w-4 h-4') => {
    if (file.category === 'images') {
      return (
        <svg className={`${className} text-[#E98297]`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect width="18" height="18" x="3" y="3" rx="2" />
          <circle cx="9" cy="9" r="2" />
          <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
        </svg>
      );
    }
    if (file.category === 'code') {
      return (
        <svg className={`${className} text-[#9880ED]`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="16 18 22 12 16 6" />
          <polyline points="8 6 2 12 8 18" />
        </svg>
      );
    }
    if (file.category === 'data') {
      return (
        <svg className={`${className} text-[#35D0BA]`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 3v18h18" />
          <path d="m19 9-5 5-4-4-3 3" />
        </svg>
      );
    }
    return (
      <svg className={`${className} text-[#4A8EFF]`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
        <polyline points="14 2 14 8 20 8" />
      </svg>
    );
  };

  const getCategoryCount = (cat: CategoryFilter) => {
    if (cat === 'all') return files.length;
    return files.filter((f) => f.category === cat).length;
  };

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
      className="flex-1 flex flex-col h-full bg-black text-[#F5F5F5] overflow-hidden select-none"
      style={{ fontFamily: "'Inter', -apple-system, sans-serif" }}
    >
      {/* Hidden File Input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        onChange={(e) => {
          if (e.target.files) handleUploadFiles(e.target.files);
          if (fileInputRef.current) fileInputRef.current.value = '';
        }}
        className="hidden"
      />

      {/* Modals */}
      <FilePreviewModal
        isOpen={!!previewFile}
        onClose={() => setPreviewFile(null)}
        file={previewFile}
        onAttachToChat={(f) => {
          onAttachToChat(f);
          onNavigateToChat();
        }}
        onToggleKnowledgeBase={handleToggleKnowledgeBase}
        onDeleteFile={handleDelete}
        onRenameFile={handleRename}
        apiBase={apiBase}
      />

      <CreateDocumentModal
        isOpen={isCreateDocOpen}
        onClose={() => setIsCreateDocOpen(false)}
        onCreate={handleCreateDocument}
      />

      <GenerateImageModal
        isOpen={isGenerateImgOpen}
        onClose={() => setIsGenerateImgOpen(false)}
        onGenerate={handleGenerateImage}
      />

      {/* ═══ TOP HEADER ═══ */}
      <div className="h-[60px] border-b border-[#1F1F1F] px-8 flex items-center justify-between flex-shrink-0 bg-black">
        <div className="flex items-center gap-3">
          <h1 className="text-[20px] font-semibold text-white tracking-tight">Library</h1>
          <span className="text-[12px] font-mono text-[#666666] bg-[#141414] px-2 py-0.5 rounded-full border border-[#222222]">
            {files.length} {files.length === 1 ? 'file' : 'files'}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Search Bar */}
          <div className="relative flex items-center">
            <svg
              className="w-4 h-4 text-[#777777] absolute left-3 pointer-events-none"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search files..."
              className="w-56 md:w-64 bg-[#141414] border border-[#262626] rounded-xl pl-9 pr-3 py-1.5 text-[13px] text-white placeholder:text-[#666666] focus:outline-none focus:border-[#444444] transition-colors"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 text-[#666666] hover:text-white text-xs"
              >
                ✕
              </button>
            )}
          </div>

          {/* New Button Dropdown */}
          <div className="relative" ref={newMenuRef}>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setIsNewMenuOpen(!isNewMenuOpen)}
              }
              className="flex items-center gap-1.5 px-3.5 py-1.5 bg-white text-black font-medium text-[13px] rounded-xl hover:bg-[#EAEAEA] transition-all cursor-pointer shadow-md"
            >
              <span>New</span>
              <svg
                className={`w-3.5 h-3.5 transition-transform ${isNewMenuOpen ? 'rotate-180' : ''}`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {isNewMenuOpen && (
              <div
                className="absolute right-0 top-full mt-1.5 w-48 bg-[#202020] border border-[#333333] rounded-xl shadow-2xl p-1.5 z-50 animate-in fade-in slide-in-from-top-1 duration-100"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  onClick={() => {
                    fileInputRef.current?.click();
                    setIsNewMenuOpen(false);
                  }}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-[12.5px] text-white hover:bg-[#2C2C2C] rounded-lg transition-colors text-left cursor-pointer"
                >
                  <svg className="w-4 h-4 text-[#4A8EFF]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" x2="12" y1="3" y2="15" />
                  </svg>
                  <span>Upload files</span>
                </button>

                <button
                  onClick={() => {
                    setIsCreateDocOpen(true);
                    setIsNewMenuOpen(false);
                  }}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-[12.5px] text-white hover:bg-[#2C2C2C] rounded-lg transition-colors text-left cursor-pointer"
                >
                  <svg className="w-4 h-4 text-[#35D0BA]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
                    <line x1="12" x2="12" y1="11" y2="17" />
                    <line x1="9" x2="15" y1="14" y2="14" />
                  </svg>
                  <span>Create document</span>
                </button>

                <button
                  onClick={() => {
                    setIsGenerateImgOpen(true);
                    setIsNewMenuOpen(false);
                  }}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-[12.5px] text-white hover:bg-[#2C2C2C] rounded-lg transition-colors text-left cursor-pointer"
                >
                  <svg className="w-4 h-4 text-[#E98297]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect width="18" height="18" x="3" y="3" rx="2" />
                    <circle cx="9" cy="9" r="2" />
                    <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
                  </svg>
                  <span>Generate image</span>
                </button>
              </div>
            )}
          </div>

          {/* List/Grid View Toggle */}
          <div className="flex items-center bg-[#141414] border border-[#262626] rounded-xl p-0.5">
            <button
              onClick={() => handleToggleViewMode('list')}
              className={`p-1.5 rounded-lg transition-colors ${
                viewMode === 'list' ? 'bg-[#282828] text-white' : 'text-[#666666] hover:text-white'
              }`}
              title="List view"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="8" x2="21" y1="6" y2="6" />
                <line x1="8" x2="21" y1="12" y2="12" />
                <line x1="8" x2="21" y1="18" y2="18" />
                <line x1="3" x2="3.01" y1="6" y2="6" />
                <line x1="3" x2="3.01" y1="12" y2="12" />
                <line x1="3" x2="3.01" y1="18" y2="18" />
              </svg>
            </button>
            <button
              onClick={() => handleToggleViewMode('grid')}
              className={`p-1.5 rounded-lg transition-colors ${
                viewMode === 'grid' ? 'bg-[#282828] text-white' : 'text-[#666666] hover:text-white'
              }`}
              title="Grid view"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect width="7" height="7" x="3" y="3" rx="1" />
                <rect width="7" height="7" x="14" y="3" rx="1" />
                <rect width="7" height="7" x="14" y="14" rx="1" />
                <rect width="7" height="7" x="3" y="14" rx="1" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* ═══ FILTER TABS ═══ */}
      <div className="px-8 pt-4 pb-2 flex items-center gap-2 border-b border-[#1A1A1A] bg-black">
        {(['all', 'images', 'documents', 'code', 'data'] as CategoryFilter[]).map((tab) => {
          const isActive = category === tab;
          const count = getCategoryCount(tab);

          return (
            <button
              key={tab}
              onClick={() => setCategory(tab)}
              className={`px-3 py-1.5 text-[13px] font-medium rounded-xl transition-all cursor-pointer capitalize flex items-center gap-1.5 ${
                isActive
                  ? 'bg-[#1F1F1F] text-white shadow-sm'
                  : 'text-[#888888] hover:text-white hover:bg-[#141414]'
              }`}
            >
              <span>{tab}</span>
              {count > 0 && (
                <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono ${isActive ? 'bg-[#333333] text-white' : 'bg-[#181818] text-[#666666]'}`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Upload Progress Banner */}
      {uploadProgress && (
        <div className="mx-8 mt-3 p-3 bg-[#1C2C26] border border-[#35D0BA]/40 rounded-xl flex items-center justify-between text-[12.5px] text-[#35D0BA] animate-in fade-in">
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <span>{uploadProgress.name}</span>
          </div>
          <span className="font-mono text-[11px] font-semibold">{uploadProgress.progress}</span>
        </div>
      )}

      {/* ═══ MAIN WORKSPACE CONTENT ═══ */}
      <div className="flex-1 overflow-y-auto px-8 py-4">
        {loading ? (
          /* Loading Skeletons */
          <div className="space-y-2 py-4">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-12 bg-[#121212] rounded-xl animate-pulse border border-[#1A1A1A]" />
            ))}
          </div>
        ) : files.length === 0 ? (
          /* Empty State (ZERO DUMMY DATA) */
          <div className="flex flex-col items-center justify-center h-[55vh] text-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-[#141414] border border-[#262626] flex items-center justify-center text-[#555555]">
              <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
                <path d="M6 6h10" />
                <path d="M6 10h10" />
              </svg>
            </div>
            <div>
              <h2 className="text-[17px] font-semibold text-white">No files yet</h2>
              <p className="text-[13px] text-[#777777] mt-1 max-w-sm">
                Upload files from your device, or create documents and images with Sakura AI.
              </p>
            </div>
            <div className="flex items-center gap-2 mt-2">
              <button
                onClick={() => fileInputRef.current?.click()}
                className="px-4 py-2 bg-white text-black font-semibold text-[13px] rounded-xl hover:bg-[#EAEAEA] transition-colors cursor-pointer shadow-md"
              >
                Upload a file
              </button>
              <button
                onClick={() => setIsCreateDocOpen(true)}
                className="px-4 py-2 bg-[#1C1C1C] text-white font-medium text-[13px] rounded-xl hover:bg-[#282828] border border-[#333333] transition-colors cursor-pointer"
              >
                Create document
              </button>
            </div>
          </div>
        ) : viewMode === 'list' ? (
          /* ═══ LIST VIEW TABLE ═══ */
          <div className="w-full">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[#1F1F1F] text-[11.5px] font-medium text-[#777777] select-none">
                  <th
                    onClick={() => handleSort('name')}
                    className="pb-3 pl-2 font-medium cursor-pointer hover:text-white transition-colors"
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Name</span>
                      {sortField === 'name' && (
                        <span>{sortOrder === 'asc' ? '↑' : '↓'}</span>
                      )}
                    </div>
                  </th>
                  <th
                    onClick={() => handleSort('modified')}
                    className="pb-3 w-40 font-medium cursor-pointer hover:text-white transition-colors hidden sm:table-cell"
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Modified</span>
                      {sortField === 'modified' && (
                        <span>{sortOrder === 'asc' ? '↑' : '↓'}</span>
                      )}
                    </div>
                  </th>
                  <th
                    onClick={() => handleSort('size')}
                    className="pb-3 w-28 font-medium cursor-pointer hover:text-white transition-colors hidden md:table-cell"
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Size</span>
                      {sortField === 'size' && (
                        <span>{sortOrder === 'asc' ? '↑' : '↓'}</span>
                      )}
                    </div>
                  </th>
                  <th className="pb-3 w-32 font-medium hidden lg:table-cell">AI Status</th>
                  <th className="pb-3 w-12 text-right pr-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#161616]">
                {files.map((file) => {
                  const isSelected = selectedFileId === file.id;
                  const isMenuOpen = activeMenuFileId === file.id;

                  return (
                    <tr
                      key={file.id}
                      onClick={() => setSelectedFileId(file.id)}
                      onDoubleClick={() => setPreviewFile(file)}
                      className={`group hover:bg-[#121212] transition-colors cursor-pointer ${
                        isSelected ? 'bg-[#161616]' : ''
                      }`}
                    >
                      {/* Name + Icon / Thumbnail */}
                      <td className="py-3 pl-2 pr-4">
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="w-8 h-8 rounded-lg bg-[#181818] border border-[#282828] flex items-center justify-center flex-shrink-0 group-hover:border-[#383838] transition-colors overflow-hidden">
                            {file.category === 'images' ? (
                              <img
                                src={`${apiBase}/api/v1/library/files/${file.id}/download`}
                                alt=""
                                className="w-full h-full object-cover"
                                loading="lazy"
                              />
                            ) : (
                              getFileIcon(file, 'w-4 h-4')
                            )}
                          </div>
                          <div className="flex flex-col min-w-0">
                            <span className="text-[13.5px] font-medium text-[#F5F5F5] group-hover:text-white truncate">
                              {file.name}
                            </span>
                            <span className="text-[11px] text-[#666666] sm:hidden">
                              {formatBytes(file.size_bytes)} • {formatRelativeDate(file.modified_at)}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Modified */}
                      <td className="py-3 text-[13px] text-[#888888] font-mono hidden sm:table-cell">
                        {formatRelativeDate(file.modified_at)}
                      </td>

                      {/* Size */}
                      <td className="py-3 text-[13px] text-[#888888] font-mono hidden md:table-cell">
                        {formatBytes(file.size_bytes)}
                      </td>

                      {/* AI Knowledge Status */}
                      <td className="py-3 hidden lg:table-cell">
                        <span
                          className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${
                            file.is_knowledge_base
                              ? 'bg-[#14231E] text-[#35D0BA] border-[#35D0BA]/30'
                              : 'bg-[#181818] text-[#777777] border-[#2A2A2A]'
                          }`}
                        >
                          {file.is_knowledge_base ? 'Ready for AI' : 'Not indexed'}
                        </span>
                      </td>

                      {/* Context Menu Button */}
                      <td className="py-3 text-right pr-2 relative">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setActiveMenuFileId(isMenuOpen ? null : file.id);
                          }}
                          className="p-1 text-[#666666] hover:text-white hover:bg-[#222222] rounded-lg transition-colors cursor-pointer"
                        >
                          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="12" cy="12" r="1" />
                            <circle cx="19" cy="12" r="1" />
                            <circle cx="5" cy="12" r="1" />
                          </svg>
                        </button>

                        {/* Dropdown Menu */}
                        {isMenuOpen && (
                          <div
                            className="absolute right-2 top-full mt-1 w-48 bg-[#202020] border border-[#333333] rounded-xl shadow-2xl p-1.5 z-50 text-left animate-in fade-in duration-100"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <button
                              onClick={() => {
                                setPreviewFile(file);
                                setActiveMenuFileId(null);
                              }}
                              className="w-full px-3 py-1.5 text-[12.5px] text-white hover:bg-[#2C2C2C] rounded-lg transition-colors flex items-center gap-2"
                            >
                              <svg className="w-3.5 h-3.5 text-[#888888]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                                <circle cx="12" cy="12" r="3" />
                              </svg>
                              <span>Preview</span>
                            </button>

                            <button
                              onClick={() => {
                                onAttachToChat(file);
                                onNavigateToChat();
                                setActiveMenuFileId(null);
                              }}
                              className="w-full px-3 py-1.5 text-[12.5px] text-[#35D0BA] hover:bg-[#2C2C2C] rounded-lg transition-colors flex items-center gap-2"
                            >
                              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                              </svg>
                              <span>Attach to chat</span>
                            </button>

                            <button
                              onClick={() => {
                                handleToggleKnowledgeBase(file);
                                setActiveMenuFileId(null);
                              }}
                              className="w-full px-3 py-1.5 text-[12.5px] text-white hover:bg-[#2C2C2C] rounded-lg transition-colors flex items-center gap-2"
                            >
                              <svg className="w-3.5 h-3.5 text-[#9880ED]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <circle cx="12" cy="12" r="10" />
                                <path d="m9 12 2 2 4-4" />
                              </svg>
                              <span>{file.is_knowledge_base ? 'Remove from AI' : 'Add to AI Index'}</span>
                            </button>

                            <a
                              href={`${apiBase}/api/v1/library/files/${file.id}/download`}
                              download={file.name}
                              onClick={() => setActiveMenuFileId(null)}
                              className="w-full px-3 py-1.5 text-[12.5px] text-white hover:bg-[#2C2C2C] rounded-lg transition-colors flex items-center gap-2"
                            >
                              <svg className="w-3.5 h-3.5 text-[#888888]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                <polyline points="7 10 12 15 17 10" />
                                <line x1="12" x2="12" y1="15" y2="3" />
                              </svg>
                              <span>Download</span>
                            </a>

                            <div className="h-px bg-[#303030] my-1" />

                            <button
                              onClick={() => {
                                handleDelete(file);
                                setActiveMenuFileId(null);
                              }}
                              className="w-full px-3 py-1.5 text-[12.5px] text-[#FF5555] hover:bg-[#2E1818] rounded-lg transition-colors flex items-center gap-2"
                            >
                              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M3 6h18" />
                                <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                                <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                              </svg>
                              <span>Delete</span>
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          /* ═══ GRID VIEW ═══ */
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {files.map((file) => (
              <div
                key={file.id}
                onClick={() => setSelectedFileId(file.id)}
                onDoubleClick={() => setPreviewFile(file)}
                className="bg-[#121212] border border-[#222222] hover:border-[#3A3A3A] rounded-2xl p-3.5 flex flex-col justify-between transition-all group cursor-pointer hover:shadow-xl relative"
              >
                {/* Thumbnail / Large Icon */}
                <div className="w-full h-32 rounded-xl bg-[#0A0A0A] border border-[#1E1E1E] flex items-center justify-center overflow-hidden mb-3">
                  {file.category === 'images' ? (
                    <img
                      src={`${apiBase}/api/v1/library/files/${file.id}/download`}
                      alt=""
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      loading="lazy"
                    />
                  ) : (
                    getFileIcon(file, 'w-10 h-10')
                  )}
                </div>

                {/* Metadata */}
                <div className="flex flex-col min-w-0">
                  <div className="flex items-center justify-between gap-1 mb-1">
                    <span className="text-[13.5px] font-medium text-white truncate" title={file.name}>
                      {file.name}
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setPreviewFile(file);
                      }}
                      className="text-[#666666] hover:text-white p-1"
                    >
                      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="1" />
                        <circle cx="19" cy="12" r="1" />
                        <circle cx="5" cy="12" r="1" />
                      </svg>
                    </button>
                  </div>

                  <div className="flex items-center justify-between text-[11px] text-[#777777] font-mono mt-1">
                    <span>{formatBytes(file.size_bytes)}</span>
                    <span>{formatRelativeDate(file.modified_at)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Drag & Drop Visual Overlay */}
      {isDragOver && (
        <div className="absolute inset-0 bg-black/80 backdrop-blur-sm border-2 border-dashed border-[#35D0BA] rounded-3xl m-4 flex flex-col items-center justify-center gap-3 z-50 pointer-events-none animate-in fade-in">
          <div className="w-16 h-16 rounded-2xl bg-[#35D0BA]/10 border border-[#35D0BA]/30 flex items-center justify-center text-[#35D0BA]">
            <svg className="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" x2="12" y1="3" y2="15" />
            </svg>
          </div>
          <span className="text-[16px] font-semibold text-white">Drop files to add to Sakura Library</span>
          <span className="text-[12px] text-[#888888]">Supported: PDF, DOCX, TXT, MD, CSV, JSON, code, images</span>
        </div>
      )}
    </div>
  );
};
