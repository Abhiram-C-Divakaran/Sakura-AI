import React from 'react';
import Image from 'next/image';

export const HeroArtwork: React.FC = () => {
  return (
    <div className="relative w-full max-w-[620px] lg:max-w-[700px] xl:max-w-[760px] mx-auto flex items-center justify-center select-none">

      {/* Main Image Container with Soft Edge Masking */}
      <div className="relative w-full aspect-[3/4] max-h-[580px] sm:max-h-[680px] lg:max-h-[760px] overflow-hidden z-10">
        {/* Soft edge gradient masks that fade into #050507 */}
        <div className="absolute inset-0 z-10 pointer-events-none bg-gradient-to-t from-[#050507] via-transparent to-transparent opacity-95 h-32 bottom-0 top-auto" />
        <div className="absolute inset-0 z-10 pointer-events-none bg-gradient-to-r from-[#050507] via-transparent to-transparent opacity-90 w-28 left-0 right-auto" />
        <div className="absolute inset-0 z-10 pointer-events-none bg-gradient-to-l from-[#050507] via-transparent to-transparent opacity-60 w-20 right-0 left-auto" />
        <div className="absolute inset-0 z-10 pointer-events-none bg-gradient-to-b from-[#050507]/40 via-transparent to-transparent h-16 top-0" />

        <Image
          src="/branding/sakura_landing_hero.jpg"
          alt="Sakura AI Character Portrait"
          fill
          priority
          sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 720px"
          className="object-cover object-center scale-[1.02] transition-transform duration-1000 ease-out hover:scale-[1.04]"
        />
      </div>

      {/* Right-Edge Editorial Text Accent */}
      <div
        aria-hidden="true"
        className="hidden lg:block absolute -bottom-2 -right-4 z-20 text-[10px] tracking-[0.28em] text-[#6F6F78] uppercase select-none font-mono text-right"
      >
        <div className="flex items-center justify-end gap-2 text-[#A5A5AD]/80">
          <span>A BRIGHTER</span>
          <span className="w-5 h-[1px] bg-[#6F6F78]/50 inline-block" />
        </div>
        <div className="flex items-center justify-end gap-2 text-[#6F6F78]">
          <span>CREATIVE TOMORROW</span>
          <span className="w-8 h-[1px] bg-[#6F6F78]/30 inline-block" />
        </div>
      </div>
    </div>
  );
};
