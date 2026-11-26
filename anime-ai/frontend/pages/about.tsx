import React from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { LandingNavbar } from '../components/landing/LandingNavbar';
import { LandingFooter } from '../components/landing/LandingFooter';

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-[#050507] text-[#F7F7F8] font-sans antialiased overflow-x-hidden selection:bg-[#FF4F83]/30 selection:text-white">
      <Head>
        <title>About — Sakura AI</title>
        <meta name="description" content="About Sakura AI. An intelligent multimodal AI workspace built for conversation, research, coding, and real work." />
      </Head>

      <LandingNavbar />

      <main className="max-w-[840px] mx-auto px-6 sm:px-10 pt-36 pb-24 relative z-10">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#FF4F83]/10 border border-[#FF4F83]/20 mb-6">
          <span className="text-[12px] font-semibold tracking-[0.2em] uppercase text-[#FFA6C2]">
            Our Mission
          </span>
        </div>

        <h1 className="text-[36px] sm:text-[48px] font-bold font-display tracking-[-0.02em] text-white mb-6">
          About Sakura AI
        </h1>

        <div className="space-y-6 text-[16px] text-[#A5A5AD] leading-relaxed">
          <p>
            Sakura AI is a serious, multimodal AI workspace designed to bring conversation, deep research, repository-level coding, image creation, document knowledge, and intelligent workflows into a unified environment.
          </p>
          <p>
            While many AI tools are fragmented across separate browser tabs and generic chat windows, Sakura AI unites context, files, and executable tools in one cohesive place. Our anime and cherry blossom aesthetic provides an elegant atmosphere — but underneath lies an engineering platform built for real productivity.
          </p>
          <p>
            From exploring complex codebases in isolated execution environments to synthesizing dense documents and visualizing new ideas, Sakura AI is built to turn imagination into finished work.
          </p>

          <div className="pt-8 flex items-center gap-4">
            <Link
              href="/chat"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full text-[14px] font-semibold text-white bg-[#FF4F83] hover:bg-[#FF6F98] shadow-[0_2px_14px_rgba(255,79,131,0.35)] transition-all"
            >
              <span>Try Sakura AI</span>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </Link>
            <Link
              href="/contact"
              className="px-5 py-3 rounded-full text-[14px] font-medium text-[#A5A5AD] hover:text-white transition-colors"
            >
              Get in touch
            </Link>
          </div>
        </div>
      </main>

      <LandingFooter />
    </div>
  );
}
