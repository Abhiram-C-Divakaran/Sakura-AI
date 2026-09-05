import React, { useState, useEffect } from 'react';
import { 
  Compass, Check, Settings, ExternalLink, ShieldCheck, 
  Code2, Database, Globe, Image, Mic, FileSearch, Loader2, Sparkles, AlertCircle
} from 'lucide-react';
import { ConnectAppsModal } from './ConnectAppsModal';
import { authFetch } from '../lib/auth';

export interface IntegrationStatus {
  id: string;
  name: string;
  category: string;
  description: string;
  state: 'NOT_CONFIGURED' | 'DISCONNECTED' | 'AUTHORIZING' | 'CONNECTED' | 'ERROR';
  connected: boolean;
  account_name: string | null;
  connected_at: string | null;
  updated_at: string | null;
  capabilities: string[];
  is_implemented?: boolean;
}

interface CapabilitiesResponse {
  status: string;
  environment?: string;
  sandbox?: {
    available: boolean;
    runtime: string;
    isolation_level: string;
    production_safe: boolean;
    reason?: string;
  };
  subsystems?: {
    sakura_code?: {
      status: string;
      isolation_level: string;
      production_safe: boolean;
      verified_sandbox: boolean;
    };
    image_gen?: {
      status: string;
      provider: string;
      model: string;
      editing_available: boolean;
      upscale_available: boolean;
    };
    rag_engine?: {
      status: string;
      dense_embeddings: boolean;
      lexical_bm25: boolean;
      retrieval_mode: string;
    };
    web_search?: {
      status: string;
      provider: string;
      has_api_key: boolean;
    };
    audio_tts?: {
      status: string;
      whisper_provider: string | null;
    };
  };
}

interface PluginsViewProps {
  apiBase?: string;
}

