import React, { useState, useRef, useEffect } from 'react';

interface IntroVideoProps {
  onFinish?: () => void;
}

export const IntroVideo: React.FC<IntroVideoProps> = ({ onFinish }) => {
  const [isVisible, setIsVisible] = useState(true);
  const [isFading, setIsFading] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [progress, setProgress] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);

  const handleDismiss = () => {
    if (isFading) return;
    setIsFading(true);
    setTimeout(() => {
      setIsVisible(false);
      if (onFinish) onFinish();
    }, 650);
  };

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    // Attempt autoplay with audio; if blocked by browser policy, fallback to muted autoplay
    const playPromise = video.play();
    if (playPromise !== undefined) {
      playPromise.catch(() => {
        video.muted = true;
        setIsMuted(true);
        video.play().catch(() => {});
      });
    }

    // Keyboard shortcut to skip intro
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        handleDismiss();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const toggleMute = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!videoRef.current) return;
    const nextMute = !videoRef.current.muted;
    videoRef.current.muted = nextMute;
    setIsMuted(nextMute);
  };

  const handleTimeUpdate = () => {
    if (!videoRef.current) return;
    const { currentTime, duration } = videoRef.current;
    if (duration > 0) {
      setProgress((currentTime / duration) * 100);
    }
  };

  if (!isVisible) return null;

  return (
    <div
      onClick={handleDismiss}
      className={`fixed inset-0 z-[99999] bg-[#000000] flex items-center justify-center cursor-pointer transition-opacity duration-700 ease-out select-none ${
        isFading ? 'opacity-0 pointer-events-none' : 'opacity-100'
      }`}
    >
      {/* Pitch black background guard */}
      <div className="absolute inset-0 bg-[#000000] pointer-events-none" />

      {/* Intro Video Element */}
      <div className="relative w-full h-full flex items-center justify-center p-4 sm:p-8">
        <video
          ref={videoRef}
          src="/intro/sakura_intro.mp4"
          playsInline
          autoPlay
          onTimeUpdate={handleTimeUpdate}
          onEnded={handleDismiss}
          className="w-full h-full object-contain max-w-[1400px] max-h-[850px] shadow-[0_0_50px_rgba(255,42,133,0.15)] pointer-events-none"
        />
      </div>

      {/* Top Bar Controls */}
      <div className="absolute top-6 left-6 right-6 flex items-center justify-between pointer-events-auto z-20">
        {/* Sound Toggle */}
        <button
          type="button"
          onClick={toggleMute}
          className="flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-black/60 hover:bg-black/80 border border-white/15 hover:border-white/30 text-[12px] font-medium text-white/80 hover:text-white backdrop-blur-md transition-all shadow-md cursor-pointer"
        >
          <span>{isMuted ? '🔇' : '🔊'}</span>
          <span>{isMuted ? 'Unmute' : 'Sound On'}</span>
        </button>

        {/* Skip Intro Button */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            handleDismiss();
          }}
          className="group flex items-center gap-2 px-4 py-1.5 rounded-full bg-black/60 hover:bg-black/80 border border-white/15 hover:border-[#FF2A85]/60 text-[12px] font-semibold tracking-wider text-white/90 hover:text-white uppercase backdrop-blur-md transition-all shadow-md cursor-pointer"
        >
          <span>Skip Intro</span>
          <span className="text-[#FF2A85] transition-transform duration-300 group-hover:translate-x-1">→</span>
        </button>
      </div>

      {/* Bottom Hint */}
      <div className="absolute bottom-5 left-1/2 -translate-x-1/2 text-[11px] text-[#6E7681] pointer-events-none tracking-wider uppercase font-medium">
        Press anywhere or Esc to skip
      </div>

      {/* Glowing Neon Progress Bar */}
      <div className="absolute bottom-0 left-0 right-0 h-[2.5px] bg-white/[0.05] pointer-events-none">
        <div
          className="h-full bg-gradient-to-r from-[#FF2A85] via-[#45D4F3] to-[#FF2A85] shadow-[0_0_10px_#FF2A85] transition-all duration-100 ease-linear"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
};
