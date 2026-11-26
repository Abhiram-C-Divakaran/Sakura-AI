import React from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { LandingNavbar } from '../components/landing/LandingNavbar';
import { LandingFooter } from '../components/landing/LandingFooter';

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-[#050507] text-[#F7F7F8] font-sans antialiased overflow-x-hidden selection:bg-[#FF4F83]/30 selection:text-white">
      <Head>
        <title>Privacy Policy — Sakura AI</title>
        <meta name="description" content="Sakura AI Privacy Policy. Learn how your data and workspace information are protected." />
      </Head>

      <LandingNavbar />

      <main className="max-w-[840px] mx-auto px-6 sm:px-10 pt-36 pb-24 relative z-10">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#FF4F83]/10 border border-[#FF4F83]/20 mb-6">
          <span className="text-[12px] font-semibold tracking-[0.2em] uppercase text-[#FFA6C2]">
            Legal Notice
          </span>
        </div>

        <h1 className="text-[36px] sm:text-[44px] font-bold font-display tracking-[-0.02em] text-white mb-4">
          Privacy Policy
        </h1>
        <p className="text-[14px] text-[#6F6F78] font-mono mb-4">
          Effective Date: Pending Publication · Version 1.0 (Draft — Requires Legal Review)
        </p>
        <div className="mb-10 rounded-xl border border-[#FF5F8F]/25 bg-[#FF5F8F]/5 px-4 py-3 text-[13px] text-[#E6B8C6]">
          Notice: This Privacy Policy draft is provided for pre-launch review and must be reviewed and approved by qualified legal counsel before public commercial launch.
        </div>

        <div className="space-y-8 text-[15px] text-[#A5A5AD] leading-relaxed">
          <section className="space-y-3">
            <h2 className="text-[20px] font-semibold text-white font-display">1. Information We Collect</h2>
            <p>
              When you create an account on Sakura AI, we collect your email address, authentication credentials, and account profile details. During use, we store conversations, attached library documents, and configuration files associated with your workspace to provide persistent workspace functionality.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-[20px] font-semibold text-white font-display">2. How Your Data Is Handled</h2>
            <p>
              Your conversations and files are stored within isolated account workspaces. When you interact with AI features, prompts and document context are transmitted to the relevant model execution endpoints to generate responses. We do not sell your personal information or training data to third parties.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-[20px] font-semibold text-white font-display">3. Sandbox &amp; Code Execution Security</h2>
            <p>
              Production code execution requires a configured isolated execution environment. Code changes, task history, and test logs may be retained with the workspace. Available execution modes depend on the deployment.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-[20px] font-semibold text-white font-display">4. Data Retention and Deletion</h2>
            <p>
              You can delete your conversations and library files directly from the Sakura AI interface at any time. Account deletion requests remove associated data from our active storage systems.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-[20px] font-semibold text-white font-display">5. Contact &amp; Inquiries</h2>
            <p>
              If you have questions regarding this Privacy Policy or your data, please contact us via our{' '}
              <Link href="/contact" className="text-[#FFA6C2] hover:underline">
                Contact page
              </Link>{' '}
              for the available support channels.
            </p>
          </section>
        </div>
      </main>

      <LandingFooter />
    </div>
  );
}
