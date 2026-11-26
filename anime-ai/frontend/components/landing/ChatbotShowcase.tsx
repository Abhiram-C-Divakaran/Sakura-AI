import React from 'react';
import { SakuraLogo } from '../SakuraLogo';

export const ChatbotShowcase: React.FC = () => {
  const infoPoints = [
    {
      icon: (
        <svg className="w-4 h-4 text-[#FF5F8F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
      ),
      title: 'CONTEXTUAL CONVERSATIONS',
      body: 'Keeps track of relevant conversation context to respond more usefully.',
    },
    {
      icon: (
        <svg className="w-4 h-4 text-[#FF5F8F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
        </svg>
      ),
      title: 'WORK WITH FILES',
      body: 'Attach supported files and ask Sakura to summarize, explain, analyze, or use them.',
    },
    {
      icon: (
        <svg className="w-4 h-4 text-[#FF5F8F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
      ),
      title: 'TOOLS WHEN NEEDED',
      body: 'Depending on the task, Sakura can use configured tools such as research, coding, or image creation.',
    },
    {
      icon: (
        <svg className="w-4 h-4 text-[#FF5F8F]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      ),
      title: 'ONE WORKSPACE',
      body: 'Your conversations, files, projects, and tasks stay organized together.',
    },
  ];

  return (
    <section id="meet-sakura" className="relative w-full py-24 sm:py-32 z-10 overflow-hidden bg-[#030304]">
      {/* Subtle ambient light */}
      <div
        aria-hidden="true"
        className="absolute w-[600px] h-[600px] rounded-full bg-[#FF5F8F]/[0.04] blur-[160px] pointer-events-none right-0 top-1/2 -translate-y-1/2 z-0"
      />

      <div className="max-w-[1440px] mx-auto px-6 sm:px-10 lg:px-12 relative z-10">

        {/* Section Header */}
        <div className="text-left max-w-[700px] mb-14 sm:mb-16">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#FF5F8F]/10 border border-[#FF5F8F]/20 mb-5">
            <span className="text-[12px] font-semibold tracking-[0.16em] uppercase text-[#FF5F8F]">
              Meet Sakura
            </span>
          </div>
          <h2 className="text-[32px] sm:text-[44px] lg:text-[50px] font-bold font-display text-[#F7F7F8] tracking-[-0.025em] leading-[1.1] mb-5">
            More than a chatbot.
          </h2>
          <p className="text-[16px] sm:text-[17px] text-[#A3A3AB] leading-relaxed">
            Sakura is designed to move beyond simple question-and-answer chat. It can work with conversational context, analyze files, use tools, help with research, use configured image tools, and assist with software projects inside one workspace.
          </p>
        </div>

        {/* Two-column layout: Feature points LEFT, Chat Demo RIGHT */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-14 items-center">

          {/* Left Column: 4 Capability Points */}
          <div className="lg:col-span-5 flex flex-col justify-center">
            <div className="space-y-6 sm:space-y-7">
              {infoPoints.map((point, i) => (
                <div key={i} className="flex gap-4 items-start">
                  <div className="w-10 h-10 rounded-xl bg-[#08080B] border border-white/[0.08] flex items-center justify-center flex-shrink-0 mt-0.5">
                    {point.icon}
                  </div>
                  <div>
                    <h3 className="text-[13px] font-mono font-bold tracking-[0.14em] text-[#F7F7F8] uppercase mb-1">
                      {point.title}
                    </h3>
                    <p className="text-[14px] text-[#A3A3AB] leading-relaxed">
                      {point.body}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right Column: Realistic Chat UI Mockup */}
          <div className="lg:col-span-7 select-none">
            <div className="rounded-[22px] bg-[#08080B] border border-white/[0.10] overflow-hidden shadow-[0_30px_80px_rgba(0,0,0,0.6)]">
              {/* Window Bar */}
              <div className="h-10 bg-[#0D0D11] px-4 flex items-center justify-between border-b border-white/[0.06]">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#FF5F56]/80" />
                  <span className="w-2.5 h-2.5 rounded-full bg-[#FFBD2E]/80" />
                  <span className="w-2.5 h-2.5 rounded-full bg-[#27C93F]/80" />
                </div>
                <div className="flex items-center gap-2 text-[11px] font-mono text-[#6F6F78]">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#FF5F8F]" />
                  <span>Sakura · illustrative conversation</span>
                </div>
                <div className="w-14" />
              </div>

              {/* Chat Canvas */}
              <div className="p-5 sm:p-6 space-y-5 bg-[#030304]">
                {/* User Message */}
                <div className="flex gap-3 justify-end items-start">
                  <div className="max-w-[85%] bg-[#FF5F8F]/15 border border-[#FF5F8F]/25 rounded-2xl rounded-tr-sm px-4 py-3 text-[13px] text-[#F7F7F8]">
                    Can you review this repository and fix the failing authentication tests?
                  </div>
                  <div className="w-7 h-7 rounded-full bg-[#1A1A22] border border-white/[0.12] flex items-center justify-center flex-shrink-0 text-[11px] font-semibold text-[#F7F7F8]">
                    You
                  </div>
                </div>

                {/* Assistant Message with Activity & Result */}
                <div className="flex gap-3 justify-start items-start">
                  <div className="w-7 h-7 rounded-full bg-[#FF5F8F]/15 border border-[#FF5F8F]/30 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <SakuraLogo size={16} alt="Sakura" />
                  </div>
                  <div className="max-w-[90%] flex flex-col gap-3">
                    {/* Activity Pipeline Block */}
                    <div className="bg-[#08080B] border border-white/[0.08] rounded-xl px-4 py-3 w-full">
                      <div className="space-y-2">
                        {[
                          'Exploring repository structure',
                          'Reading authentication flow',
                          'Editing 3 files',
                          'Running tests',
                        ].map((step, idx) => (
                          <div key={idx} className="flex items-center gap-2 text-[12px]">
                            <span className="w-1.5 h-1.5 rounded-full bg-[#FF5F8F]" />
                            <span className="text-[#A3A3AB]">{step}</span>
                          </div>
                        ))}
                      </div>
                      <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center gap-2 text-[12px]">
                        <svg className="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                        </svg>
                        <span className="text-emerald-400 font-medium font-mono">49 tests passed · illustrative example</span>
                      </div>
                    </div>

                    {/* Final Assistant Response */}
                    <div className="bg-[#08080B] border border-white/[0.07] rounded-2xl rounded-tl-sm px-4 py-3 text-[13px] text-[#F7F7F8] leading-relaxed">
                      I found the issue in token validation and updated the affected authentication paths. The relevant test suite now passes.
                    </div>
                  </div>
                </div>

                {/* Input Composer */}
                <div className="w-full rounded-xl bg-[#08080B] border border-white/[0.08] p-3 flex items-center justify-between mt-3">
                  <div className="flex items-center gap-2.5 text-[#6F6F78] text-[13px]">
                    <svg className="w-4 h-4 text-[#A3A3AB]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                    </svg>
                    <span>Message Sakura...</span>
                  </div>
                  <div className="w-7 h-7 rounded-full bg-[#FF5F8F] text-white flex items-center justify-center">
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
    </section>
  );
};
