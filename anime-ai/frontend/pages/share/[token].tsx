import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import Head from 'next/head';
import Link from 'next/link';
import { SakuraLogo } from '../../components/SakuraLogo';
import { Loader2, ArrowLeft, MessageSquare, AlertCircle } from 'lucide-react';
import { apiUrl } from '../../lib/api';

interface SharedMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at?: string;
}

interface SharedData {
  title: string;
  created_at?: string;
  character_id: string;
  messages: SharedMessage[];
}

export default function SharedConversationPage() {
  const router = useRouter();
  const { token } = router.query;
  const [data, setData] = useState<SharedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || typeof token !== 'string') return;

    const fetchShared = async () => {
      try {
        setLoading(true);
        setError(null);
        const res = await fetch(apiUrl(`/api/v1/share/${token}`));
        if (!res.ok) {
          throw new Error('This shared conversation has expired or was removed.');
        }
        const json = await res.json();
        setData(json);
      } catch (err: any) {
        setError(err.message || 'Failed to load shared conversation.');
      } finally {
        setLoading(false);
      }
    };

    fetchShared();
  }, [token]);

  return (
    <div className="min-h-screen bg-[#0D0D0D] text-[#ECECEC] flex flex-col font-sans select-text">
      <Head>
        <title>{data ? `${data.title} — Sakura AI` : 'Shared Chat — Sakura AI'}</title>
      </Head>

      {/* Top Bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between px-6 py-3.5 bg-[#0D0D0D]/90 backdrop-blur-md border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <Link href="/console" className="flex items-center gap-2.5 group">
            <SakuraLogo size={26} alt="Sakura AI" />
            <span className="font-semibold text-[15px] tracking-wide text-white font-sans">
              SAKURA AI
            </span>
          </Link>
          <span className="text-[12px] font-mono px-2 py-0.5 rounded-full bg-white/[0.05] text-[#8E8E8E] border border-white/[0.06]">
            Shared Snapshot
          </span>
        </div>

        <Link
          href="/console"
          className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-white text-black text-[13px] font-medium hover:bg-[#E0E0E0] transition-colors cursor-pointer"
        >
          <MessageSquare className="w-4 h-4" />
          <span>Chat with Sakura</span>
        </Link>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-3xl w-full mx-auto px-6 py-10 flex flex-col">
        {loading ? (
          <div className="flex-1 flex flex-col items-center justify-center py-32 gap-3">
            <Loader2 className="w-7 h-7 animate-spin text-white/50" />
            <span className="text-[13px] text-[#888888]">Loading shared conversation...</span>
          </div>
        ) : error ? (
          <div className="flex-1 flex flex-col items-center justify-center py-32 text-center">
            <div className="w-12 h-12 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center text-red-400 mb-4">
              <AlertCircle className="w-6 h-6" />
            </div>
            <h2 className="text-[18px] font-semibold text-white mb-2">Conversation Unavailable</h2>
            <p className="text-[13.5px] text-[#888888] max-w-md mb-6">{error}</p>
            <Link
              href="/console"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-white/[0.08] hover:bg-white/[0.12] text-white text-[13px] font-medium transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Return to Sakura AI</span>
            </Link>
          </div>
        ) : data ? (
          <div className="space-y-8">
            <div className="border-b border-white/[0.06] pb-6">
              <h1 className="text-[24px] font-semibold text-white tracking-tight mb-2">
                {data.title}
              </h1>
              {data.created_at && (
                <p className="text-[12.5px] text-[#777777]">
                  Shared on {new Date(data.created_at).toLocaleDateString(undefined, {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric'
                  })}
                </p>
              )}
            </div>

            <div className="space-y-6">
              {data.messages.map((m, idx) => (
                <div key={m.id || idx}>
                  {m.role === 'user' ? (
                    <div className="flex justify-end">
                      <div className="bg-[#212121] border border-white/[0.06] text-white px-5 py-3 rounded-2xl max-w-[80%] text-[15px] leading-relaxed">
                        {m.content}
                      </div>
                    </div>
                  ) : (
                    <div className="flex gap-3.5">
                      <div className="flex-shrink-0 mt-0.5">
                        <SakuraLogo size={22} alt="Sakura" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[15px] text-[#ECECEC] leading-relaxed whitespace-pre-wrap">
                          {m.content}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </main>

      {/* Footer */}
      <footer className="py-6 border-t border-white/[0.04] text-center text-[12px] text-[#666666]">
        Powered by Sakura AI — Frontier Software Engineering & Multimodal Assistant
      </footer>
    </div>
  );
}
