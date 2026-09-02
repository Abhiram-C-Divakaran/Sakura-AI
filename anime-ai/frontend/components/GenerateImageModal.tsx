import React, { useState } from 'react';
import { SakuraLogo } from './SakuraLogo';

interface GenerateImageModalProps {
  isOpen: boolean;
  onClose: () => void;
  onGenerate: (prompt: string, filename?: string) => Promise<void>;
}

export const GenerateImageModal: React.FC<GenerateImageModalProps> = ({
  isOpen,
  onClose,
  onGenerate
}) => {
  const [prompt, setPrompt] = useState('');
  const [filename, setFilename] = useState('');
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) {
      setError('Please provide an image prompt.');
      return;
    }

    setGenerating(true);
    setError(null);
    try {
      await onGenerate(prompt.trim(), filename.trim() ? filename.trim() : undefined);
      setPrompt('');
      setFilename('');
      onClose();
    } catch (err: any) {
      setError(err.message || 'Image generation failed');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div className="bg-[#1C1C1C] border border-[#333333] rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-[#2C2C2C] flex items-center justify-between bg-[#161616]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-black border border-[#2A2A2A] flex items-center justify-center overflow-hidden">
              <SakuraLogo size={22} alt="" />
            </div>
            <div>
              <h3 className="text-[15px] font-semibold text-white">Generate Image to Library</h3>
              <p className="text-[11.5px] text-[#888888]">
                Create new artwork with Sakura AI and store it in your Library
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

          <div>
            <label className="block text-[11px] font-mono text-[#888888] uppercase mb-1">
              Visual Prompt
            </label>
            <textarea
              rows={3}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. Futuristic Neo-Tokyo subway station in rain at midnight, cyberpunk neon glow..."
              className="w-full bg-[#222222] border border-[#333333] rounded-xl p-3 text-[13px] text-white placeholder:text-[#666666] focus:outline-none focus:border-[#E98297] resize-none"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-[11px] font-mono text-[#888888] uppercase mb-1">
              File Name (Optional)
            </label>
            <input
              type="text"
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
              placeholder="e.g. neo_tokyo_station.png"
              className="w-full bg-[#222222] border border-[#333333] rounded-xl px-3 py-2 text-[13px] text-white placeholder:text-[#666666] focus:outline-none focus:border-[#E98297]"
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
              disabled={generating}
              className="px-4 py-1.5 text-[12.5px] font-semibold text-black bg-[#E98297] hover:bg-[#D46C82] rounded-lg transition-colors cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
            >
              {generating && (
                <SakuraLogo size={14} className="animate-pulse" alt="" />
              )}
              <span>{generating ? 'Creating image...' : 'Generate & Save'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
