import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
export const DemoModal = ({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) => {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!isOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    const element = dialog.current;
    element?.showModal();
    document.body.style.overflow = 'hidden';
    return () => { element?.close(); document.body.style.overflow = overflow; previous?.focus(); };
  }, [isOpen]);
  if (!isOpen) return null;
  return <dialog ref={dialog} className="landing-demo" aria-labelledby="demo-title" onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="landing-demo-content">
      <div className="flex items-center justify-between gap-4 mb-5"><h2 id="demo-title">Meet Sakura AI</h2><button autoFocus onClick={onClose} aria-label="Close demo" className="landing-close"><X /></button></div>
      <video controls playsInline preload="metadata" aria-label="Sakura brand introduction" src="/intro/sakura_intro.mp4" />
      <p className="mt-4 text-sm text-[#A3A3AB]">A short brand introduction. Explore the illustrated workspace examples on this page to see how Sakura brings your work together.</p>
    </div>
  </dialog>;
};

