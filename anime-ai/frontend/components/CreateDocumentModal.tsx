import React, { useState } from 'react';

interface CreateDocumentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (filename: string, content: string, category: string) => Promise<void>;
}

export const CreateDocumentModal: React.FC<CreateDocumentModalProps> = ({
  isOpen,
  onClose,
  onCreate
}) => {
  const [filename, setFilename] = useState('');
  const [content, setContent] = useState('');
  const [docType, setDocType] = useState<'md' | 'py' | 'json' | 'txt' | 'csv'>('md');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    let finalName = filename.trim();
    if (!finalName) {
      setError('Please provide a file name.');
      return;
    }

    if (!finalName.includes('.')) {
      finalName = `${finalName}.${docType}`;
    }

    const category = docType === 'py' || docType === 'json' ? 'code' : (docType === 'csv' ? 'data' : 'documents');

    setSaving(true);
    try {
      await onCreate(finalName, content, category);
      setFilename('');
      setContent('');
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to create document');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div className="bg-[#1C1C1C] border border-[#333333] rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-[#2C2C2C] flex items-center justify-between bg-[#161616]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#2A2A2A] flex items-center justify-center text-[#35D0BA]">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            </div>
            <div>
              <h3 className="text-[15px] font-semibold text-white">Create New Document</h3>
              <p className="text-[11.5px] text-[#888888]">
                Write or paste text, markdown, code, or datasets into your library
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-[#888888] hover:text-white hover:bg-[#2A2A2A] rounded-lg transition-colors cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {error && (
            <div className="p-2.5 bg-[#2A1515] border border-[#5C2323] text-[#FF8585] text-[12px] rounded-lg">
              {error}
            </div>
          )}

          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="block text-[11px] font-mono text-[#888888] uppercase mb-1">
                File Name
              </label>
              <input
                type="text"
                value={filename}
                onChange={(e) => setFilename(e.target.value)}
                placeholder="e.g. system_architecture"
                className="w-full bg-[#222222] border border-[#333333] rounded-xl px-3 py-2 text-[13.5px] text-white placeholder:text-[#666666] focus:outline-none focus:border-[#35D0BA]"
                autoFocus
              />
            </div>

            <div>
              <label className="block text-[11px] font-mono text-[#888888] uppercase mb-1">
                Format
              </label>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value as any)}
                className="w-full bg-[#222222] border border-[#333333] rounded-xl px-3 py-2 text-[13.5px] text-white focus:outline-none focus:border-[#35D0BA]"
              >
                <option value="md">Markdown (.md)</option>
                <option value="txt">Plain Text (.txt)</option>
                <option value="py">Python (.py)</option>
                <option value="json">JSON (.json)</option>
                <option value="csv">CSV (.csv)</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-[#888888] uppercase mb-1">
              File Content
            </label>
            <textarea
              rows={8}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Type or paste document content here..."
              className="w-full bg-[#222222] border border-[#333333] rounded-xl p-3 text-[13px] text-white font-mono placeholder:text-[#666666] focus:outline-none focus:border-[#35D0BA] resize-none"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#2A2A2A]">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-[12.5px] text-[#CCCCCC] hover:text-white hover:bg-[#2A2A2A] rounded-lg transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-1.5 text-[12.5px] font-semibold text-black bg-[#35D0BA] hover:bg-[#2EB8A4] rounded-lg transition-colors cursor-pointer disabled:opacity-50"
            >
              {saving ? 'Creating…' : 'Create & Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
