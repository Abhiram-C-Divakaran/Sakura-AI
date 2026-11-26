import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { SakuraLogo } from '../SakuraLogo';

export const LandingNavbar: React.FC = () => {
  const [scrolled, setScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const navLinks = [
    { label: 'Product', href: '/#capabilities' },
    { label: 'Sakura Code', href: '/#sakura-code' },
    { label: 'Images', href: '/#images' },
    { label: 'Library', href: '/#library' },
    { label: 'How It Works', href: '/#how-it-works' },
  ];

  return (
    <header
      className={`landing-nav fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-[#030304]/90 backdrop-blur-md border-b border-white/[0.08]'
          : 'bg-transparent border-b border-transparent'
      }`}
    >
      <div className="max-w-[1440px] mx-auto px-6 sm:px-10 lg:px-12 h-[74px] flex items-center justify-between">
        {/* Left: Brand Logo & Name */}
        <Link href="/" className="flex items-center gap-3 group cursor-pointer select-none">
          <SakuraLogo
            size={30}
            alt="Sakura AI"
            className="transition-transform duration-300 group-hover:scale-105 drop-shadow-[0_0_12px_rgba(255,95,143,0.4)]"
          />
          <span className="font-bold text-[18px] sm:text-[19px] tracking-[-0.02em] text-[#F7F7F8] font-display">
            Sakura AI
          </span>
        </Link>

        {/* Center: Desktop Navigation */}
        <nav className="hidden lg:flex items-center gap-7 lg:gap-9" aria-label="Main Navigation">
          {navLinks.map((link) => (
            <Link
              key={link.label}
              href={link.href}
              className="text-[14px] font-medium text-[#A3A3AB] hover:text-[#F7F7F8] transition-colors py-1 focus:outline-none focus-visible:text-white"
            >
              {link.label}
            </Link>
          ))}
        </nav>

        {/* Right: Sign in only (no Get Started button in navbar) */}
        <div className="hidden lg:flex items-center">
          <Link
            href="/login"
            className="text-[14px] font-medium text-[#E5E5EA] hover:text-white transition-colors px-3 py-2 rounded-full border border-white/[0.12] hover:border-[#FF5F8F]/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#FF5F8F]"
          >
            Sign in
          </Link>
        </div>

        {/* Mobile menu button */}
        <div className="flex lg:hidden items-center gap-3">
          <Link
            href="/login"
            className="text-[13px] font-medium text-[#E5E5EA] hover:text-white px-2.5 py-1.5 rounded-full border border-white/[0.12]"
          >
            Sign in
          </Link>
          <button
            type="button"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle mobile menu"
            aria-expanded={mobileMenuOpen}
            aria-controls="landing-mobile-menu"
            onKeyDown={(event) => {
              if (event.key === 'Escape') setMobileMenuOpen(false);
            }}
            className="p-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-[#F7F7F8] hover:bg-white/[0.08] transition-colors"
          >
            {mobileMenuOpen ? (
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div
          id="landing-mobile-menu"
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setMobileMenuOpen(false);
              document.querySelector<HTMLButtonElement>('[aria-controls="landing-mobile-menu"]')?.focus();
            }
          }}
          className="lg:hidden bg-[#08080B]/98 backdrop-blur-xl border-b border-white/[0.08] px-6 py-6 space-y-4"
        >
          <div className="flex flex-col space-y-3">
            {navLinks.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                onClick={() => setMobileMenuOpen(false)}
                className="text-[15px] font-medium text-[#A3A3AB] hover:text-white transition-colors py-1"
              >
                {link.label}
              </Link>
            ))}
          </div>

          <div className="pt-4 border-t border-white/[0.08]">
            <Link
              href="/login"
              onClick={() => setMobileMenuOpen(false)}
              className="block w-full text-center py-3 rounded-full text-[14px] font-medium text-white border border-white/[0.16] hover:border-[#FF5F8F]/60 transition-all"
            >
              Sign in
            </Link>
          </div>
        </div>
      )}
    </header>
  );
};
