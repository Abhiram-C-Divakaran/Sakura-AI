import React, { useState, useEffect } from 'react';
import { Download, X, ZoomIn, ZoomOut, RotateCcw, Info, Sparkles, Copy, Check } from 'lucide-react';

export interface ImageMetadata {
  id?: string;
  prompt?: string;
  enhanced_prompt?: string;
  aspect_ratio?: string;
  width?: number;
  height?: number;
  model?: string;
  seed?: number;
  workflow?: string;
  parent_image_id?: string;
  lineage_depth?: number;
  url?: string;
  filename?: string;
  created_at?: string;
}

interface ImageLightboxModalProps {
  isOpen: boolean;
  onClose: () => void;
  imageUrl: string;
  altText?: string;
  metadata?: ImageMetadata | null;
  onEdit?: (meta: ImageMetadata) => void;
  onVariation?: (meta: ImageMetadata) => void;
  onUpscale?: (meta: ImageMetadata) => void;
}

export const ImageLightboxModal: React.FC<ImageLightboxModalProps> = ({
  isOpen,
  onClose,
  imageUrl,
  altText = 'Generated Image',
  metadata,
  onEdit,
  onVariation,
  onUpscale
}) => {
  const [zoom, setZoom] = useState(1);
  const [showInfo, setShowInfo] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === '+' || e.key === '=') setZoom(z => Math.min(z + 0.25, 3));
      if (e.key === '-') setZoom(z => Math.max(z - 0.25, 0.5));
      if (e.key === '0') setZoom(1);
    };
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.body.style.overflow = '';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleCopyLink = () => {
    const fullUrl = imageUrl.startsWith('http') ? imageUrl : window.location.origin + imageUrl;
    navigator.clipboard.writeText(fullUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const a = document.createElement('a');
    a.href = imageUrl;
    a.download = metadata?.filename || altText || 'sakura-creation.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/95 backdrop-blur-xl animate-in fade-in duration-200 select-none">
      {/* Top Bar */}
      <div className="absolute top-0 inset-x-0 h-16 flex items-center justify-between px-6 z-10 bg-gradient-to-b from-black/80 to-transparent">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-[#181818] border border-[#2E2E2E] flex items-center justify-center text-[#E98297]">
            <Sparkles className="w-4 h-4" />
          </div>
          <div className="flex flex-col">
            <span className="text-[14px] font-medium text-white max-w-[400px] truncate">{metadata?.filename || altText}</span>
            <span className="text-[11px] text-[#888888]">{metadata?.width || 1024} × {metadata?.height || 1024} • {metadata?.model || 'Flux Realism'}</span>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {/* Zoom controls */}
          <div className="flex items-center bg-[#181818] border border-[#2E2E2E] rounded-xl p-1 gap-1">
            <button
              type="button"
              onClick={() => setZoom(z => Math.max(z - 0.25, 0.5))}
              className="p-1.5 rounded-lg text-[#A0A0A0] hover:text-white hover:bg-[#252525] transition-colors"
              title="Zoom out (-)"
            >
              <ZoomOut className="w-4 h-4" />
            </button>
            <span className="text-[11px] font-mono px-2 text-[#CCCCCC]">{Math.round(zoom * 100)}%</span>
            <button
              type="button"
              onClick={() => setZoom(z => Math.min(z + 0.25, 3))}
              className="p-1.5 rounded-lg text-[#A0A0A0] hover:text-white hover:bg-[#252525] transition-colors"
              title="Zoom in (+)"
            >
              <ZoomIn className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => setZoom(1)}
              className="p-1.5 rounded-lg text-[#A0A0A0] hover:text-white hover:bg-[#252525] transition-colors"
              title="Reset zoom (0)"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>

          <button
            type="button"
            onClick={handleCopyLink}
            className="flex items-center gap-1.5 px-3 py-2 bg-[#181818] hover:bg-[#252525] border border-[#2E2E2E] rounded-xl text-[12.5px] text-[#D0D0D0] hover:text-white transition-colors"
          >
            {copied ? <Check className="w-4 h-4 text-[#35D0BA]" /> : <Copy className="w-4 h-4" />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>

          <button
            type="button"
            onClick={handleDownload}
            className="flex items-center gap-1.5 px-3 py-2 bg-[#181818] hover:bg-[#252525] border border-[#2E2E2E] rounded-xl text-[12.5px] text-[#D0D0D0] hover:text-white transition-colors"
          >
            <Download className="w-4 h-4" />
            <span>Download</span>
          </button>

          <button
            type="button"
            onClick={() => setShowInfo(prev => !prev)}
            className={`p-2 rounded-xl border transition-colors ${
              showInfo
                ? 'bg-[#2E182A] border-[#E98297]/40 text-[#E98297]'
                : 'bg-[#181818] border-[#2E2E2E] text-[#A0A0A0] hover:text-white hover:bg-[#252525]'
            }`}
            title="Toggle Metadata Inspector"
          >
            <Info className="w-4 h-4" />
          </button>

          <button
            type="button"
            onClick={onClose}
            className="p-2 bg-[#181818] hover:bg-[#252525] border border-[#2E2E2E] rounded-xl text-[#A0A0A0] hover:text-white transition-colors ml-2"
            title="Close (Esc)"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Main Image Stage */}
      <div className="relative flex-1 h-full flex items-center justify-center overflow-hidden p-8">
        <div
          className="transition-transform duration-150 ease-out flex items-center justify-center max-w-full max-h-full"
          style={{ transform: `scale(${zoom})` }}
        >
          <img
            src={imageUrl}
            alt={altText}
            className="max-h-[85vh] max-w-[85vw] object-contain rounded-xl shadow-2xl border border-[#222222]"
            draggable={false}
          />
        </div>
      </div>

      {/* Side Metadata Inspector Drawer */}
      {showInfo && (
        <div className="w-[340px] h-full bg-[#111111] border-l border-[#222222] p-6 flex flex-col gap-5 overflow-y-auto z-20 animate-in slide-in-from-right duration-200">
          <div className="flex items-center justify-between pb-3 border-b border-[#222222]">
            <h3 className="text-[14px] font-semibold text-white">Generation Inspector</h3>
            <button
              onClick={() => setShowInfo(false)}
              className="text-[#888888] hover:text-white p-1 rounded-lg"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Prompt */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-mono uppercase tracking-wider text-[#777777]">User Prompt</span>
            <p className="text-[13px] text-[#EDEDED] bg-[#181818] p-3 rounded-xl border border-[#242424] leading-relaxed">
              {metadata?.prompt || altText}
            </p>
          </div>

          {/* Enhanced Prompt */}
          {metadata?.enhanced_prompt && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-mono uppercase tracking-wider text-[#777777]">Enhanced Art Direction</span>
              <p className="text-[12px] text-[#B0B0B0] bg-[#181818] p-3 rounded-xl border border-[#242424] leading-relaxed font-mono">
                {metadata.enhanced_prompt}
              </p>
            </div>
          )}

          {/* Specs Grid */}
          <div className="grid grid-cols-2 gap-2.5">
            <div className="p-3 bg-[#181818] rounded-xl border border-[#242424] flex flex-col">
              <span className="text-[10px] text-[#777777] uppercase font-mono">Aspect Ratio</span>
              <span className="text-[13px] text-white font-medium mt-0.5">{metadata?.aspect_ratio || '1:1'}</span>
            </div>
            <div className="p-3 bg-[#181818] rounded-xl border border-[#242424] flex flex-col">
              <span className="text-[10px] text-[#777777] uppercase font-mono">Resolution</span>
              <span className="text-[13px] text-white font-medium mt-0.5">{metadata?.width || 1024} × {metadata?.height || 1024}</span>
            </div>
            <div className="p-3 bg-[#181818] rounded-xl border border-[#242424] flex flex-col">
              <span className="text-[10px] text-[#777777] uppercase font-mono">Seed</span>
              <span className="text-[13px] text-white font-medium mt-0.5 font-mono">{metadata?.seed || '42'}</span>
            </div>
            <div className="p-3 bg-[#181818] rounded-xl border border-[#242424] flex flex-col">
              <span className="text-[10px] text-[#777777] uppercase font-mono">Model</span>
              <span className="text-[13px] text-white font-medium mt-0.5">{metadata?.model || 'Flux'}</span>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="flex flex-col gap-2 mt-auto pt-4 border-t border-[#222222]">
            {onEdit && (
              <button
                type="button"
                onClick={() => {
                  if (metadata) onEdit(metadata);
                  onClose();
                }}
                className="w-full py-2.5 bg-[#212121] hover:bg-[#2A2A2A] text-white rounded-xl text-[13px] font-medium transition-colors border border-[#333333] flex items-center justify-center gap-2"
              >
                <span>✏️ Edit this image in chat</span>
              </button>
            )}
            {onVariation && (
              <button
                type="button"
                onClick={() => {
                  if (metadata) onVariation(metadata);
                  onClose();
                }}
                className="w-full py-2.5 bg-[#212121] hover:bg-[#2A2A2A] text-white rounded-xl text-[13px] font-medium transition-colors border border-[#333333] flex items-center justify-center gap-2"
              >
                <span>🔀 Create variations</span>
              </button>
            )}
            {onUpscale && (
              <button
                type="button"
                onClick={() => {
                  if (metadata) onUpscale(metadata);
                  onClose();
                }}
                className="w-full py-2.5 bg-[#212121] hover:bg-[#2A2A2A] text-white rounded-xl text-[13px] font-medium transition-colors border border-[#333333] flex items-center justify-center gap-2"
              >
                <span>🔍 Upscale 2×</span>
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
