import React, { useState, useEffect } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { SakuraLogo } from '../components/SakuraLogo';
import { IntroVideo } from '../components/IntroVideo';

export default function SakuraLandingPage() {
  const router = useRouter();
  const [showIntro, setShowIntro] = useState(true);
  const [showDemoModal, setShowDemoModal] = useState(false);
  const [activeModel, setActiveModel] = useState('SAKURA PRO');
  const [showModelDropdown, setShowModelDropdown] = useState(false);
  const [activeNav, setActiveNav] = useState('');

  useEffect(() => {
    const handleScroll = () => {
      const scrollY = window.scrollY;
      const vh = window.innerHeight;
      const sections = ['workflows', 'memory', 'features'];
      for (const id of sections) {
        const el = document.getElementById(id);
        if (el) {
          const rect = el.getBoundingClientRect();
          if (rect.top <= vh * 0.45 && rect.bottom >= vh * 0.2) {
            setActiveNav(id);
            return;
          }
        }
      }
      if (scrollY < 200) {
        setActiveNav('');
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);




  return (
    <div className="min-h-screen bg-[#000000] text-[#F4F4F4] overflow-x-hidden select-none font-sans antialiased">
      {/* Cinematic App Intro Video */}
      {showIntro && <IntroVideo onFinish={() => setShowIntro(false)} />}

      <Head>
        <title>SAKURA AI — One Assistant. Every Mode. Limitless Potential.</title>
        <meta
          name="description"
          content="Sakura AI is your all-in-one assistant for chat, coding, research, summarization, image creation, voice, and scheduling—working across text, images, and audio with memory that understands you."
        />
        <link rel="icon" href="/branding/sakura_flower_pink.png" />
      </Head>

      {/* ═══════════════════════════════════════════════════════════════
          TOP NAVIGATION BAR (Fixed with Active Underline Indicator)
          ═══════════════════════════════════════════════════════════════ */}
      <header className="w-full fixed top-0 left-0 right-0 z-50 bg-[#000000]/90 backdrop-blur-xl border-b border-white/[0.08]">
        <div className="max-w-[1560px] mx-auto px-6 sm:px-10 lg:px-12 h-20 flex items-center justify-between">
          {/* Brand Logo & Name */}
          <Link href="/" className="flex items-center gap-3.5 group cursor-pointer">
            <SakuraLogo size={32} alt="Sakura AI" className="transition-transform duration-300 group-hover:scale-105 drop-shadow-[0_0_10px_rgba(255,42,133,0.5)]" />
            <span className="font-extrabold text-[18px] sm:text-[19px] tracking-[0.24em] text-white font-sans uppercase">
              SAKURA AI
            </span>
          </Link>

          {/* Center Navigation Links */}
          <nav className="hidden md:flex items-center gap-8 lg:gap-10">
            <a
              href="#features"
              onClick={() => setActiveNav('features')}
              className={`relative text-[14px] font-medium transition-colors py-1 ${
                activeNav === 'features' ? 'text-white' : 'text-[#9298A3] hover:text-white'
              }`}
            >
              Features
              {activeNav === 'features' && (
                <span className="absolute -bottom-2 left-0 right-0 h-[2.5px] bg-[#FF2A85] rounded-full shadow-[0_0_10px_#FF2A85]" />
              )}
            </a>
            <a
              href="#memory"
              onClick={() => setActiveNav('memory')}
              className={`relative text-[14px] font-medium transition-colors py-1 ${
                activeNav === 'memory' ? 'text-white' : 'text-[#9298A3] hover:text-white'
              }`}
            >
              Memory
              {activeNav === 'memory' && (
                <span className="absolute -bottom-2 left-0 right-0 h-[2.5px] bg-[#FF2A85] rounded-full shadow-[0_0_10px_#FF2A85]" />
              )}
            </a>
            <a
              href="#workflows"
              onClick={() => setActiveNav('workflows')}
              className={`relative text-[14px] font-medium transition-colors py-1 ${
                activeNav === 'workflows' ? 'text-white' : 'text-[#9298A3] hover:text-white'
              }`}
            >
              Workflows
              {activeNav === 'workflows' && (
                <span className="absolute -bottom-2 left-0 right-0 h-[2.5px] bg-[#FF2A85] rounded-full shadow-[0_0_10px_#FF2A85]" />
              )}
            </a>
            <a href="#images" className="text-[14px] font-medium text-[#9298A3] hover:text-white transition-colors py-1">
              Images
            </a>
            <a href="#pricing" className="text-[14px] font-medium text-[#9298A3] hover:text-white transition-colors py-1">
              Pricing
            </a>
          </nav>

          {/* Right CTA Actions */}
          <div className="flex items-center gap-5 sm:gap-7">
            <button
              onClick={() => setShowIntro(true)}
              className="hidden sm:flex items-center gap-1.5 text-[13.5px] font-medium text-[#9298A3] hover:text-[#FF2A85] transition-colors cursor-pointer"
              title="Watch Intro Video"
            >
              <svg className="w-3.5 h-3.5 text-[#FF2A85]" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7z" />
              </svg>
              <span>Intro</span>
            </button>

            <Link
              href="/login"
              className="text-[14px] font-medium text-[#9298A3] hover:text-white transition-colors"
            >
              Sign in
            </Link>

            {/* Bordered Primary Nav Button: Get Started */}
            <Link
              href="/console"
              className="relative inline-flex p-[1px] rounded-xl overflow-hidden group cursor-pointer shadow-[0_0_18px_rgba(255,42,133,0.25)]"
            >
              <span className="absolute inset-0 bg-gradient-to-r from-[#FF2A85] via-[#A855F7] to-[#00F0FF] opacity-90 group-hover:opacity-100 transition-opacity" />
              <span className="relative px-5 py-2 rounded-[11px] bg-[#080B10]/95 group-hover:bg-[#080B10]/80 text-[13.5px] font-semibold text-white tracking-wide transition-colors">
                Get Started
              </span>
            </Link>
          </div>
        </div>
      </header>

      {/* Spacer for fixed navbar */}
      <div className="h-20" />

      {/* ═══════════════════════════════════════════════════════════════
          HERO SECTION (16:9 Desktop Viewport Ratio)
          ═══════════════════════════════════════════════════════════════ */}
      <main className="max-w-[1560px] mx-auto px-6 sm:px-10 lg:px-12 py-8 lg:py-12 min-h-[calc(100vh-80px)] flex items-center relative">
        {/* Subtle Ambient Background Light Blooms */}
        <div className="absolute top-1/4 right-1/4 w-96 h-96 bg-[#00F0FF]/10 rounded-full blur-[140px] pointer-events-none -z-10" />
        <div className="absolute bottom-1/4 left-1/4 w-96 h-96 bg-[#FF2A85]/10 rounded-full blur-[140px] pointer-events-none -z-10" />

        <div className="w-full flex flex-col lg:flex-row items-center justify-between gap-12 lg:gap-8">
          
          {/* ─── LEFT HERO CONTENT (44%) ─── */}
          <div className="w-full lg:w-[44%] flex flex-col justify-center max-w-[640px]">
            {/* Upper-Left Multimodal AI Label + Circuit Line */}
            <div className="flex items-center gap-3">
              <span className="w-2.5 h-2.5 rounded-full bg-[#FF2A85] shadow-[0_0_12px_#FF2A85] flex-shrink-0" />
              <span className="text-[11px] sm:text-[11.5px] font-bold tracking-[0.24em] text-[#FF3385] uppercase whitespace-nowrap">
                YOUR MULTIMODAL AI ASSISTANT
              </span>
              {/* Technical Decorative Circuit Line */}
              <div className="flex-1 hidden sm:flex items-center ml-2 relative">
                <div className="w-full h-[1px] bg-gradient-to-r from-[#FF2A85]/70 via-[#00F0FF]/40 to-transparent" />
                <div className="w-2.5 h-[1px] bg-[#00F0FF]/40 -rotate-45 -ml-1 origin-left" />
                <div className="w-8 h-[1px] bg-white/20 -mt-3.5" />
              </div>
            </div>

            {/* Massive 3-Line Marketing Headline with Radiant Gradient */}
            <h1 className="mt-6 text-[44px] sm:text-[54px] lg:text-[60px] xl:text-[68px] font-extrabold tracking-[-0.035em] leading-[1.08] text-white">
              One Assistant.
              <br />
              Every Mode.
              <br />
              <span className="bg-gradient-to-r from-[#FF2A85] via-[#B366FF] to-[#00F0FF] bg-clip-text text-transparent drop-shadow-[0_0_35px_rgba(255,42,133,0.35)]">
                Limitless Potential.
              </span>
            </h1>

            {/* Description Paragraph */}
            <p className="mt-6 text-[#9298A3] text-[16px] sm:text-[18px] lg:text-[19px] leading-[1.65] max-w-[540px] font-normal">
              Sakura AI is your all-in-one assistant for chat, coding, research,
              summarization, image creation, voice, and scheduling—working across text,
              images, and audio with memory that understands you.
            </p>

            {/* Primary CTA Row */}
            <div className="mt-8 sm:mt-10 flex flex-wrap items-center gap-4 sm:gap-5">
              {/* Primary Button with Vivid Gradient & Glowing Aura */}
              <Link
                href="/console"
                className="h-[56px] px-8 rounded-2xl bg-gradient-to-r from-[#FF2A85] via-[#8B5CF6] to-[#2563EB] hover:opacity-95 text-white font-semibold text-[15.5px] flex items-center justify-center gap-3 shadow-[0_0_28px_rgba(255,42,133,0.45),0_0_20px_rgba(37,99,235,0.3)] hover:shadow-[0_0_38px_rgba(255,42,133,0.65),0_0_25px_rgba(37,99,235,0.45)] transition-all transform hover:scale-[1.02] active:scale-[0.99] cursor-pointer"
              >
                {/* Sakura Flower Outline Icon */}
                <svg className="w-5 h-5 text-white flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M12 3C10.5 5 8 6 8 8C8 10 9.5 11 12 12C14.5 11 16 10 16 8C16 6 13.5 5 12 3Z" />
                  <path d="M21 12C19 10.5 18 8 16 8C14 8 13 9.5 12 12C13 14.5 14 16 16 16C18 16 19 13.5 21 12Z" />
                  <path d="M12 21C13.5 19 16 18 16 16C16 14 14.5 13 12 12C9.5 13 8 14 8 16C8 18 10.5 19 12 21Z" />
                  <path d="M3 12C5 13.5 6 16 8 16C10 16 11 14.5 12 12C11 9.5 10 8 8 8C6 8 5 10.5 3 12Z" />
                  <circle cx="12" cy="12" r="2" fill="currentColor" />
                </svg>
                <span>Start with Sakura</span>
                <span className="text-[17px] leading-none ml-0.5">→</span>
              </Link>

              {/* Secondary Button */}
              <button
                type="button"
                onClick={() => setShowDemoModal(true)}
                className="h-[56px] px-7 rounded-2xl bg-black/60 hover:bg-white/[0.08] border border-white/15 text-white font-medium text-[15px] flex items-center justify-center gap-2.5 transition-all cursor-pointer"
              >
                {/* Play Outline Icon */}
                <svg className="w-5 h-5 text-white/90" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <circle cx="12" cy="12" r="9" />
                  <polygon points="10 8 16 12 10 16 10 8" fill="currentColor" stroke="none" />
                </svg>
                <span>See Demo</span>
              </button>
            </div>

            {/* Horizontal Capability Strip with Bright Neon Accents */}
            <div className="mt-9 inline-flex flex-wrap items-center bg-[#090C12]/90 border border-white/12 rounded-2xl px-5 py-3 shadow-[0_10px_30px_rgba(0,0,0,0.8)] backdrop-blur-md gap-4 sm:gap-5 w-fit">
              {/* Memory Active */}
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-[#FF2A85] drop-shadow-[0_0_8px_rgba(255,42,133,0.6)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-2.04" />
                  <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-2.04" />
                </svg>
                <span className="text-[12.5px] font-medium text-white/95">Memory Active</span>
              </div>

              <div className="hidden sm:block h-3.5 w-[1px] bg-white/10" />

              {/* Image Gen */}
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-[#00F0FF] drop-shadow-[0_0_8px_rgba(0,240,255,0.6)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <rect width="18" height="18" x="3" y="3" rx="4" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <path d="m21 15-5-5L5 21" />
                </svg>
                <span className="text-[12.5px] font-medium text-white/95">Image Gen</span>
              </div>

              <div className="hidden sm:block h-3.5 w-[1px] bg-white/10" />

              {/* Voice */}
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-[#00F0FF] drop-shadow-[0_0_8px_rgba(0,240,255,0.6)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M2 10v4" />
                  <path d="M6 6v12" />
                  <path d="M10 3v18" />
                  <path d="M14 8v8" />
                  <path d="M18 5v14" />
                  <path d="M22 10v4" />
                </svg>
                <span className="text-[12.5px] font-medium text-white/95">Voice</span>
              </div>

              <div className="hidden sm:block h-3.5 w-[1px] bg-white/10" />

              {/* Research */}
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-[#38BDF8] drop-shadow-[0_0_8px_rgba(56,189,248,0.6)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <circle cx="11" cy="11" r="8" />
                  <path d="m21 21-4.3-4.3" />
                </svg>
                <span className="text-[12.5px] font-medium text-white/95">Research</span>
              </div>

              <div className="hidden sm:block h-3.5 w-[1px] bg-white/10" />

              {/* Scheduling */}
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-[#FF2A85] drop-shadow-[0_0_8px_rgba(255,42,133,0.6)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <rect width="18" height="18" x="3" y="4" rx="3" />
                  <line x1="16" x2="16" y1="2" y2="6" />
                  <line x1="8" x2="8" y1="2" y2="6" />
                  <line x1="3" x2="21" y1="10" y2="10" />
                </svg>
                <span className="text-[12.5px] font-medium text-white/95">Scheduling</span>
              </div>
            </div>

            {/* Social Proof Row */}
            <div className="mt-8 flex items-center gap-3.5">
              <div className="flex -space-x-2.5 overflow-hidden">
                <img
                  src="/social_avatars.png"
                  alt="Sakura Community Avatars"
                  className="h-7 w-auto object-contain"
                />
              </div>

              <div className="flex items-center gap-1 text-[#FF2A85] text-xs drop-shadow-[0_0_6px_rgba(255,42,133,0.7)]">
                <span>★</span><span>★</span><span>★</span><span>★</span><span>★</span>
              </div>

              <span className="text-[13px] text-[#9298A3] font-normal">
                Trusted by 50,000+ creators, developers, and teams worldwide.
              </span>
            </div>
          </div>

          {/* ─── RIGHT HERO ARTWORK & FLOATING PANELS (56%) ─── */}
          <div className="w-full lg:w-[56%] flex items-center justify-center relative">
            {/* Ambient Backlight Glow around the artwork container */}
            <div className="absolute -inset-2 bg-gradient-to-tr from-[#FF2A85]/20 via-transparent to-[#00F0FF]/25 rounded-[38px] blur-2xl pointer-events-none -z-10" />

            {/* Main Rounded Artwork Container */}
            <div className="relative w-full aspect-[16/11] max-w-[780px] rounded-[30px] sm:rounded-[34px] overflow-hidden border border-white/15 shadow-[0_24px_70px_rgba(0,0,0,0.95)] group select-none">
              
              {/* High-End Vivid Anime Sakura Operator Artwork */}
              <img
                src="/sakura_hero_operator.jpg"
                alt="Sakura AI Operator at Workstation"
                className="w-full h-full object-cover object-center transform scale-100 group-hover:scale-[1.01] transition-transform duration-700"
              />

              {/* Minimal Subtle Edge Vignette */}
              <div className="absolute inset-0 bg-gradient-to-t from-black/45 via-transparent to-black/15 pointer-events-none" />

              {/* ─────────────────────────────────────────────────────────
                  1. FLOATING IMAGE GENERATION PANEL (Upper-Left)
                  ───────────────────────────────────────────────────────── */}
              <div className="absolute top-4 sm:top-5 left-4 sm:left-5 z-20 bg-[#090C12]/92 backdrop-blur-md border border-white/12 rounded-2xl p-3 shadow-2xl hover:border-[#00F0FF]/50 transition-all duration-300 hover:-translate-y-0.5 max-w-[210px] sm:max-w-[230px]">
                <div className="flex items-center gap-2 mb-2">
                  <div className="p-1 rounded-md bg-[#00F0FF]/15 text-[#00F0FF] shadow-[0_0_10px_rgba(0,240,255,0.35)]">
                    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect width="18" height="18" x="3" y="3" rx="4" />
                      <circle cx="8.5" cy="8.5" r="1.5" />
                      <path d="m21 15-5-5L5 21" />
                    </svg>
                  </div>
                  <span className="text-[12.5px] font-semibold text-white tracking-tight">Image Generation</span>
                </div>

                {/* 4 Miniature Thumbnails */}
                <div className="grid grid-cols-4 gap-1.5">
                  <div className="aspect-[3/4] rounded-lg overflow-hidden border border-white/10 bg-black/40 shadow-sm">
                    <img src="/thumb_mountain.png" alt="Snowy Mountain" className="w-full h-full object-cover" />
                  </div>
                  <div className="aspect-[3/4] rounded-lg overflow-hidden border border-white/10 bg-black/40 shadow-sm">
                    <img src="/thumb_pagoda.png" alt="Japanese Pagoda" className="w-full h-full object-cover" />
                  </div>
                  <div className="aspect-[3/4] rounded-lg overflow-hidden border border-white/10 bg-black/40 shadow-sm">
                    <img src="/thumb_neon.png" alt="Neon Street" className="w-full h-full object-cover" />
                  </div>
                  <div className="aspect-[3/4] rounded-lg overflow-hidden border border-white/10 bg-black/40 shadow-sm">
                    <img src="/thumb_character.png" alt="Anime Character" className="w-full h-full object-cover" />
                  </div>
                </div>
              </div>

              {/* ─────────────────────────────────────────────────────────
                  2. FLOATING CODE ASSISTANT PANEL (Upper-Right)
                  ───────────────────────────────────────────────────────── */}
              <div className="absolute top-4 sm:top-5 right-4 sm:right-5 z-20 bg-[#090C12]/92 backdrop-blur-md border border-white/12 rounded-2xl p-3.5 shadow-2xl hover:border-[#00F0FF]/50 transition-all duration-300 hover:-translate-y-0.5 max-w-[210px] sm:max-w-[230px]">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[12px] font-mono font-bold text-[#00F0FF] bg-[#00F0FF]/15 px-1.5 py-0.5 rounded shadow-[0_0_8px_rgba(0,240,255,0.35)]">
                    &lt;&gt;
                  </span>
                  <span className="text-[12.5px] font-semibold text-white tracking-tight">Code Assistant</span>
                </div>

                {/* Real-Looking Monospace Code Sample with Bright Syntax Highlighting */}
                <div className="bg-[#05070A]/85 border border-white/10 rounded-lg p-2 font-mono text-[10px] sm:text-[10.5px] text-[#CBD5E1] leading-[1.45]">
                  <p><span className="text-[#C084FC]">function</span> <span className="text-[#60A5FA]">sakuraAI</span>(prompt) &#123;</p>
                  <p className="pl-2.5"><span className="text-[#C084FC]">return</span> generate(&#123;</p>
                  <p className="pl-5 text-[#94A3B8]">model: <span className="text-[#4ADE80]">'sakura-pro'</span>,</p>
                  <p className="pl-5 text-[#94A3B8]">prompt,</p>
                  <p className="pl-5 text-[#94A3B8]">stream: <span className="text-[#FF2A85]">true</span></p>
                  <p className="pl-2.5">&#125;);</p>
                  <p>&#125;</p>
                </div>

                {/* Status line with Glowing Mint Green Checkmark */}
                <div className="mt-2 flex items-center gap-1.5 text-[11px] text-[#4ADE80] font-semibold drop-shadow-[0_0_6px_rgba(74,222,128,0.6)]">
                  <span>✓</span>
                  <span>Code generated</span>
                </div>
              </div>

              {/* ─────────────────────────────────────────────────────────
                  3. FLOATING WEB SEARCH PANEL (Center-Left)
                  ───────────────────────────────────────────────────────── */}
              <div className="absolute top-[48%] -translate-y-1/2 left-4 sm:left-5 z-20 bg-[#090C12]/92 backdrop-blur-md border border-white/12 rounded-2xl p-3.5 shadow-2xl hover:border-[#00F0FF]/50 transition-all duration-300 hover:-translate-y-1 w-[180px] sm:w-[195px]">
                <div className="flex items-center gap-2 mb-1.5">
                  <div className="p-1 rounded-md bg-[#00F0FF]/15 text-[#00F0FF] shadow-[0_0_10px_rgba(0,240,255,0.35)]">
                    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="11" cy="11" r="8" />
                      <path d="m21 21-4.3-4.3" />
                    </svg>
                  </div>
                  <span className="text-[12.5px] font-semibold text-white tracking-tight">Web Search</span>
                </div>

                <p className="text-[11.5px] text-[#9298A3] font-normal">Summarizing results...</p>

                <div className="mt-2 flex items-center justify-between text-[10.5px] text-[#626873]">
                  <span>Sourced 24 pages</span>
                  <span className="font-mono text-[#00F0FF] font-semibold">89%</span>
                </div>

                {/* Bright Glowing Cyan Progress Bar */}
                <div className="mt-1 w-full h-[3.5px] bg-white/10 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-[#00F0FF] to-[#3B82F6] w-[89%] rounded-full shadow-[0_0_12px_#00F0FF]" />
                </div>
              </div>

              {/* ─────────────────────────────────────────────────────────
                  4. FLOATING MEMORY PANEL (Lower-Right)
                  ───────────────────────────────────────────────────────── */}
              <div className="absolute bottom-20 right-4 sm:right-5 z-20 bg-[#090C12]/92 backdrop-blur-md border border-white/12 rounded-2xl p-3.5 shadow-2xl hover:border-[#FF2A85]/50 transition-all duration-300 hover:-translate-y-0.5 w-[185px] sm:w-[200px]">
                <div className="flex items-center gap-2 mb-1.5">
                  <div className="p-1 rounded-md bg-[#FF2A85]/15 text-[#FF2A85] shadow-[0_0_10px_rgba(255,42,133,0.35)]">
                    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M12 3C10.5 5 8 6 8 8C8 10 9.5 11 12 12C14.5 11 16 10 16 8C16 6 13.5 5 12 3Z" />
                      <path d="M21 12C19 10.5 18 8 16 8C14 8 13 9.5 12 12C13 14.5 14 16 16 16C18 16 19 13.5 21 12Z" />
                      <path d="M12 21C13.5 19 16 18 16 16C16 14 14.5 13 12 12C9.5 13 8 14 8 16C8 18 10.5 19 12 21Z" />
                      <path d="M3 12C5 13.5 6 16 8 16C10 16 11 14.5 12 12C11 9.5 10 8 8 8C6 8 5 10.5 3 12Z" />
                      <circle cx="12" cy="12" r="2" fill="currentColor" />
                    </svg>
                  </div>
                  <span className="text-[12.5px] font-semibold text-white tracking-tight">Memory</span>
                </div>

                <p className="text-[11.5px] text-[#9298A3] leading-[1.4] font-normal">
                  Remembers your projects, preferences, and context.
                </p>

                <p className="mt-2 text-[10.5px] text-[#626873]">128 memories</p>

                {/* Bright Glowing Pink Progress Indicator */}
                <div className="mt-1 w-full h-[3.5px] bg-white/10 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-[#FF2A85] to-[#F43F5E] w-[75%] rounded-full shadow-[0_0_12px_#FF2A85]" />
                </div>
              </div>

              {/* ─────────────────────────────────────────────────────────
                  5. BOTTOM STATUS BAR INSIDE ART
                  ───────────────────────────────────────────────────────── */}
              <div className="absolute bottom-4 left-4 sm:left-5 right-20 sm:right-22 z-20 bg-[#080B10]/94 backdrop-blur-md border border-white/12 rounded-xl px-4 py-2.5 flex items-center justify-between shadow-xl">
                <div className="flex items-center gap-2.5">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#22C55E] opacity-80" />
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-[#22C55E] shadow-[0_0_10px_#22C55E]" />
                  </span>
                  <span className="text-[11.5px] font-bold tracking-wider text-white uppercase">
                    SAKURA ONLINE
                  </span>
                </div>

                {/* Model Selector Trigger */}
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setShowModelDropdown(!showModelDropdown)}
                    className="flex items-center gap-1.5 text-[11px] text-[#9298A3] hover:text-white transition-colors cursor-pointer"
                  >
                    <span>MODEL</span>
                    <span className="text-white font-semibold">{activeModel}</span>
                    <svg className="w-3 h-3 text-[#9298A3]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </button>

                  {/* Tiny Model Dropdown Popover */}
                  {showModelDropdown && (
                    <div className="absolute right-0 bottom-full mb-2 w-36 bg-[#0E1219] border border-white/10 rounded-lg p-1 shadow-2xl z-30">
                      {['SAKURA PRO', 'SAKURA CODE', 'SAKURA ULTRA'].map((model) => (
                        <button
                          key={model}
                          onClick={() => {
                            setActiveModel(model);
                            setShowModelDropdown(false);
                          }}
                          className={`w-full text-left px-2.5 py-1.5 rounded text-[11px] font-medium transition-colors cursor-pointer ${
                            activeModel === model ? 'bg-[#FF2A85]/20 text-white' : 'text-[#9298A3] hover:text-white hover:bg-white/5'
                          }`}
                        >
                          {model}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* ─────────────────────────────────────────────────────────
                  6. CIRCULAR VOICE BUTTON WITH VIBRANT CYAN PULSE
                  ───────────────────────────────────────────────────────── */}
              <button
                type="button"
                onClick={() => router.push('/console')}
                title="Talk to Sakura"
                className="absolute bottom-4 right-4 sm:right-5 z-20 w-12 h-12 rounded-full bg-[#080B10]/95 border border-[#00F0FF]/50 shadow-[0_0_24px_rgba(0,240,255,0.4)] flex items-center justify-center hover:scale-110 active:scale-95 transition-all cursor-pointer group/voice"
              >
                <svg className="w-5 h-5 text-[#00F0FF] group-hover/voice:scale-110 transition-transform drop-shadow-[0_0_8px_#00F0FF]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M2 10v4" />
                  <path d="M6 6v12" />
                  <path d="M10 3v18" />
                  <path d="M14 8v8" />
                  <path d="M18 5v14" />
                  <path d="M22 10v4" />
                </svg>
              </button>

            </div>
          </div>

        </div>
      </main>

      {/* ═══════════════════════════════════════════════════════════════
          FEATURES SECTION (Matching Reference Image)
          ═══════════════════════════════════════════════════════════════ */}
      <section id="features" className="max-w-[1560px] mx-auto px-6 sm:px-10 lg:px-12 py-16 sm:py-20 scroll-mt-20 relative">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10 items-center">
          
          {/* Left Column: Heading & Description */}
          <div className="lg:col-span-4 flex flex-col">
            <span className="text-[11px] font-bold tracking-[0.24em] text-[#FF2A85] uppercase block mb-3">
              FEATURES
            </span>
            <h2 className="text-[32px] sm:text-[38px] lg:text-[42px] font-extrabold tracking-[-0.03em] leading-[1.14] text-white">
              Everything you need.
              <br />
              One{' '}
              <span className="bg-gradient-to-r from-[#FF2A85] via-[#B366FF] to-[#00F0FF] bg-clip-text text-transparent">
                intelligent assistant.
              </span>
            </h2>
            <p className="mt-4 text-[#9298A3] text-[14px] sm:text-[15px] leading-relaxed max-w-[380px]">
              Powerful capabilities designed to amplify your creativity and productivity.
            </p>
          </div>

          {/* Right Column: 4 Minimalist Feature Cards */}
          <div className="lg:col-span-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            
            {/* Card 1: Chat & Assistant */}
            <div
              onClick={() => router.push('/console')}
              className="bg-[#090C12] border border-white/[0.08] hover:border-[#FF2A85]/50 rounded-2xl p-5 flex flex-col justify-start min-h-[185px] transition-all duration-300 hover:-translate-y-1 group cursor-pointer shadow-lg"
            >
              <div className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#FF2A85] mb-3.5 group-hover:scale-105 transition-transform">
                <svg className="w-5 h-5 drop-shadow-[0_0_8px_#FF2A85]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
                  <circle cx="9" cy="11" r="1" fill="currentColor" />
                  <circle cx="12" cy="11" r="1" fill="currentColor" />
                  <circle cx="15" cy="11" r="1" fill="currentColor" />
                </svg>
              </div>
              <h3 className="text-white font-bold text-[15px] tracking-tight group-hover:text-[#FF2A85] transition-colors">
                Chat & Assistant
              </h3>
              <p className="mt-2 text-[#88909D] text-[12px] leading-relaxed">
                Natural conversations that understand context and adapt to you.
              </p>
            </div>

            {/* Card 2: Code Assistant */}
            <div
              onClick={() => router.push('/console')}
              className="bg-[#090C12] border border-white/[0.08] hover:border-[#00F0FF]/50 rounded-2xl p-5 flex flex-col justify-start min-h-[185px] transition-all duration-300 hover:-translate-y-1 group cursor-pointer shadow-lg"
            >
              <div className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#00F0FF] mb-3.5 group-hover:scale-105 transition-transform">
                <svg className="w-5 h-5 drop-shadow-[0_0_8px_#00F0FF]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <polyline points="16 18 22 12 16 6" />
                  <polyline points="8 6 2 12 8 18" />
                </svg>
              </div>
              <h3 className="text-white font-bold text-[15px] tracking-tight group-hover:text-[#00F0FF] transition-colors">
                Code Assistant
              </h3>
              <p className="mt-2 text-[#88909D] text-[12px] leading-relaxed">
                Write, debug, and ship code faster with AI by your side.
              </p>
            </div>

            {/* Card 3: Image Generation */}
            <div
              onClick={() => router.push('/console')}
              className="bg-[#090C12] border border-white/[0.08] hover:border-[#FF2A85]/50 rounded-2xl p-5 flex flex-col justify-start min-h-[185px] transition-all duration-300 hover:-translate-y-1 group cursor-pointer shadow-lg"
            >
              <div className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#FF2A85] mb-3.5 group-hover:scale-105 transition-transform">
                <svg className="w-5 h-5 drop-shadow-[0_0_8px_#FF2A85]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect width="18" height="18" x="3" y="3" rx="4" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <path d="m21 15-5-5L5 21" />
                </svg>
              </div>
              <h3 className="text-white font-bold text-[15px] tracking-tight group-hover:text-[#FF2A85] transition-colors">
                Image Generation
              </h3>
              <p className="mt-2 text-[#88909D] text-[12px] leading-relaxed">
                Create stunning imagery from text or reference.
              </p>
            </div>

            {/* Card 4: Voice & Audio */}
            <div
              onClick={() => router.push('/console')}
              className="bg-[#090C12] border border-white/[0.08] hover:border-[#A47DF0]/50 rounded-2xl p-5 flex flex-col justify-start min-h-[185px] transition-all duration-300 hover:-translate-y-1 group cursor-pointer shadow-lg"
            >
              <div className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#A47DF0] mb-3.5 group-hover:scale-105 transition-transform">
                <svg className="w-5 h-5 drop-shadow-[0_0_8px_#A47DF0]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M2 10v4" />
                  <path d="M6 6v12" />
                  <path d="M10 3v18" />
                  <path d="M14 8v8" />
                  <path d="M18 5v14" />
                  <path d="M22 10v4" />
                </svg>
              </div>
              <h3 className="text-white font-bold text-[15px] tracking-tight group-hover:text-[#A47DF0] transition-colors">
                Voice & Audio
              </h3>
              <p className="mt-2 text-[#88909D] text-[12px] leading-relaxed">
                Transcribe, summarize, and interact using voice.
              </p>
            </div>

          </div>

        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════
          MEMORY SECTION (Matching Reference Image)
          ═══════════════════════════════════════════════════════════════ */}
      <section id="memory" className="max-w-[1560px] mx-auto px-6 sm:px-10 lg:px-12 py-16 sm:py-20 scroll-mt-20 relative">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8 items-stretch">
          
          {/* Left Column: Heading & Learn More */}
          <div className="lg:col-span-4 flex flex-col justify-center">
            <span className="text-[11px] font-bold tracking-[0.24em] text-[#FF2A85] uppercase block mb-3">
              MEMORY
            </span>
            <h2 className="text-[32px] sm:text-[38px] lg:text-[42px] font-extrabold tracking-[-0.03em] leading-[1.14] text-white">
              Remembers what
              <br />
              matters. For you.
            </h2>
            <p className="mt-4 text-[#9298A3] text-[14px] sm:text-[15px] leading-relaxed max-w-[360px]">
              Sakura AI stores your preferences, interests, and important details securely and privately. So you get smarter, more personal results every time.
            </p>
            <div className="mt-6">
              <Link
                href="/console"
                className="rounded-xl border border-white/15 bg-white/[0.03] hover:bg-white/[0.08] hover:border-white/30 text-white text-xs font-semibold px-4.5 py-2.5 inline-flex items-center gap-2 transition-all cursor-pointer"
              >
                <span>Learn More</span>
                <span className="text-sm leading-none">→</span>
              </Link>
            </div>
          </div>

          {/* Center Column: Desk Artwork with Neural Orb & Window */}
          <div className="lg:col-span-5 flex items-center">
            <div className="w-full rounded-2xl overflow-hidden border border-white/10 shadow-2xl aspect-[16/10] bg-[#090C12] group">
              <img
                src="/features/memory_neural_desk.png"
                alt="Sakura Memory Neural Hub"
                className="w-full h-full object-cover object-center transform group-hover:scale-105 transition-transform duration-500"
              />
            </div>
          </div>

          {/* Right Column: 4 Memory Capabilities List */}
          <div className="lg:col-span-3 flex items-center">
            <div className="w-full bg-[#090C12] border border-white/[0.08] rounded-2xl p-5 sm:p-6 flex flex-col justify-between gap-4 h-full shadow-lg">
              
              {/* Item 1: Preferences */}
              <div className="flex items-start gap-3.5 group">
                <div className="w-9 h-9 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#FF2A85] flex-shrink-0 mt-0.5 shadow-[0_0_10px_rgba(255,42,133,0.2)]">
                  <SakuraLogo size={18} alt="Preferences" />
                </div>
                <div>
                  <h4 className="text-white font-semibold text-[13.5px] tracking-tight">
                    Preferences
                  </h4>
                  <p className="text-[#88909D] text-[11.5px] mt-0.5">
                    Understands your style
                  </p>
                </div>
              </div>

              {/* Item 2: Knowledge */}
              <div className="flex items-start gap-3.5 group">
                <div className="w-9 h-9 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#FF2A85] flex-shrink-0 mt-0.5">
                  <svg className="w-4.5 h-4.5 text-[#FF2A85]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
                    <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
                  </svg>
                </div>
                <div>
                  <h4 className="text-white font-semibold text-[13.5px] tracking-tight">
                    Knowledge
                  </h4>
                  <p className="text-[#88909D] text-[11.5px] mt-0.5">
                    Remembers what you've shared
                  </p>
                </div>
              </div>

              {/* Item 3: History */}
              <div className="flex items-start gap-3.5 group">
                <div className="w-9 h-9 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#FF2A85] flex-shrink-0 mt-0.5">
                  <svg className="w-4.5 h-4.5 text-[#FF2A85]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 16 14" />
                  </svg>
                </div>
                <div>
                  <h4 className="text-white font-semibold text-[13.5px] tracking-tight">
                    History
                  </h4>
                  <p className="text-[#88909D] text-[11.5px] mt-0.5">
                    Builds on past conversations
                  </p>
                </div>
              </div>

              {/* Item 4: Privacy */}
              <div className="flex items-start gap-3.5 group">
                <div className="w-9 h-9 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#FF2A85] flex-shrink-0 mt-0.5">
                  <svg className="w-4.5 h-4.5 text-[#FF2A85]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                </div>
                <div>
                  <h4 className="text-white font-semibold text-[13.5px] tracking-tight">
                    Privacy
                  </h4>
                  <p className="text-[#88909D] text-[11.5px] mt-0.5">
                    Your memory is always private
                  </p>
                </div>
              </div>

            </div>
          </div>

        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════
          WORKFLOWS SECTION (Matching Reference Image)
          ═══════════════════════════════════════════════════════════════ */}
      <section id="workflows" className="max-w-[1560px] mx-auto px-6 sm:px-10 lg:px-12 py-16 sm:py-20 scroll-mt-20 relative">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8 items-center">
          
          {/* Left Column: Heading & CTA */}
          <div className="lg:col-span-3 flex flex-col justify-center">
            <span className="text-[11px] font-bold tracking-[0.24em] text-[#FF2A85] uppercase block mb-3">
              WORKFLOWS
            </span>
            <h2 className="text-[32px] sm:text-[38px] lg:text-[42px] font-extrabold tracking-[-0.03em] leading-[1.14] text-white">
              Work smarter
              <br />
              with{' '}
              <span className="bg-gradient-to-r from-[#FF2A85] via-[#B366FF] to-[#00F0FF] bg-clip-text text-transparent">
                Sakura AI.
              </span>
            </h2>
            <p className="mt-4 text-[#9298A3] text-[14px] sm:text-[15px] leading-relaxed max-w-[320px]">
              Pre-built workflows and automations to handle complex tasks in just a few clicks.
            </p>
            <div className="mt-6">
              <Link
                href="/console"
                className="rounded-xl border border-white/15 bg-white/[0.03] hover:bg-white/[0.08] hover:border-white/30 text-white text-xs font-semibold px-4.5 py-2.5 inline-flex items-center gap-2 transition-all cursor-pointer"
              >
                <span>Explore Workflows</span>
                <span className="text-sm leading-none">→</span>
              </Link>
            </div>
          </div>

          {/* Right Column: 3 Action Cards + 1 Pagoda Artwork */}
          <div className="lg:col-span-9 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 items-stretch">
            
            {/* Card 1: Code Review */}
            <div
              onClick={() => router.push('/console')}
              className="bg-[#090C12] border border-white/[0.08] hover:border-[#00F0FF]/50 rounded-2xl p-5 flex flex-col justify-between min-h-[175px] transition-all duration-300 hover:-translate-y-1 group cursor-pointer shadow-lg"
            >
              <div>
                <div className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#00F0FF] mb-3.5">
                  <svg className="w-5 h-5 drop-shadow-[0_0_8px_#00F0FF]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                    <polyline points="16 18 22 12 16 6" />
                    <polyline points="8 6 2 12 8 18" />
                  </svg>
                </div>
                <h3 className="text-white font-bold text-[14.5px] tracking-tight group-hover:text-[#00F0FF] transition-colors">
                  Code Review
                </h3>
                <p className="mt-1.5 text-[#88909D] text-[12px] leading-relaxed">
                  Analyze, refactor, and improve your code with AI.
                </p>
              </div>
              <div className="mt-3 flex justify-end text-[#6E7681] group-hover:text-[#00F0FF] transition-colors">
                <span className="text-sm font-semibold group-hover:translate-x-1 transition-transform">→</span>
              </div>
            </div>

            {/* Card 2: Content Creation */}
            <div
              onClick={() => router.push('/console')}
              className="bg-[#090C12] border border-white/[0.08] hover:border-[#FF2A85]/50 rounded-2xl p-5 flex flex-col justify-between min-h-[175px] transition-all duration-300 hover:-translate-y-1 group cursor-pointer shadow-lg"
            >
              <div>
                <div className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#FF2A85] mb-3.5">
                  <svg className="w-5 h-5 drop-shadow-[0_0_8px_#FF2A85]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                </div>
                <h3 className="text-white font-bold text-[14.5px] tracking-tight group-hover:text-[#FF2A85] transition-colors">
                  Content Creation
                </h3>
                <p className="mt-1.5 text-[#88909D] text-[12px] leading-relaxed">
                  Generate blogs, scripts, and marketing content.
                </p>
              </div>
              <div className="mt-3 flex justify-end text-[#6E7681] group-hover:text-[#FF2A85] transition-colors">
                <span className="text-sm font-semibold group-hover:translate-x-1 transition-transform">→</span>
              </div>
            </div>

            {/* Card 3: Research Assistant */}
            <div
              onClick={() => router.push('/console')}
              className="bg-[#090C12] border border-white/[0.08] hover:border-[#00F0FF]/50 rounded-2xl p-5 flex flex-col justify-between min-h-[175px] transition-all duration-300 hover:-translate-y-1 group cursor-pointer shadow-lg"
            >
              <div>
                <div className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/10 flex items-center justify-center text-[#00F0FF] mb-3.5">
                  <svg className="w-5 h-5 drop-shadow-[0_0_8px_#00F0FF]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="11" cy="11" r="8" />
                    <path d="m21 21-4.3-4.3" />
                  </svg>
                </div>
                <h3 className="text-white font-bold text-[14.5px] tracking-tight group-hover:text-[#00F0FF] transition-colors">
                  Research Assistant
                </h3>
                <p className="mt-1.5 text-[#88909D] text-[12px] leading-relaxed">
                  Summarize, compare, and find what matters.
                </p>
              </div>
              <div className="mt-3 flex justify-end text-[#6E7681] group-hover:text-[#00F0FF] transition-colors">
                <span className="text-sm font-semibold group-hover:translate-x-1 transition-transform">→</span>
              </div>
            </div>

            {/* Card 4: Japanese Pagoda Sunset Artwork */}
            <div className="rounded-2xl overflow-hidden border border-white/10 shadow-lg min-h-[175px] group relative">
              <img
                src="/features/workflows_pagoda_art.png"
                alt="Tokyo Pagoda Dusk"
                className="w-full h-full object-cover object-center transform group-hover:scale-108 transition-transform duration-500"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-black/30 via-transparent to-transparent pointer-events-none" />
            </div>

          </div>

        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════
          CALL-TO-ACTION BANNER (Matching Reference Image)
          ═══════════════════════════════════════════════════════════════ */}
      <section className="max-w-[1560px] mx-auto px-6 sm:px-10 lg:px-12 py-10">
        <div className="rounded-2xl bg-gradient-to-r from-[#0C1019] via-[#090C12] to-[#0A0F1A] border border-[#FF2A85]/35 shadow-[0_0_30px_rgba(255,42,133,0.18)] p-6 sm:p-7 flex flex-col sm:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-4.5 w-full sm:w-auto">
            <div className="w-12 h-12 rounded-xl bg-[#FF2A85]/15 border border-[#FF2A85]/40 flex items-center justify-center flex-shrink-0 shadow-[0_0_15px_rgba(255,42,133,0.3)]">
              <SakuraLogo size={26} alt="Sakura Logo" />
            </div>
            <div>
              <h3 className="text-[18px] sm:text-[20px] font-bold text-white tracking-tight">
                Ready to unlock your limitless potential?
              </h3>
              <p className="text-[12.5px] sm:text-[13px] text-[#A0A6B0] mt-0.5">
                Join thousands of creators, developers, and dreamers using Sakura AI.
              </p>
            </div>
          </div>

          <Link
            href="/console"
            className="h-[46px] px-7 rounded-xl bg-gradient-to-r from-[#FF2A85] via-[#8B5CF6] to-[#2563EB] text-white font-semibold text-sm shadow-[0_0_24px_rgba(255,42,133,0.45)] hover:shadow-[0_0_34px_rgba(255,42,133,0.65)] hover:scale-[1.02] active:scale-[0.99] transition-all whitespace-nowrap cursor-pointer inline-flex items-center justify-center gap-2 flex-shrink-0"
          >
            <span>Start Your Journey</span>
            <span className="text-base leading-none">→</span>
          </Link>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════════
          RICH FOOTER (Matching Reference Image)
          ═══════════════════════════════════════════════════════════════ */}
      <footer className="max-w-[1560px] mx-auto px-6 sm:px-10 lg:px-12 pt-16 pb-12">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-12 gap-10 pb-12 border-b border-white/[0.06]">
          
          {/* Brand & Socials (Col 1-4) */}
          <div className="lg:col-span-4 flex flex-col justify-between">
            <div>
              <Link href="/" className="flex items-center gap-3 group cursor-pointer">
                <SakuraLogo size={24} alt="Sakura AI" />
                <span className="font-extrabold text-[16px] tracking-[0.22em] text-white uppercase">
                  SAKURA AI
                </span>
              </Link>
              <p className="mt-3.5 text-[#88909D] text-[13px] leading-relaxed max-w-[280px]">
                Your intelligent AI assistant.
                <br />
                Limitless. Personalized. Yours.
              </p>
            </div>

            {/* Social Icons */}
            <div className="flex items-center gap-4 mt-6">
              {/* X / Twitter */}
              <a href="#" className="w-8 h-8 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/10 flex items-center justify-center text-[#A0A6B0] hover:text-white transition-colors">
                <span className="font-bold text-xs">𝕏</span>
              </a>
              {/* Discord */}
              <a href="#" className="w-8 h-8 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/10 flex items-center justify-center text-[#A0A6B0] hover:text-white transition-colors">
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.929 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.894.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
                </svg>
              </a>
              {/* GitHub */}
              <a href="#" className="w-8 h-8 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/10 flex items-center justify-center text-[#A0A6B0] hover:text-white transition-colors">
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
                </svg>
              </a>
              {/* Instagram */}
              <a href="#" className="w-8 h-8 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/10 flex items-center justify-center text-[#A0A6B0] hover:text-white transition-colors">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <rect width="20" height="20" x="2" y="2" rx="5" ry="5" />
                  <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" />
                  <circle cx="17.5" cy="6.5" r="1.5" fill="currentColor" />
                </svg>
              </a>
            </div>
          </div>

          {/* Product (Col 5-6) */}
          <div className="lg:col-span-2">
            <span className="text-[12.5px] font-semibold text-white tracking-wide block mb-3.5">
              Product
            </span>
            <ul className="space-y-2.5 text-[12.5px] text-[#88909D]">
              <li><a href="#features" className="hover:text-white transition-colors">Features</a></li>
              <li><a href="#memory" className="hover:text-white transition-colors">Memory</a></li>
              <li><a href="#workflows" className="hover:text-white transition-colors">Workflows</a></li>
              <li><Link href="/console" className="hover:text-white transition-colors">Integrations</Link></li>
            </ul>
          </div>

          {/* Resources (Col 7-8) */}
          <div className="lg:col-span-2">
            <span className="text-[12.5px] font-semibold text-white tracking-wide block mb-3.5">
              Resources
            </span>
            <ul className="space-y-2.5 text-[12.5px] text-[#88909D]">
              <li><a href="#" className="hover:text-white transition-colors">Documentation</a></li>
              <li><a href="#" className="hover:text-white transition-colors">Guides</a></li>
              <li><a href="#" className="hover:text-white transition-colors">Help Center</a></li>
              <li><a href="#" className="hover:text-white transition-colors">Blog</a></li>
            </ul>
          </div>

          {/* Company (Col 9) */}
          <div className="lg:col-span-1">
            <span className="text-[12.5px] font-semibold text-white tracking-wide block mb-3.5">
              Company
            </span>
            <ul className="space-y-2.5 text-[12.5px] text-[#88909D]">
              <li><a href="#" className="hover:text-white transition-colors">About</a></li>
              <li><a href="#" className="hover:text-white transition-colors">Careers</a></li>
              <li><a href="#" className="hover:text-white transition-colors">Contact</a></li>
            </ul>
          </div>

          {/* Stay in the loop Newsletter Card (Col 10-12) */}
          <div className="lg:col-span-3">
            <div className="rounded-2xl border border-[#FF2A85]/30 bg-[#090C12] p-5 flex flex-col gap-3 shadow-lg">
              <span className="text-[13.5px] font-bold text-white tracking-tight">
                Stay in the loop
              </span>
              <p className="text-[11.5px] text-[#88909D] leading-normal">
                Get the latest updates, new features, and product drops.
              </p>
              
              <div className="mt-1 flex items-center bg-white/[0.04] border border-white/10 rounded-xl px-3 py-1.5 focus-within:border-[#FF2A85]/60 transition-colors">
                <input
                  type="email"
                  placeholder="Enter your email"
                  className="w-full bg-transparent text-xs text-white placeholder-[#6E7681] focus:outline-none"
                />
                <button
                  type="button"
                  className="text-[#A0A6B0] hover:text-[#FF2A85] text-sm font-bold pl-2 transition-colors cursor-pointer"
                >
                  →
                </button>
              </div>
            </div>
          </div>

        </div>

        {/* Copyright */}
        <div className="pt-8 text-center text-[12px] text-[#6E7681]">
          © 2026 Sakura AI. All rights reserved.
        </div>
      </footer>

      {/* ═══════════════════════════════════════════════════════════════
          INTERACTIVE DEMO MODAL
          ═══════════════════════════════════════════════════════════════ */}
      {showDemoModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="bg-[#0A0D13] border border-white/10 rounded-3xl max-w-2xl w-full p-6 sm:p-8 shadow-2xl relative">
            <button
              onClick={() => setShowDemoModal(false)}
              className="absolute top-5 right-5 text-[#9298A3] hover:text-white p-1 rounded-lg hover:bg-white/10 transition-colors"
            >
              ✕
            </button>
            <div className="flex items-center gap-3 mb-4">
              <SakuraLogo size={28} />
              <h3 className="text-xl font-bold text-white tracking-wide">Sakura AI Interactive Showcase</h3>
            </div>
            <p className="text-[#9298A3] text-sm leading-relaxed mb-6">
              Experience all modes inside the live Sakura AI workspace. Generate production code, research complex topics with deep web synthesis, craft 8K visual artwork, and speak with real-time vocal latency.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
              <div className="bg-[#0E1219] p-3 rounded-xl border border-white/5 text-center">
                <span className="text-[#48C8F0] font-bold text-sm block mb-1">Codex Core</span>
                <span className="text-[11px] text-[#9298A3]">Full-stack generation</span>
              </div>
              <div className="bg-[#0E1219] p-3 rounded-xl border border-white/5 text-center">
                <span className="text-[#EF72A4] font-bold text-sm block mb-1">Neural Memory</span>
                <span className="text-[11px] text-[#9298A3]">Zero context loss</span>
              </div>
              <div className="bg-[#0E1219] p-3 rounded-xl border border-white/5 text-center">
                <span className="text-[#A882F0] font-bold text-sm block mb-1">Hybrid RAG</span>
                <span className="text-[11px] text-[#9298A3]">Multi-file analysis</span>
              </div>
              <div className="bg-[#0E1219] p-3 rounded-xl border border-white/5 text-center">
                <span className="text-[#63D79A] font-bold text-sm block mb-1">Live Web</span>
                <span className="text-[11px] text-[#9298A3]">Real-time grounding</span>
              </div>
            </div>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowDemoModal(false)}
                className="px-5 py-2.5 rounded-xl border border-white/10 text-[#9298A3] hover:text-white transition-colors"
              >
                Close
              </button>
              <Link
                href="/console"
                className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-[#EF72A4] to-[#48C8F0] text-white font-semibold text-sm transition-opacity hover:opacity-90"
              >
                Launch Workspace →
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
