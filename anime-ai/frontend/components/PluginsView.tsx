import React, { useState, useEffect } from 'react';
import { 
  Compass, Check, Settings, ExternalLink, ShieldCheck, 
  Code2, Database, Globe, Image, Mic, FileSearch, Loader2, Sparkles
} from 'lucide-react';
import { ConnectAppsModal } from './ConnectAppsModal';

interface IntegrationStatus {
  id: string;
  name: string;
  category: string;
  description: string;
  is_connected: boolean;
  account_name: string | null;
  connected_at: string | null;
}

interface PluginsViewProps {
  apiBase?: string;
}

export const PluginsView: React.FC<PluginsViewProps> = ({
  apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
}) => {
  const [integrations, setIntegrations] = useState<IntegrationStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [isConnectModalOpen, setIsConnectModalOpen] = useState(false);

  const getAuthToken = () => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('token') || '';
    }
    return '';
  };

  const fetchIntegrations = async () => {
    try {
      setLoading(true);
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/integrations`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setIntegrations(data);
      }
    } catch (err) {
      console.error('Failed to load integrations:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIntegrations();
  }, []);

  const BUILTIN_CAPABILITIES = [
    {
      id: 'sakura_code',
      name: 'Sakura Frontier Coding Engine',
      category: 'Core Engineering',
      description: 'Isolated subprocess execution, syntax validation AST parsing, unified diff patching, and test verification.',
      status: 'Active',
      icon: <Code2 className="w-5 h-5 text-emerald-400" />
    },
    {
      id: 'image_gen',
      name: 'Multimodal Image & Lineage Engine',
      category: 'Visual AI',
      description: 'High-fidelity raster image generation, iterative multi-turn editing lineage tree, and upscaling.',
      status: 'Active',
      icon: <Image className="w-5 h-5 text-purple-400" />
    },
    {
      id: 'rag_engine',
      name: 'Hybrid RAG Document Search',
      category: 'Knowledge Base',
      description: 'Lexical BM25 and dense vector retrieval across uploaded PDF, DOCX, TXT, and source files.',
      status: 'Active',
      icon: <FileSearch className="w-5 h-5 text-blue-400" />
    },
    {
      id: 'web_search',
      name: 'Live Web Research Agent',
      category: 'Information Gathering',
      description: 'Real-time multi-query web search, citation extraction, and cross-reference synthesis.',
      status: 'Active',
      icon: <Globe className="w-5 h-5 text-amber-400" />
    },
    {
      id: 'audio_tts',
      name: 'Voice & Audio Synthesizer',
      category: 'Multimodal Speech',
      description: 'Local and cloud Whisper transcription paired with expressive neural speech synthesis.',
      status: 'Active',
      icon: <Mic className="w-5 h-5 text-rose-400" />
    }
  ];

  return (
    <div className="flex-1 flex flex-col h-full bg-[#121212] text-[#ECECEC] overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 z-20 flex items-center justify-between px-8 py-4 bg-[#121212]/95 backdrop-blur-md border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
            <Compass className="w-4 h-4" />
          </div>
          <div>
            <h1 className="text-[18px] font-semibold text-white tracking-tight">Plugins & Capabilities</h1>
            <p className="text-[12px] text-[#8E8E8E]">
              Core subsystems, third-party connectors, and toolchain integrations active in Sakura AI
            </p>
          </div>
        </div>

        <button
          onClick={() => setIsConnectModalOpen(true)}
          className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-white text-black text-[13px] font-medium hover:bg-[#E0E0E0] active:scale-[0.98] transition-all cursor-pointer shadow-sm"
        >
          <Settings className="w-4 h-4" />
          <span>Manage Connectors</span>
        </button>
      </div>

      <div className="max-w-5xl w-full mx-auto p-8 space-y-10 flex-1">
        {/* Built-in Subsystems */}
        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-white/70" />
            <h2 className="text-[15px] font-medium text-white">Frontier Native Engines</h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {BUILTIN_CAPABILITIES.map((plugin) => (
              <div
                key={plugin.id}
                className="bg-[#181818] border border-white/[0.06] rounded-2xl p-5 flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-start justify-between mb-3">
                    <div className="w-10 h-10 rounded-xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center">
                      {plugin.icon}
                    </div>
                    <span className="flex items-center gap-1.5 text-[11px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      {plugin.status}
                    </span>
                  </div>
                  <h3 className="text-[15px] font-medium text-white mb-1">{plugin.name}</h3>
                  <p className="text-[12.5px] text-[#888888] leading-relaxed mb-4">{plugin.description}</p>
                </div>
                <div className="text-[11.5px] text-[#666666] pt-3 border-t border-white/[0.04] flex items-center justify-between">
                  <span>{plugin.category}</span>
                  <span className="flex items-center gap-1 text-white/60">
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                    Verified Sandbox
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Third-party Integrations */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4 text-white/70" />
              <h2 className="text-[15px] font-medium text-white">External Service Connectors</h2>
            </div>
          </div>

          {loading ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <Loader2 className="w-5 h-5 animate-spin text-white/50" />
              <span className="text-[12.5px] text-[#8E8E8E]">Loading connectors...</span>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {integrations.map((item) => (
                <div
                  key={item.id}
                  className="bg-[#181818] border border-white/[0.06] rounded-2xl p-5 flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="text-[14px] font-medium text-white">{item.name}</h4>
                      <span className={`text-[10.5px] font-mono px-2 py-0.5 rounded-full border ${
                        item.is_connected
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                          : 'bg-white/[0.04] text-[#666666] border-white/[0.06]'
                      }`}>
                        {item.is_connected ? 'CONNECTED' : 'DISCONNECTED'}
                      </span>
                    </div>
                    <p className="text-[12px] text-[#888888] line-clamp-2 leading-relaxed mb-4">
                      {item.description}
                    </p>
                  </div>

                  <div className="pt-3 border-t border-white/[0.04] flex items-center justify-between">
                    <span className="text-[11px] text-[#666666]">{item.category}</span>
                    <button
                      onClick={() => setIsConnectModalOpen(true)}
                      className="text-[12px] text-blue-400 hover:text-blue-300 font-medium transition-colors cursor-pointer"
                    >
                      {item.is_connected ? 'Manage' : 'Connect'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Connect modal */}
      {isConnectModalOpen && (
        <ConnectAppsModal
          isOpen={isConnectModalOpen}
          onClose={() => {
            setIsConnectModalOpen(false);
            fetchIntegrations();
          }}
          apiBase={apiBase}
        />
      )}
    </div>
  );
};