export const PluginsView: React.FC<PluginsViewProps> = ({
  apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
}) => {
  const [integrations, setIntegrations] = useState<IntegrationStatus[]>([]);
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [isConnectModalOpen, setIsConnectModalOpen] = useState(false);

  const fetchStatusAndCapabilities = async () => {
    try {
      setLoading(true);
      const [intRes, capRes] = await Promise.all([
        authFetch(`${apiBase}/api/v1/integrations`),
        fetch(`${apiBase}/api/v1/capabilities`)
      ]);

      if (intRes.ok) {
        const intData = await intRes.json();
        setIntegrations(intData);
      }

      if (capRes.ok) {
        const capData = await capRes.json();
        setCapabilities(capData);
      }
    } catch (err) {
      console.error('Failed to load plugins or capabilities:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatusAndCapabilities();
  }, [apiBase]);

  // Derive truthful engine attributes from live backend capability response
  const sub = capabilities?.subsystems;
  const isVerifiedSandbox = Boolean(sub?.sakura_code?.verified_sandbox);
  const sandboxIsolation = sub?.sakura_code?.isolation_level || 'host_restricted';
  const sandboxStatus = sub?.sakura_code?.status || 'DEGRADED';

  const ragMode = sub?.rag_engine?.retrieval_mode === 'hybrid_rrf'
    ? 'Hybrid RAG (Dense vector embeddings + Okapi BM25 ranking via RRF)'
    : 'Knowledge Base search (True Okapi BM25 lexical ranking)';

  const searchProvider = sub?.web_search?.provider === 'tavily'
    ? 'Tavily Search API with structured citations'
    : 'DuckDuckGo live web search fallback';

  const builtinEngines = [
    {
      id: 'sakura_code',
      name: 'Sakura Frontier Coding Engine',
      category: 'Core Engineering',
      description: `Autonomous repository coding engine. Isolation level: ${sandboxIsolation}. AST patching, multi-file synthesis, and verified test execution.`,
      status: sandboxStatus === 'AVAILABLE' ? 'Active' : (sandboxStatus === 'DEGRADED' ? 'Local Sandbox' : 'Unavailable'),
      statusLevel: sandboxStatus,
      isVerified: isVerifiedSandbox,
      icon: <Code2 className="w-5 h-5 text-emerald-400" />
    },
    {
      id: 'image_gen',
      name: 'Multimodal Image & Lineage Engine',
      category: 'Visual AI',
      description: 'High-fidelity Pollinations Flux neural rendering, multi-turn editing lineage tree, and resolution upscaling.',
      status: sub?.image_gen?.status === 'AVAILABLE' ? 'Active' : 'Unavailable',
      statusLevel: sub?.image_gen?.status || 'UNKNOWN',
      isVerified: false,
      icon: <Image className="w-5 h-5 text-purple-400" />
    },
    {
      id: 'rag_engine',
      name: 'Knowledge Base & Retrieval Engine',
      category: 'RAG Retrieval',
      description: ragMode,
      status: sub?.rag_engine?.status === 'AVAILABLE' ? 'Active' : 'Unavailable',
      statusLevel: sub?.rag_engine?.status || 'UNKNOWN',
      isVerified: false,
      icon: <FileSearch className="w-5 h-5 text-blue-400" />
    },
    {
      id: 'web_search',
      name: 'Live Web Research Subsystem',
      category: 'Information Gathering',
      description: `Real-time web research engine using ${searchProvider}.`,
      status: sub?.web_search?.status === 'AVAILABLE' ? 'Active' : 'Unavailable',
      statusLevel: sub?.web_search?.status || 'UNKNOWN',
      isVerified: false,
      icon: <Globe className="w-5 h-5 text-amber-400" />
    },
    {
      id: 'audio_tts',
      name: 'Voice & Speech Transcription',
      category: 'Multimodal Speech',
      description: sub?.audio_tts?.status === 'AVAILABLE' 
        ? 'Whisper transcription paired with natural speech synthesis.' 
        : 'Whisper audio transcription (Requires configured Groq or OpenAI API key).',
      status: sub?.audio_tts?.status === 'AVAILABLE' ? 'Active' : 'Not Configured',
      statusLevel: sub?.audio_tts?.status || 'NOT_CONFIGURED',
      isVerified: false,
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
            {builtinEngines.map((plugin) => (
              <div
                key={plugin.id}
                className="bg-[#181818] border border-white/[0.06] rounded-2xl p-5 flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-start justify-between mb-3">
                    <div className="w-10 h-10 rounded-xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center">
                      {plugin.icon}
                    </div>
                    <span className={`flex items-center gap-1.5 text-[11px] font-mono px-2 py-0.5 rounded-full border ${
                      plugin.statusLevel === 'AVAILABLE'
                        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                        : plugin.statusLevel === 'DEGRADED'
                        ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                        : 'bg-white/[0.04] text-[#888888] border-white/[0.06]'
                    }`}>
                      {plugin.statusLevel === 'AVAILABLE' && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      )}
                      {plugin.status}
                    </span>
                  </div>
                  <h3 className="text-[15px] font-medium text-white mb-1">{plugin.name}</h3>
                  <p className="text-[12.5px] text-[#888888] leading-relaxed mb-4">{plugin.description}</p>
                </div>
                <div className="text-[11.5px] text-[#666666] pt-3 border-t border-white/[0.04] flex items-center justify-between">
                  <span>{plugin.category}</span>
                  {plugin.isVerified ? (
                    <span className="flex items-center gap-1 text-emerald-400">
                      <ShieldCheck className="w-3.5 h-3.5" />
                      Verified Sandbox
                    </span>
                  ) : plugin.id === 'sakura_code' ? (
                    <span className="text-[#888888] font-mono text-[11px]">
                      Local Host Sandbox
                    </span>
                  ) : null}
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
              {integrations.map((item) => {
                const isSupported = item.is_implemented !== false;
                return (
                  <div
                    key={item.id}
                    className="bg-[#181818] border border-white/[0.06] rounded-2xl p-5 flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="text-[14px] font-medium text-white">{item.name}</h4>
                        <span className={`text-[10.5px] font-mono px-2 py-0.5 rounded-full border ${
                          !isSupported
                            ? 'bg-white/[0.04] text-[#888888] border-white/[0.08]'
                            : item.connected
                            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                            : item.state === 'DISCONNECTED'
                            ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                            : 'bg-white/[0.04] text-[#666666] border-white/[0.06]'
                        }`}>
                          {!isSupported
                            ? 'COMING SOON'
                            : (item.connected ? 'CONNECTED' : (item.state === 'DISCONNECTED' ? 'DISCONNECTED' : 'NOT CONFIGURED'))}
                        </span>
                      </div>
                      <p className="text-[12px] text-[#888888] line-clamp-2 leading-relaxed mb-4">
                        {item.description}
                      </p>
                      {item.connected && item.account_name && (
                        <div className="mb-3 text-[11px] text-[#35D0BA] font-mono">
                          Account: @{item.account_name}
                        </div>
                      )}
                    </div>

                    <div className="pt-3 border-t border-white/[0.04] flex items-center justify-between">
                      <span className="text-[11px] text-[#666666]">{item.category}</span>
                      {isSupported ? (
                        <button
                          onClick={() => setIsConnectModalOpen(true)}
                          className="text-[12px] text-blue-400 hover:text-blue-300 font-medium transition-colors cursor-pointer"
                        >
                          {item.connected ? 'Manage' : (item.state === 'NOT_CONFIGURED' ? 'Setup' : 'Connect')}
                        </button>
                      ) : (
                        <span className="text-[11.5px] text-[#666666] font-medium">
                          Coming Soon
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
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
            fetchStatusAndCapabilities();
          }}
          apiBase={apiBase}
        />
      )}
    </div>
  );
};
