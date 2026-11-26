import React from 'react';
import Link from 'next/link';
import { SakuraLogo } from '../SakuraLogo';

export const ProductShowcase: React.FC = () => {
  return (
    <section id="showcase" className="relative w-full py-20 lg:py-28 overflow-hidden z-10">
      {/* Background ambient lighting */}
      <div
        aria-hidden="true"
        className="absolute w-[500px] h-[500px] rounded-full bg-[#FF4F83]/10 blur-[140px] pointer-events-none -left-20 top-1/2 -translate-y-1/2 z-0"
      />

      <div className="max-w-[1440px] mx-auto px-6 sm:px-10 lg:px-12 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-center">
          
          {/* Left Column: Realistic Sakura AI App Mockup (7 cols) */}
          <div className="lg:col-span-7 xl:col-span-7 select-none">
            <div className="relative rounded-[20px] sm:rounded-[24px] bg-[#09090C] border border-white/[0.10] p-1.5 sm:p-2.5 shadow-[0_30px_80px_rgba(0,0,0,0.7)] group">
              {/* Subtle pink halo reflection on top-left corner */}
              <div
                aria-hidden="true"
                className="absolute -top-10 -left-10 w-40 h-40 bg-[#FF4F83]/15 rounded-full blur-2xl pointer-events-none"
              />

              {/* Window Shell Header */}
              <div className="h-10 bg-[#0D0D12] rounded-t-[18px] sm:rounded-t-[20px] px-4 flex items-center justify-between border-b border-white/[0.06]">
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full bg-[#FF5F56]/80" />
                  <span className="w-3 h-3 rounded-full bg-[#FFBD2E]/80" />
                  <span className="w-3 h-3 rounded-full bg-[#27C93F]/80" />
                </div>
                <div className="text-[12px] font-mono text-[#6F6F78] flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#FF4F83]" />
                  <span>sakura-workspace</span>
                </div>
                <div className="w-10" />
              </div>

              {/* App UI Grid inside Mockup */}
              <div className="grid grid-cols-12 bg-[#050507] rounded-b-[18px] sm:rounded-b-[20px] overflow-hidden min-h-[420px] sm:min-h-[480px]">
                
                {/* Mockup Left Sidebar (4 cols on sm+) */}
                <div className="hidden sm:flex sm:col-span-4 bg-[#09090C] border-r border-white/[0.06] p-4 flex-col justify-between">
                  <div>
                    {/* Brand Lockup */}
                    <div className="flex items-center gap-2 mb-5">
                      <SakuraLogo size={20} alt="Sakura" />
                      <span className="text-[13px] font-bold text-white tracking-wide">Sakura AI</span>
                    </div>

                    {/* New Chat Button */}
                    <div className="w-full py-2 px-3 rounded-xl bg-[#16161D] border border-white/[0.08] text-[12px] text-white/90 font-medium flex items-center gap-2 mb-5 cursor-default">
                      <span className="text-[#FF6F98] text-base leading-none">+</span>
                      <span>New Chat</span>
                    </div>

                    {/* Nav Links */}
                    <div className="space-y-1 text-[12px] text-[#A5A5AD] font-medium">
                      <div className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg bg-white/[0.05] text-white">
                        <span>💬</span>
                        <span>Chat</span>
                      </div>
                      <div className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-white/[0.03]">
                        <span>📁</span>
                        <span>Library</span>
                      </div>
                      <div className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-white/[0.03]">
                        <span>🎨</span>
                        <span>Images</span>
                      </div>
                      <div className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-white/[0.03]">
                        <span>⚡</span>
                        <span>Sakura Code</span>
                      </div>
                      <div className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-white/[0.03]">
                        <span>🗂️</span>
                        <span>Projects</span>
                      </div>
                    </div>

                    {/* Recent Chats Section */}
                    <div className="mt-6 pt-4 border-t border-white/[0.06]">
                      <div className="text-[10px] uppercase font-mono tracking-wider text-[#6F6F78] mb-2 px-2">Recent</div>
                      <div className="space-y-1 text-[11px] text-[#A5A5AD]/80 truncate">
                        <div className="px-2 py-1 truncate hover:text-white">Refactor auth module</div>
                        <div className="px-2 py-1 truncate hover:text-white">Build landing page</div>
                        <div className="px-2 py-1 truncate hover:text-white">Research competitors</div>
                        <div className="px-2 py-1 truncate hover:text-white">Draft project proposal</div>
                      </div>

                    </div>
                  </div>

                  <div className="text-[11px] text-[#6F6F78] px-2 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500/80" />
                    <span>Connected</span>
                  </div>
                </div>

                {/* Mockup Center Workspace (8 cols) */}
                <div className="col-span-12 sm:col-span-8 p-5 sm:p-7 flex flex-col justify-between bg-[#050507]">
                  {/* Center Welcome Header */}
                  <div className="flex flex-col items-center justify-center text-center pt-6 sm:pt-10">
                    <div className="w-12 h-12 rounded-2xl bg-[#FF4F83]/10 border border-[#FF4F83]/20 flex items-center justify-center mb-3">
                      <SakuraLogo size={28} alt="Sakura Logo" />
                    </div>
                    <h4 className="text-[18px] sm:text-[20px] font-bold text-white font-display mb-1">
                      Sakura AI
                    </h4>
                    <p className="text-[13px] text-[#A5A5AD]">
                      How can I help you today?
                    </p>

                    {/* Suggestion Chips */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mt-6 w-full max-w-[420px]">
                      <div className="p-2.5 rounded-xl bg-[#0D0D12] border border-white/[0.06] text-[11px] text-[#F7F7F8]/90 text-left">
                        <span className="block font-medium text-white">Analyze a document</span>
                        <span className="text-[#6F6F78] text-[10px]">Upload and extract insights</span>
                      </div>
                      <div className="p-2.5 rounded-xl bg-[#0D0D12] border border-white/[0.06] text-[11px] text-[#F7F7F8]/90 text-left">
                        <span className="block font-medium text-white">Work on a repository</span>
                        <span className="text-[#6F6F78] text-[10px]">Sakura Code engine</span>
                      </div>
                      <div className="p-2.5 rounded-xl bg-[#0D0D12] border border-white/[0.06] text-[11px] text-[#F7F7F8]/90 text-left">
                        <span className="block font-medium text-white">Create an image</span>
                        <span className="text-[#6F6F78] text-[10px]">High-res concept art</span>
                      </div>
                      <div className="p-2.5 rounded-xl bg-[#0D0D12] border border-white/[0.06] text-[11px] text-[#F7F7F8]/90 text-left">
                        <span className="block font-medium text-white">Research a topic</span>
                        <span className="text-[#6F6F78] text-[10px]">Clear breakdown</span>
                      </div>
                    </div>
                  </div>

                  {/* Mockup Composer */}
                  <div className="pt-6">
                    <div className="w-full rounded-2xl bg-[#0D0D12] border border-white/[0.08] p-3 flex items-center justify-between shadow-inner">
                      <div className="flex items-center gap-3 text-[#6F6F78] text-[13px]">
                        <svg className="w-4 h-4 text-[#A5A5AD]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z" />
                        </svg>
                        <span>Message Sakura...</span>
                      </div>
                      <div className="w-7 h-7 rounded-full bg-[#FF4F83] text-white flex items-center justify-center shadow-[0_0_10px_rgba(255,79,131,0.5)]">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                        </svg>
                      </div>
                    </div>
                  </div>

                </div>

              </div>
            </div>
          </div>

          {/* Right Column: Headline, Copy & Benefits (5 cols) */}
          <div className="lg:col-span-5 xl:col-span-5 flex flex-col items-start text-left">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#FF4F83]/10 border border-[#FF4F83]/20 mb-5">
              <span className="text-[12px] font-semibold tracking-[0.2em] uppercase text-[#FFA6C2]">
                A Unified AI Workspace
              </span>
            </div>

            <h2 className="text-[36px] sm:text-[44px] lg:text-[48px] font-bold font-display text-[#F7F7F8] tracking-[-0.02em] leading-[1.1] mb-5">
              Chat. Create. Code.<br />
              All in one place.
            </h2>

            <p className="text-[16px] text-[#A3A3AA] leading-relaxed mb-8">
              From everyday conversations to repository-level engineering, Sakura keeps your ideas, files, tools, and execution in one focused workspace.
            </p>

            {/* Checklist */}
            <div className="space-y-4 mb-9 w-full">
              {[
                'Minimal, focused interface',
                'Repository-aware Sakura Code',
                'Files and knowledge in one place',
                'Multimodal workflows',
                'Projects that stay organized',
              ].map((item, idx) => (
                <div key={idx} className="flex items-start gap-3">
                  <div className="w-5 h-5 rounded-full bg-[#FF4F83]/15 text-[#FF6F98] flex items-center justify-center flex-shrink-0 mt-0.5">
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.8} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <span className="text-[15px] font-medium text-[#F7F7F8]/90">
                    {item}
                  </span>
                </div>
              ))}
            </div>

            <Link
              href="/chat"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full text-[14px] font-semibold text-white bg-[#FF4F83] hover:bg-[#FF6F98] shadow-[0_2px_14px_rgba(255,79,131,0.35)] hover:shadow-[0_4px_22px_rgba(255,79,131,0.5)] transition-all"
            >
              <span>Explore Workspace</span>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </Link>
          </div>

        </div>
      </div>
    </section>
  );
};
