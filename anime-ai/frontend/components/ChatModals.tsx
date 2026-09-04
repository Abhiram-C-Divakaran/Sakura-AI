import React, { useState, useEffect } from 'react';

interface ShareModalProps {
  isOpen: boolean;
  onClose: () => void;
  chatTitle: string;
  chatId: string;
  apiBase?: string;
}

export const ShareModal: React.FC<ShareModalProps> = ({ 
  isOpen, 
  onClose, 
  chatTitle, 
  chatId,
  apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
}) => {
  const [copied, setCopied] = useState(false);
  const [shareUrl, setShareUrl] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (!isOpen || !chatId) return;
    const createShare = async () => {
      try {
        setLoading(true);
        const token = typeof window !== 'undefined' ? localStorage.getItem('token') || '' : '';
        const res = await fetch(`${apiBase}/api/v1/conversations/${chatId}/share`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` }
        });
        if (res.ok) {
          const data = await res.json();
          const fullUrl = typeof window !== 'undefined' 
            ? `${window.location.origin}${data.share_url}` 
            : data.share_url;
          setShareUrl(fullUrl);
        } else {
          setShareUrl(typeof window !== 'undefined' ? `${window.location.origin}/share/${chatId}` : `/share/${chatId}`);
        }
      } catch (err) {
        setShareUrl(typeof window !== 'undefined' ? `${window.location.origin}/share/${chatId}` : `/share/${chatId}`);
      } finally {
        setLoading(false);
      }
    };
    createShare();
  }, [isOpen, chatId, apiBase]);

  if (!isOpen) return null;

  const handleCopy = () => {
    if (!shareUrl) return;
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div className="bg-[#242424] border border-[#3A3A3A] rounded-2xl w-full max-w-md shadow-2xl p-5 flex flex-col gap-4 text-white">
        <div className="flex items-center justify-between">
          <h3 className="text-[16px] font-semibold text-white truncate">Share link to chat</h3>
          <button
            onClick={onClose}
            className="p-1 text-[#888888] hover:text-white hover:bg-[#333333] rounded-lg transition-colors cursor-pointer"
          >
            ✕
          </button>
        </div>

        <p className="text-[13px] text-[#A0A0A0] leading-relaxed">
          Messages you send after creating this link will not be shared. Anyone with the link will be able to view this conversation snapshot.
        </p>

        <div className="flex items-center gap-2 bg-[#171717] border border-[#333333] rounded-xl p-1.5 pl-3">
          <input
            type="text"
            readOnly
            value={loading ? 'Generating secure share link...' : shareUrl}
            className="bg-transparent text-[13px] text-[#CCCCCC] w-full focus:outline-none truncate font-mono select-all"
          />
          <button
            onClick={handleCopy}
            disabled={loading}
            className={`px-3.5 py-1.5 rounded-lg text-[12.5px] font-medium transition-colors cursor-pointer flex-shrink-0 disabled:opacity-50 ${
              copied
                ? 'bg-[#35D0BA] text-black font-semibold'
                : 'bg-white text-black hover:bg-[#EAEAEA]'
            }`}
          >
            {copied ? 'Copied!' : 'Copy link'}
          </button>
        </div>
      </div>
    </div>
  );
};

interface DeleteConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  chatTitle: string;
}

export const DeleteConfirmModal: React.FC<DeleteConfirmModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  chatTitle
}) => {
  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div className="bg-[#242424] border border-[#3A3A3A] rounded-2xl w-full max-w-sm shadow-2xl p-5 flex flex-col gap-4 text-white">
        <div className="flex flex-col gap-1">
          <h3 className="text-[16px] font-semibold text-white">Delete chat?</h3>
          <p className="text-[13px] text-[#A0A0A0] leading-relaxed">
            This will permanently delete <span className="text-white font-medium">"{chatTitle}"</span>.
          </p>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#333333]">
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-1.5 text-[13px] text-[#CCCCCC] hover:text-white hover:bg-[#333333] rounded-xl transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              onConfirm();
              onClose();
            }}
            className="px-4 py-1.5 text-[13px] font-medium bg-[#E03838] hover:bg-[#C92A2A] text-white rounded-xl transition-colors cursor-pointer"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
};

interface RenameModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (newTitle: string) => void;
  currentTitle: string;
}

export const RenameModal: React.FC<RenameModalProps> = ({
  isOpen,
  onClose,
  onSave,
  currentTitle
}) => {
  const [title, setTitle] = useState(currentTitle);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (title.trim() && title.trim() !== currentTitle) {
      onSave(title.trim());
    }
    onClose();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div className="bg-[#242424] border border-[#3A3A3A] rounded-2xl w-full max-w-sm shadow-2xl p-5 flex flex-col gap-4 text-white">
        <h3 className="text-[16px] font-semibold text-white">Rename chat</h3>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
            className="w-full bg-[#171717] border border-[#3A3A3A] rounded-xl px-3 py-2 text-[14px] text-white focus:outline-none focus:border-[#4A8EFF]"
          />

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-1.5 text-[13px] text-[#CCCCCC] hover:text-white hover:bg-[#333333] rounded-xl transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-1.5 text-[13px] font-medium bg-white text-black hover:bg-[#EAEAEA] rounded-xl transition-colors cursor-pointer"
            >
              Save
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
