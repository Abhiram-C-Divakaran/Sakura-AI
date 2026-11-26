import React from 'react';
import Link from 'next/link';

export const SakuraCodeShowcase: React.FC = () => {
  const pipelineSteps = [
    { label: 'Exploring repository', done: true },
    { label: 'Reading relevant files', done: true },
    { label: 'Planning changes', done: true },
    { label: 'Editing 4 files', done: true },
    { label: 'Running tests', done: true },
    { label: 'All tests passed!', done: true, isSuccess: true },
  ];

  return (
    <section id="sakura-code" aria-label="Sakura Code with illustrative workflow" className="relative w-full py-24 sm:py-32 overflow-hidden z-10 bg-[#030304]">
      {/* Pink ambient left glow */}
      <div
        aria-hidden="true"
        className="absolute w-[500px] h-[500px] rounded-full bg-[#FF5F8F]/[0.05] blur-[150px] pointer-events-none -left-20 top-1/2 -translate-y-1/2 z-0"
      />

      <div className="max-w-[1440px] mx-auto px-6 sm:px-10 lg:px-12 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-center">

          {/* Left: Headline, description, checklist & CTA */}
          <div className="lg:col-span-5 xl:col-span-5 flex flex-col">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#FF5F8F]/10 border border-[#FF5F8F]/20 mb-5 self-start">
              <span className="text-[12px] font-semibold tracking-[0.16em] uppercase text-[#FF5F8F]">
                Sakura Code
              </span>
            </div>

            <h2 className="text-[32px] sm:text-[44px] lg:text-[48px] font-bold font-display text-[#F7F7F8] tracking-[-0.025em] leading-[1.1] mb-5">
              From idea to<br />tested code.
            </h2>

            <p className="text-[16px] text-[#A3A3AB] leading-relaxed mb-8 max-w-[460px]">
              Sakura can inspect a repository before changing it, understand relevant files, make updates, run tests, inspect failures, and review the resulting diff.
            </p>

            {/* Checklist */}
            <div className="space-y-3 mb-9">
              {[
                'Explore and understand your codebase',
                'Make focused, reviewable changes',
                'Run and verify tests',
                'Fix issues and iterate',
                'Review changes before applying',
              ].map((item, i) => (
                <div key={i} className="flex items-center gap-3">
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
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full text-[14px] font-semibold text-white bg-[#FF5F8F] hover:bg-[#FF7CA2] shadow-[0_2px_14px_rgba(255,95,143,0.35)] hover:shadow-[0_4px_22px_rgba(255,95,143,0.5)] transition-all self-start focus:outline-none focus-visible:ring-2 focus-visible:ring-[#FF5F8F]"
            >
              <span>Try Sakura Code →</span>
            </Link>
          </div>

          {/* Right: Code activity & diff split mockup */}
          <div className="lg:col-span-7 xl:col-span-7 select-none">
            <div className="rounded-[22px] bg-[#08080B] border border-white/[0.10] overflow-hidden shadow-[0_30px_80px_rgba(0,0,0,0.6)]">
              {/* Window chrome */}
              <div className="h-10 bg-[#0D0D11] px-4 flex items-center justify-between border-b border-white/[0.06]">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#FF5F56]/80" />
                  <span className="w-2.5 h-2.5 rounded-full bg-[#FFBD2E]/80" />
                  <span className="w-2.5 h-2.5 rounded-full bg-[#27C93F]/80" />
                </div>
                <div className="flex items-center gap-2 text-[11px] font-mono text-[#6F6F78]">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#FF5F8F]" />
                  <span>Sakura Code · illustrative workflow</span>
                </div>
                <div className="w-14" />
              </div>

              {/* Pipeline Tabs */}
              <div className="flex items-center gap-1.5 px-4 pt-3 pb-2.5 border-b border-white/[0.06] bg-[#08080B] overflow-x-auto text-[12px]">
                {['Exploring', 'Planning', 'Editing', 'Testing'].map((tab) => (
                  <div key={tab} className="px-3 py-1 text-[#6F6F78] font-mono">
                    {tab}
                  </div>
                ))}
                <div className="px-3 py-1 rounded-full bg-[#FF5F8F]/15 text-[#FF5F8F] font-mono font-medium border border-[#FF5F8F]/30 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#FF5F8F]" />
                  <span>Completed</span>
                </div>
              </div>

              {/* Split Content: Activity Left, Code Diff Right */}
              <div className="grid grid-cols-1 md:grid-cols-12 divide-y md:divide-y-0 md:divide-x divide-white/[0.06] bg-[#030304]">
                
                {/* Activity Pipeline Left (5 cols) */}
                <div className="md:col-span-5 p-5 flex flex-col justify-between">
                  <div className="space-y-3">
                    <span className="text-[11px] font-mono uppercase tracking-wider text-[#6F6F78] block mb-2">
                      Execution pipeline
                    </span>

                    {pipelineSteps.map((step, idx) => (
                      <div key={idx} className="flex items-center gap-2.5 text-[12px]">
                        <div className="w-4 h-4 rounded-full bg-emerald-950/40 border border-emerald-500/30 flex items-center justify-center text-emerald-400 flex-shrink-0">
                          <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                          </svg>
                        </div>
                        <span className={`font-mono ${step.isSuccess ? 'text-emerald-400 font-semibold' : 'text-[#A3A3AB]'}`}>
                          {step.label}
                        </span>
                      </div>
                    ))}
                  </div>

                  <div className="pt-6 mt-6 border-t border-white/[0.06]">
                    <div className="flex items-center gap-2 text-[12px] font-mono mb-3">
                      <span className="text-[#A3A3AB]">4 files changed</span>
                      <span className="text-emerald-400 font-semibold">+83</span>
                      <span className="text-rose-400 font-semibold">−21</span>
                    </div>
                    <Link
                      href="/chat"
                      className="w-full py-2 px-3 rounded-xl bg-[#08080B] border border-white/[0.12] text-[12px] text-white font-medium hover:bg-white/[0.04] transition-colors flex items-center justify-center gap-2"
                    >
                      <span>Review changes</span>
                      <svg className="w-3.5 h-3.5 text-[#A3A3AB]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </Link>
                  </div>
                </div>

                {/* Diff Editor Right (7 cols) */}
                <div className="md:col-span-7 p-4 sm:p-5 font-mono text-[12px] leading-relaxed bg-[#050507]">
                  <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/[0.06] text-[11px] text-[#6F6F78]">
                    <span className="text-[#A3A3AB]">auth.ts</span>
                    <span>TypeScript</span>
                  </div>

                  <div className="space-y-1">
                    <div className="text-[#6F6F78]">
                      <span className="w-6 inline-block select-none text-right mr-3 text-[#4A4A52]">15</span>
                      <span className="text-[#D5D5DA]">export async function validateToken(token: string) {'{'}</span>
                    </div>
                    <div className="bg-rose-950/30 text-rose-300 rounded px-1 -mx-1">
                      <span className="w-6 inline-block select-none text-right mr-3 text-rose-500/70">16</span>
                      <span className="text-rose-400 font-semibold mr-1">−</span>
                      <span className="line-through">if (!token) return null;</span>
                    </div>
                    <div className="bg-rose-950/30 text-rose-300 rounded px-1 -mx-1">
                      <span className="w-6 inline-block select-none text-right mr-3 text-rose-500/70">17</span>
                      <span className="text-rose-400 font-semibold mr-1">−</span>
                      <span className="line-through">const payload = decode(token);</span>
                    </div>
                    <div className="bg-emerald-950/35 text-emerald-300 rounded px-1 -mx-1">
                      <span className="w-6 inline-block select-none text-right mr-3 text-emerald-500/70">18</span>
                      <span className="text-emerald-400 font-semibold mr-1">+</span>
                      <span>if (!token) throw new Error(&quot;Token required&quot;);</span>
                    </div>
                    <div className="bg-emerald-950/35 text-emerald-300 rounded px-1 -mx-1">
                      <span className="w-6 inline-block select-none text-right mr-3 text-emerald-500/70">19</span>
                      <span className="text-emerald-400 font-semibold mr-1">+</span>
                      <span>const payload = await verifyToken(token);</span>
                    </div>
                    <div className="text-[#6F6F78]">
                      <span className="w-6 inline-block select-none text-right mr-3 text-[#4A4A52]">20</span>
                    </div>
                    <div className="text-[#6F6F78]">
                      <span className="w-6 inline-block select-none text-right mr-3 text-[#4A4A52]">21</span>
                      <span className="text-[#D5D5DA]">return payload;</span>
                    </div>
                    <div className="text-[#6F6F78]">
                      <span className="w-6 inline-block select-none text-right mr-3 text-[#4A4A52]">22</span>
                      <span className="text-[#D5D5DA]">{'}'}</span>
                    </div>
                  </div>

                  <div className="mt-6 pt-3 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-[#6F6F78]">
                    <div className="flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                      <span className="text-emerald-400 font-medium">Example test result</span>
                    </div>
                    <span>49 passed · example</span>
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
