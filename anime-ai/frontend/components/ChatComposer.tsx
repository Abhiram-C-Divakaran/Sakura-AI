import React, { useState, useEffect, useRef } from 'react';
import { PlusMenu } from './PlusMenu';
import { IntensityDropdown, IntensityLevel } from './IntensityDropdown';
import { VoiceRecorder, VoiceRecorderHandle } from './VoiceRecorder';
import { FileLibraryModal, LibraryDocument } from './FileLibraryModal';
import { ConnectAppsModal } from './ConnectAppsModal';
import { AttachmentChips, AttachmentItem, ActiveMode } from './AttachmentChips';
import { authFetch } from '../lib/auth';
import { API_BASE } from '../lib/api';

export interface ChatSubmitPayload {
  message: string;
  intensity: IntensityLevel;
  tools: string[];
  attachments: {
    id?: string;
    filename: string;
    mime_type?: string;
    content?: string;
  }[];
  active_workspace_id?: string | null;
}

interface ChatComposerProps {
  onSendMessage: (payload: ChatSubmitPayload) => void;
  onStopGeneration?: () => void;
  isGenerating?: boolean;
  documents?: LibraryDocument[];
  onRefreshDocuments?: () => void;
  apiBase?: string;
  placeholder?: string;
  externalAttachment?: any;
  onClearExternalAttachment?: () => void;
  editingImage?: { id?: string; filename?: string; url?: string; prompt?: string } | null;
  onClearEditingImage?: () => void;
  prefilledText?: string | null;
  onClearPrefilledText?: () => void;
}

