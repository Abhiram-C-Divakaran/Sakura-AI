import React from 'react';
import Link from 'next/link';
import { SakuraLogo } from '../SakuraLogo';

export const WorkspaceShowcase: React.FC = () => {
  return (
    <section id="workspace" aria-label="Illustrative Sakura workspace preview" className="relative w-full py-24 sm:py-32 overflow-hidden z-10 bg-[#030304]">
      {/* Background ambient lighting */}
      <div
        aria-hidden="true"
        className="absolute w-[500px] h-[500px] rounded-full bg-[#FF5F8F]/[0.05] blur-[140px] pointer-events-none -left-20 top-1/2 -translate-y-1/2 z-0"
      />

      <div className="max-w-[1440px] mx-auto px-6 sm:px-10 lg:px-12 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-center">
          
          {/* Left Column: Realistic Sakura AI App Mockup (7 cols) */}
          <div className="lg:col-span-7 xl:col-span-7 select-none">
            <div className="relative rounded-[22px] sm:rounded-[24px] bg-[#08080B] border border-white/[0.10] p-1.5 sm:p-2.5 shadow-[0_30px_80px_rgba(0,0,0,0.7)] group">
              {/* Subtle pink reflection */}
              <div
                aria-hidden="true"
                className="absolute -top-10 -left-10 w-40 h-40 bg-[#FF5F8F]/10 rounded-full blur-2xl pointer-events-none"
              />

              {/* Window Shell Header */}
              <div className="h-10 bg-[#0D0D11] rounded-t-[18px] sm:rounded-t-[20px] px-4 flex items-center justify-between border-b border-white/[0.06]">
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded-full bg-[#FF5F56]/80" />
                  <span className="w-3 h-3 rounded-full bg-[#FFBD2E]/80" />
                  <span className="w-3 h-3 rounded-full bg-[#27C93F]/80" />
                </div>
                <div className="text-[12px] font-mono text-[#6F6F78] flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#FF5F8F]" />
                  <span>Sakura AI — Illustrative workspace</span>
                </div>
                <div className="w-10" />
              </div>

              {/* App UI Grid inside Mockup */}
              <div className="grid grid-cols-12 bg-[#030304] rounded-b-[18px] sm:rounded-b-[20px] overflow-hidden min-h-[460px] sm:min-h-[500px]">
                
                {/* Mockup Left Sidebar (3 cols on md+) */}
                <div className="hidden sm:flex sm:col-span-3 bg-[#08080B] border-r border-white/[0.06] p-3.5 flex-col justify-between">
                  <div>
                    {/* Brand Lockup */}
                    <div className="flex items-center gap-2 mb-4">
                      <SakuraLogo size={18} alt="Sakura" />
                      <span className="text-[12px] font-bold text-white tracking-wide">Sakura AI</span>
                    </div>

                    {/* New Chat Button */}
                    <div className="w-full py-1.5 px-2.5 rounded-lg bg-[#0D0D11] border border-white/[0.08] text-[11px] text-white/90 font-medium flex items-center gap-2 mb-4 cursor-default">
                      <span className="text-[#FF5F8F] text-sm leading-none">+</span>
                      <span>New Chat</span>
                    </div>

                    {/* Nav Links */}
                    <div className="space-y-1 text-[11px] text-[#A3A3AB] font-medium">
                      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-white/[0.06] text-white">
                        <span>💬</span>
                        <span>Chat</span>
                      </div>
                      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white/[0.03]">
                        <span>📁</span>
                        <span>Library</span>
                      </div>
                      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white/[0.03]">
                        <span>🗂️</span>
                        <span>Projects</span>
                      </div>
                      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white/[0.03]">
                        <span>⏱️</span>
                        <span>Tasks</span>
                      </div>
                      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white/[0.03]">
                        <span>🔌</span>
                        <span>Plugins</span>
                      </div>
                    </div>

                    {/* Recent Chats Section */}
                    <div className="mt-5 pt-3 border-t border-white/[0.06]">
                      <div className="text-[9px] uppercase font-mono tracking-wider text-[#6F6F78] mb-2 px-1">Recent chats</div>
                      <div className="space-y-1 text-[11px] text-[#A3A3AB] truncate">
                        <div className="px-1.5 py-1 truncate hover:text-white rounded hover:bg-white/[0.02]">Fix authentication tests</div>
                        <div className="px-1.5 py-1 truncate hover:text-white rounded hover:bg-white/[0.02]">Design a landing page</div>
                        <div className="px-1.5 py-1 truncate hover:text-white rounded hover:bg-white/[0.02]">Analyze document</div>
                        <div className="px-1.5 py-1 truncate hover:text-white rounded hover:bg-white/[0.02]">Plan project roadmap</div>
                      </div>
                    </div>
                  </div>

                  <div className="text-[10px] text-[#6F6F78] px-1 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span>Preview</span>
                  </div>
                </div>

                {/* Mockup Center Workspace (6 cols on lg, 9 cols on sm) */}
                <div className="col-span-12 sm:col-span-9 lg:col-span-6 p-4 sm:p-5 flex flex-col justify-between bg-[#030304]">
                  {/* Center Welcome Header */}
                  <div className="flex flex-col items-center justify-center text-center pt-4 sm:pt-6">
                    <div className="w-10 h-10 rounded-xl bg-[#FF5F8F]/10 border border-[#FF5F8F]/20 flex items-center justify-center mb-2.5">
                      <SakuraLogo size={24} alt="Sakura Logo" />
                    </div>
                    <h3 className="text-[16px] sm:text-[17px] font-bold text-white font-display mb-0.5">
                      Sakura AI
                    </h3>
                    <p className="text-[12px] text-[#A3A3AB]">
                      How can I help you today?
                    </p>

                    {/* Suggestion Chips */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-5 w-full max-w-[360px]">
                      <div className="p-2 rounded-xl bg-[#08080B] border border-white/[0.06] text-[11px] text-[#F7F7F8] text-left">
                        <span className="block font-medium">Analyze a document</span>
                        <span className="text-[#6F6F78] text-[10px]">PDF, Markdown, Code</span>
                      </div>
                      <div className="p-2 rounded-xl bg-[#08080B] border border-white/[0.06] text-[11px] text-[#F7F7F8] text-left">
                        <span className="block font-medium">Work on a repository</span>
                        <span className="text-[#6F6F78] text-[10px]">Inspect, edit, test</span>
                      </div>
                      <div className="p-2 rounded-xl bg-[#08080B] border border-white/[0.06] text-[11px] text-[#F7F7F8] text-left">
                        <span className="block font-medium">Create an image</span>
                        <span className="text-[#6F6F78] text-[10px]">Original visual art</span>
                      </div>
                      <div className="p-2 rounded-xl bg-[#08080B] border border-white/[0.06] text-[11px] text-[#F7F7F8] text-left">
                        <span className="block font-medium">Research a topic</span>
                        <span className="text-[#6F6F78] text-[10px]">Synthesis &amp; sources</span>
                      </div>
                    </div>
                  </div>

                  {/* Mockup Composer */}
                  <div className="pt-4">
                    <div className="w-full rounded-xl bg-[#08080B] border border-white/[0.08] p-2.5 flex items-center justify-between">
                      <div className="flex items-center gap-2 text-[#6F6F78] text-[12px]">
                        <svg className="w-3.5 h-3.5 text-[#A3A3AB]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                        </svg>
                        <span>Message Sakura...</span>
                      </div>
                      <div className="w-6 h-6 rounded-full bg-[#FF5F8F] text-white flex items-center justify-center">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                        </svg>
                      </div>
                    </div>
                  </div>

                </div>

                {/* Mockup Right Panel: Sakura Code Context (3 cols on lg only) */}
                <div className="hidden lg:flex lg:col-span-3 bg-[#08080B] border-l border-white/[0.06] p-3.5 flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between mb-4">
                      <span className="text-[12px] font-semibold text-white">Sakura Code</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#FF5F8F]/15 text-[#FF5F8F] font-mono">example</span>
                    </div>

                    <div className="space-y-3 text-[11px]">
                      <div>
                        <span className="text-[#6F6F78] block text-[10px] uppercase font-mono">Repository</span>
                        <span className="text-white font-mono">Sakura-AI</span>
                      </div>
                      <div>
                        <span className="text-[#6F6F78] block text-[10px] uppercase font-mono">Branch</span>
                        <span className="text-[#A3A3AB] font-mono">main</span>
                      </div>
                      <div>
                        <span className="text-[#6F6F78] block text-[10px] uppercase font-mono">Status</span>
                        <span className="text-emerald-400 font-mono">✓ 49 tests passing · example</span>
                      </div>

                      <div className="pt-3 border-t border-white/[0.06]">
                        <span className="text-[#6F6F78] block text-[10px] uppercase font-mono mb-1.5">Recent Activity</span>
                        <div className="space-y-1.5 text-[10px] text-[#A3A3AB]">
                          <div className="flex items-center gap-1.5">
                            <span className="w-1 h-1 rounded-full bg-[#FF5F8F]" />
                            <span>Edited 3 files (+84 -21)</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <span className="w-1 h-1 rounded-full bg-emerald-400" />
                            <span>Ran test suite (49/49)</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <span className="w-1 h-1 rounded-full bg-sky-400" />
                            <span>Updated documentation</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="pt-3 border-t border-white/[0.06] text-[10px] text-[#6F6F78]">
                    <span>Example execution environment</span>
                  </div>
                </div>

              </div>
            </div>
          </div>

          {/* Right Column: Headline, Copy & Checklist (5 cols) */}
          <div className="lg:col-span-5 xl:col-span-5 flex flex-col items-start text-left">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#FF5F8F]/10 border border-[#FF5F8F]/20 mb-5">
              <span className="text-[12px] font-semibold tracking-[0.16em] uppercase text-[#FF5F8F]">
                A Unified AI Workspace
              </span>
            </div>

            <h2 className="text-[36px] sm:text-[44px] lg:text-[48px] font-bold font-display text-[#F7F7F8] tracking-[-0.02em] leading-[1.1] mb-5">
              Chat. Create. Code.<br />
              All in one place.
            </h2>

            <p className="text-[16px] text-[#A3A3AB] leading-relaxed mb-8">
              From everyday questions to repository-level engineering, Sakura keeps conversations, files, tools, and execution in one focused workspace.
            </p>

            {/* Checklist */}
            <div className="space-y-3.5 mb-9 w-full">
              {[
                'Clean minimal interface',
                'Repository-aware Sakura Code',
                'Files and knowledge together',
                'Image and multimodal workflows',
                'Projects stay organized',
              ].map((item, idx) => (
                <div key={idx} className="flex items-center gap-3">
                  <div className="w-5 h-5 rounded-full bg-[#FF5F8F]/15 text-[#FF5F8F] flex items-center justify-center flex-shrink-0">
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.8} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <span className="text-[15px] font-medium text-[#F7F7F8]">
                    {item}
                  </span>
                </div>
              ))}
            </div>

            <Link
              href="/chat"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full text-[14px] font-semibold text-white bg-[#FF5F8F] hover:bg-[#FF7CA2] shadow-[0_2px_14px_rgba(255,95,143,0.35)] hover:shadow-[0_4px_22px_rgba(255,95,143,0.5)] transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-[#FF5F8F]"
            >
              <span>Explore Workspace →</span>
            </Link>
          </div>

        </div>
      </div>
    </section>
  );
};
