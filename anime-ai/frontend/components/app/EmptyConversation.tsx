import React from 'react';
import { Terminal, BookOpen, Sparkles, FolderGit2, ArrowUpRight } from 'lucide-react';
import { SakuraLogo } from '../SakuraLogo';

export interface EmptyConversationProps {
  onSelectPrompt: (promptText: string) => void;
}

export const EmptyConversation: React.FC<EmptyConversationProps> = ({ onSelectPrompt }) => {
  const starterPrompts = [
    {
      title: 'Analyze Repository Codebase',
      description: 'Audit project structure, dependency hygiene, and isolated architecture.',
      icon: <FolderGit2 className="w-4 h-4 text-[#ff7597]" />,
      prompt: 'Analyze the repository architecture and verify key modules and interfaces.'
    },
    {
      title: 'Execute Isolated Sandbox Tests',
      description: 'Run automated unit and integration tests inside dedicated Docker sandbox.',
      icon: <Terminal className="w-4 h-4 text-emerald-400" />,
      prompt: 'Run the test suite inside the isolated sandbox and summarize results.'
    },
    {
      title: 'Index Documents & Knowledge Base',
      description: 'Durable worker RAG indexing with dense embeddings and BM25 hybrid search.',
      icon: <BookOpen className="w-4 h-4 text-cyan-400" />,
      prompt: 'Index uploaded documents into the knowledge base for semantic retrieval.'
    },
    {
      title: 'Generate High-Detail Image Asset',
      description: 'Produce high-resolution artwork and visual designs with durable object storage.',
      icon: <Sparkles className="w-4 h-4 text-purple-400" />,
      prompt: 'Create a high-detail anime-styled character portrait in a futuristic cyberpunk city.'
    }
  ];

  return (
    <div className="flex flex-col items-center justify-center flex-1 px-4 py-8 max-w-2xl mx-auto text-center animate-in fade-in duration-300">
      {/* Brand Icon */}
      <div className="mb-5 p-3 rounded-2xl bg-gradient-to-b from-white/10 to-transparent border border-white/10 shadow-2xl">
        <SakuraLogo size={44} />
      </div>

      <h1 className="text-2xl font-bold tracking-tight text-white mb-2">
        What would you like to build?
      </h1>
      <p className="text-sm text-neutral-400 max-w-md mb-8 leading-relaxed">
        Sakura AI pairs autonomous coding with truthful system capabilities and durable cloud storage.
      </p>

      {/* Starter Prompts Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full text-left">
        {starterPrompts.map((item, idx) => (
          <button
            key={idx}
            onClick={() => onSelectPrompt(item.prompt)}
            className="group flex flex-col justify-between p-3.5 rounded-xl border border-white/5 bg-[#0a0a0a] hover:bg-[#111111] hover:border-[#ff7597]/30 transition-all text-xs"
          >
            <div className="flex items-start justify-between w-full mb-2">
              <div className="p-1.5 rounded-lg bg-white/5 group-hover:bg-[#ff7597]/10 transition-colors">
                {item.icon}
              </div>
              <ArrowUpRight className="w-3.5 h-3.5 text-neutral-600 group-hover:text-[#ff7597] transition-colors" />
            </div>
            <div>
              <div className="font-semibold text-neutral-200 group-hover:text-white transition-colors mb-0.5">
                {item.title}
              </div>
              <div className="text-[11px] text-neutral-500 leading-snug">
                {item.description}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};