export const ChatComposer: React.FC<ChatComposerProps> = ({
  onSendMessage,
  onStopGeneration,
  isGenerating = false,
  documents = [],
  onRefreshDocuments,
  apiBase = API_BASE,
  placeholder = 'Ask Sakura AI',
  externalAttachment = null,
  onClearExternalAttachment,
  editingImage = null,
  onClearEditingImage,
  prefilledText = null,
  onClearPrefilledText
}) => {
  const [inputText, setInputText] = useState('');
  const [intensity, setIntensity] = useState<IntensityLevel>('medium');
  const [activeModes, setActiveModes] = useState<ActiveMode[]>([]);
  const [attachments, setAttachments] = useState<AttachmentItem[]>([]);
  const [isPlusMenuOpen, setIsPlusMenuOpen] = useState(false);
  const [isLibraryOpen, setIsLibraryOpen] = useState(false);
  const [isConnectAppsOpen, setIsConnectAppsOpen] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerContainerRef = useRef<HTMLDivElement>(null);
  const voiceRecorderRef = useRef<VoiceRecorderHandle>(null);

  // Sync external attachment (e.g. from Library "Attach to chat")
  useEffect(() => {
    if (externalAttachment) {
      setAttachments((prev) => {
        if (prev.some((a) => a.id === externalAttachment.id)) return prev;
        return [
          ...prev,
          {
            id: externalAttachment.id,
            filename: externalAttachment.name || externalAttachment.filename,
            size: externalAttachment.size_bytes || externalAttachment.size,
            mime_type: externalAttachment.mime_type,
            status: 'Ready'
          }
        ];
      });
      if (onClearExternalAttachment) onClearExternalAttachment();
    }
  }, [externalAttachment, onClearExternalAttachment]);

  // Sync prefilled text (e.g. from Edit Prompt on failed image generation)
  useEffect(() => {
    if (prefilledText) {
      setInputText(prefilledText);
      setTimeout(() => {
        if (textareaRef.current) {
          textareaRef.current.focus();
          textareaRef.current.selectionStart = textareaRef.current.value.length;
          textareaRef.current.selectionEnd = textareaRef.current.value.length;
        }
      }, 50);
      onClearPrefilledText?.();
    }
  }, [prefilledText, onClearPrefilledText]);

  // Load saved intensity from localStorage
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('sakura_composer_intensity');
      if (saved && ['low', 'medium', 'high'].includes(saved)) {
        setIntensity(saved as IntensityLevel);
      }
    }
  }, []);

  // Save intensity to localStorage
  const handleIntensityChange = (level: IntensityLevel) => {
    setIntensity(level);
    if (typeof window !== 'undefined') {
      localStorage.setItem('sakura_composer_intensity', level);
    }
  };

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [inputText]);

  // Plus menu action triggers
  const handleTriggerUpload = () => {
    fileInputRef.current?.click();
  };

  const handleOpenLibrary = () => {
    if (onRefreshDocuments) onRefreshDocuments();
    setIsLibraryOpen(true);
  };

  const handleToggleMode = (mode: ActiveMode) => {
    setActiveModes((prev) =>
      prev.includes(mode) ? prev.filter((m) => m !== mode) : [...prev, mode]
    );
    // Focus textarea after adding mode
    setTimeout(() => textareaRef.current?.focus(), 50);
  };

  const handleRemoveMode = (mode: ActiveMode) => {
    setActiveModes((prev) => prev.filter((m) => m !== mode));
  };

  // Handle direct file uploads (via native file picker or drag-and-drop)
  const handleFilesSelected = async (files: FileList | File[]) => {
    const fileArray = Array.from(files);
    if (fileArray.length === 0) return;

    for (const file of fileArray) {
      const tempId = `file-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      const newAttachment: AttachmentItem = {
        id: tempId,
        filename: file.name,
        size: file.size,
        mime_type: file.type || 'text/plain',
        status: 'Uploading',
        file: file
      };

      setAttachments((prev) => [...prev, newAttachment]);

      // Read text preview for small/code/text/csv files
      if (file.size < 1024 * 1024) {
        const reader = new FileReader();
        reader.onload = (e) => {
          const content = e.target?.result as string;
          setAttachments((prev) =>
            prev.map((a) => (a.id === tempId ? { ...a, content } : a))
          );
        };
        reader.readAsText(file);
      }

      // Upload to backend API
      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await authFetch(`${apiBase}/api/v1/documents/upload`, {
          method: 'POST',
          body: formData
        });

        if (res.ok) {
          const data = await res.json();
          setAttachments((prev) =>
            prev.map((a) =>
              a.id === tempId
                ? {
                    ...a,
                    id: data.document_id || tempId,
                    status: 'Ready'
                  }
                : a
            )
          );
          if (onRefreshDocuments) onRefreshDocuments();
        } else {
          setAttachments((prev) =>
            prev.map((a) =>
              a.id === tempId
                ? {
                    ...a,
                    status: 'Failed',
                    error: 'Upload rejected by server'
                  }
                : a
            )
          );
        }
      } catch (err: any) {
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === tempId
              ? {
                  ...a,
                  status: 'Failed',
                  error: err.message || 'Network error'
                }
              : a
          )
        );
      }
    }
  };

  const handleRemoveAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const handleAttachFromLibrary = (doc: LibraryDocument) => {
    const isAlreadyAttached = attachments.some((a) => a.id === doc.id);
    if (!isAlreadyAttached) {
      setAttachments((prev) => [
        ...prev,
        {
          id: doc.id,
          filename: doc.filename,
          size: doc.metadata?.size,
          mime_type: doc.mime_type,
          status: 'Ready'
        }
      ]);
    }
  };

  // Drag and Drop handlers
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!composerContainerRef.current?.contains(e.relatedTarget as Node)) {
      setIsDragOver(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFilesSelected(e.dataTransfer.files);
    }
  };

  // Speech-to-text insertion
  const handleVoiceTranscription = (transcribedText: string) => {
    setInputText((prev) => {
      const trimmed = prev.trim();
      return trimmed ? `${trimmed} ${transcribedText}` : transcribedText;
    });
    setTimeout(() => {
      textareaRef.current?.focus();
    }, 50);
  };

  // Send message
  const handleSend = () => {
    const trimmed = inputText.trim();
    if ((!trimmed && attachments.length === 0 && !editingImage) || isGenerating) return;

    const finalAttachments = [...attachments];
    if (editingImage && editingImage.id && !finalAttachments.some(a => a.id === editingImage.id)) {
      finalAttachments.unshift({
        id: editingImage.id,
        filename: editingImage.filename || 'reference_image.png',
        mime_type: 'image/png',
        status: 'Ready'
      });
    }

    const payload: ChatSubmitPayload = {
      message: trimmed || (editingImage ? 'Modify image' : activeModes.includes('create_image') ? 'Generate image' : 'Analyze attached files'),
      intensity: intensity,
      tools: editingImage ? [...Array.from(new Set([...activeModes, 'edit_image' as ActiveMode]))] : activeModes,
      attachments: finalAttachments.map((a) => ({
        id: a.id,
        filename: a.filename,
        mime_type: a.mime_type,
        content: a.content
      }))
    };

    onSendMessage(payload);
    setInputText('');
    setAttachments([]);
    setActiveModes([]);
    if (onClearEditingImage) onClearEditingImage();
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend = inputText.trim().length > 0 || attachments.length > 0 || !!editingImage;

  return (
    <div
      ref={composerContainerRef}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="relative w-full max-w-[860px] mx-auto px-4"
      style={{ width: 'min(90%, 860px)' }}
    >
      {/* Hidden File Input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.txt,.md,.markdown,.csv,.json,.py,.js,.ts,.tsx,.jsx,.html,.css,.rs,.go,.cpp,.c,.java,.png,.jpg,.jpeg,.webp"
        onChange={(e) => {
          if (e.target.files) handleFilesSelected(e.target.files);
          e.target.value = '';
        }}
        className="hidden"
        aria-hidden="true"
      />

      {/* Floating Plus Menu */}
      <PlusMenu
        isOpen={isPlusMenuOpen}
        onClose={() => setIsPlusMenuOpen(false)}
        onSelectUpload={handleTriggerUpload}
        onSelectLibrary={handleOpenLibrary}
        onToggleMode={handleToggleMode}
        onOpenConnectApps={() => setIsConnectAppsOpen(true)}
        activeModes={activeModes}
      />

      {/* Modals */}
      <FileLibraryModal
        isOpen={isLibraryOpen}
        onClose={() => setIsLibraryOpen(false)}
        documents={documents}
        onSelectDocument={handleAttachFromLibrary}
        attachedDocIds={attachments.map((a) => a.id)}
      />

      <ConnectAppsModal
        isOpen={isConnectAppsOpen}
        onClose={() => setIsConnectAppsOpen(false)}
      />

      {/* Main Canonical Composer Pill Container */}
      <div
        className={`rounded-[30px] px-3.5 py-2 transition-all duration-200 border flex flex-col justify-center min-h-[58px] bg-theme-composer-inner ${
          isDragOver
            ? 'border-theme-accent ring-2 ring-theme-accent/30'
            : 'border-theme-border hover:border-theme-border-card focus-within:border-theme-border-card'
        }`}
        style={{
          boxShadow: 'none',
        }}
      >
        {/* Chips Area (Modes, Editing Image & Attachments) */}
        <AttachmentChips
          activeModes={activeModes}
          onRemoveMode={handleRemoveMode}
          attachments={attachments}
          onRemoveAttachment={handleRemoveAttachment}
          editingImage={editingImage}
          onClearEditingImage={onClearEditingImage}
        />

        {/* Canonical Input Row */}
        <div className="flex items-center gap-2 relative">
          {/* Left + Button */}
          <button
            type="button"
            onClick={() => setIsPlusMenuOpen(!isPlusMenuOpen)}
            aria-label="Add files and tools"
            aria-expanded={isPlusMenuOpen}
            className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors flex-shrink-0 cursor-pointer text-theme-text hover:bg-theme-hover active:bg-theme-active ${
              isPlusMenuOpen ? 'bg-theme-active text-theme-text rotate-45' : ''
            }`}
            title="Add files and tools"
          >
            <svg
              className="w-5 h-5 transition-transform"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>

          {/* Center Auto-resizing Text Input */}
          <div className="flex-1 min-w-0 py-1 px-1 flex items-center">
            <textarea
              ref={textareaRef}
              rows={1}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={editingImage ? 'Describe what you want to change...' : placeholder}
              aria-label="Ask Sakura AI message prompt"
              className="w-full bg-transparent text-[16px] leading-[1.5] text-theme-text placeholder:text-theme-muted focus:outline-none resize-none max-h-[190px] overflow-y-auto font-sans"
              style={{
                fontFamily: 'Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
              }}
            />
          </div>

          {/* Right Action Controls */}
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {/* Intensity Selector Dropdown */}
            <IntensityDropdown
              value={intensity}
              onChange={handleIntensityChange}
              disabled={isGenerating}
            />

            {/* Voice Input Microphone Button */}
            <VoiceRecorder
              ref={voiceRecorderRef}
              onTranscriptionComplete={handleVoiceTranscription}
              apiBase={apiBase}
            />

            {/* Primary Action Button (Waveform / Send / Stop) */}
            {isGenerating ? (
              <button
                type="button"
                onClick={onStopGeneration}
                aria-label="Stop response generation"
                title="Stop generation"
                className="w-10 h-10 rounded-full bg-[#2F95F6] hover:bg-[#2580D8] text-white flex items-center justify-center transition-transform active:scale-95 cursor-pointer shadow-sm flex-shrink-0"
              >
                <div className="w-3.5 h-3.5 bg-white rounded-xs" />
              </button>
            ) : canSend ? (
              <button
                type="button"
                onClick={handleSend}
                aria-label="Send message"
                title="Send message (Enter)"
                className="w-10 h-10 rounded-full bg-[#2F95F6] hover:bg-[#2580D8] text-white flex items-center justify-center transition-all active:scale-95 cursor-pointer shadow-sm flex-shrink-0"
              >
                <svg
                  className="w-5 h-5 text-white"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="12" y1="19" x2="12" y2="5" />
                  <polyline points="5 12 12 5 19 12" />
                </svg>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => voiceRecorderRef.current?.startRecording()}
                aria-label="Voice mode"
                title="Start voice mode"
                className="w-10 h-10 rounded-full bg-[#2F95F6] hover:bg-[#2580D8] text-white flex items-center justify-center transition-all active:scale-95 cursor-pointer shadow-sm flex-shrink-0"
              >
                <svg
                  className="w-[18px] h-[18px] text-white"
                  viewBox="0 0 24 24"
                  fill="currentColor"
                >
                  <rect x="3.5" y="8" width="2.5" height="8" rx="1.25" />
                  <rect x="9" y="4" width="2.5" height="16" rx="1.25" />
                  <rect x="14.5" y="6" width="2.5" height="12" rx="1.25" />
                  <rect x="20" y="9" width="2.5" height="6" rx="1.25" />
                </svg>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Subdued Footer Note */}
      <p className="text-[12px] text-[#666666] text-center mt-2.5 select-none font-sans">
        Sakura AI can make mistakes. Verify important information.
      </p>
    </div>
  );
};
