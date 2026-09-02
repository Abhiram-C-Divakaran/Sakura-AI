import React, { useState } from 'react';

export interface AppConnector {
  id: string;
  name: string;
  category: string;
  description: string;
  iconSvg: JSX.Element;
  connected: boolean;
}

const DEFAULT_CONNECTORS: AppConnector[] = [
  {
    id: 'github',
    name: 'GitHub',
    category: 'Development',
    description: 'Sync repositories, inspect pull requests, and commit code directly.',
    connected: true,
    iconSvg: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
        <path d="M9 18c-4.51 2-5-2-7-2" />
      </svg>
    )
  },
  {
    id: 'google_drive',
    name: 'Google Drive',
    category: 'Productivity',
    description: 'Access Docs, Sheets, Presentations, and cloud storage files.',
    connected: false,
    iconSvg: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 2v20" />
        <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
      </svg>
    )
  },
  {
    id: 'notion',
    name: 'Notion',
    category: 'Knowledge',
    description: 'Search pages, retrieve database rows, and sync meeting notes.',
    connected: false,
    iconSvg: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M4 4v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2Z" />
        <path d="M9 9h6" />
        <path d="M9 13h6" />
        <path d="M9 17h4" />
      </svg>
    )
  },
  {
    id: 'slack',
    name: 'Slack',
    category: 'Communication',
    description: 'Read channels, synthesize threads, and post automated digests.',
    connected: false,
    iconSvg: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect width="3" height="8" x="13" y="2" rx="1.5" />
        <path d="M19 8.5V10h1.5A1.5 1.5 0 1 0 19 8.5" />
        <rect width="3" height="8" x="8" y="14" rx="1.5" />
        <path d="M5 15.5V14H3.5A1.5 1.5 0 1 0 5 15.5" />
      </svg>
    )
  },
  {
    id: 'postgres',
    name: 'PostgreSQL',
    category: 'Database',
    description: 'Execute analytical read queries and inspect table schemas live.',
    connected: true,
    iconSvg: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M3 5v14a9 3 0 0 0 18 0V5" />
        <path d="M3 12a9 3 0 0 0 18 0" />
      </svg>
    )
  },
  {
    id: 'jira',
    name: 'Jira / Linear',
    category: 'Project Tracking',
    description: 'Track roadmap tickets, backlog tasks, and sprint statuses.',
    connected: false,
    iconSvg: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 2v20" />
        <path d="m19 9-7 7-7-7" />
      </svg>
    )
  }
];

interface ConnectAppsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ConnectAppsModal: React.FC<ConnectAppsModalProps> = ({ isOpen, onClose }) => {
  const [connectors, setConnectors] = useState<AppConnector[]>(DEFAULT_CONNECTORS);

  if (!isOpen) return null;

  const toggleConnect = (id: string) => {
    setConnectors((prev) =>
      prev.map((c) => (c.id === id ? { ...c, connected: !c.connected } : c))
    );
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="connect-apps-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div className="bg-[#1C1C1C] border border-[#333333] rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="p-4 border-b border-[#2C2C2C] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#2A2A2A] flex items-center justify-center text-[#35D0BA]">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect width="7" height="7" x="3" y="3" rx="1.5" />
                <rect width="7" height="7" x="14" y="3" rx="1.5" />
                <rect width="7" height="7" x="14" y="14" rx="1.5" />
                <rect width="7" height="7" x="3" y="14" rx="1.5" />
              </svg>
            </div>
            <div>
              <h3 id="connect-apps-title" className="text-[15px] font-semibold text-white">
                Connect External Apps & Skills
              </h3>
              <p className="text-[11.5px] text-[#888888]">
                Grant Sakura AI permission to pull data from your integrated services
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-[#888888] hover:text-white hover:bg-[#2A2A2A] rounded-lg transition-colors cursor-pointer"
            aria-label="Close connect apps modal"
          >
            ✕
          </button>
        </div>

        {/* Connectors List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2.5">
          {connectors.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between p-3 bg-[#222222] border border-[#2E2E2E] rounded-xl hover:border-[#3E3E3E] transition-colors"
            >
              <div className="flex items-center gap-3.5 min-w-0 flex-1">
                <div className="w-10 h-10 rounded-xl bg-[#181818] border border-[#333333] flex items-center justify-center flex-shrink-0 text-white">
                  {c.iconSvg}
                </div>
                <div className="flex flex-col min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13.5px] font-medium text-white">{c.name}</span>
                    <span className="text-[10px] font-mono text-[#777777] bg-[#161616] px-1.5 py-0.5 rounded border border-[#2A2A2A]">
                      {c.category}
                    </span>
                  </div>
                  <span className="text-[11.5px] text-[#999999] truncate mt-0.5">
                    {c.description}
                  </span>
                </div>
              </div>

              <button
                type="button"
                onClick={() => toggleConnect(c.id)}
                className={`ml-4 px-3 py-1.5 text-[12px] font-medium rounded-lg transition-all cursor-pointer flex-shrink-0 ${
                  c.connected
                    ? 'bg-[#1C2C26] text-[#35D0BA] border border-[#35D0BA]/30 hover:bg-[#223930]'
                    : 'bg-[#2A2A2A] text-[#CCCCCC] hover:bg-[#383838] hover:text-white'
                }`}
              >
                {c.connected ? 'Connected' : 'Connect'}
              </button>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="p-3 bg-[#161616] border-t border-[#282828] flex items-center justify-between text-[11.5px] text-[#888888]">
          <span>All connections are encrypted with AES-256 tokens</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-black bg-white hover:bg-[#E5E5E5] font-medium rounded-lg transition-colors cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
