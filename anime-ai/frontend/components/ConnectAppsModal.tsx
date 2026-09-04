import React, { useState, useEffect } from 'react';
import { authFetch } from '../lib/auth';

export interface AppConnector {
  id: string;
  name: string;
  category: string;
  description: string;
  iconSvg: JSX.Element;
  connected: boolean;
  state?: 'NOT_CONFIGURED' | 'DISCONNECTED' | 'AUTHORIZING' | 'CONNECTED' | 'ERROR';
  account_name?: string | null;
  capabilities?: string[];
}

const DEFAULT_CONNECTORS: AppConnector[] = [
  {
    id: 'github',
    name: 'GitHub',
    category: 'Development',
    description: 'Sync repositories, inspect pull requests, and commit code directly.',
    connected: false,
    state: 'NOT_CONFIGURED',
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
    state: 'NOT_CONFIGURED',
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
    state: 'NOT_CONFIGURED',
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
    state: 'NOT_CONFIGURED',
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
    connected: false,
    state: 'NOT_CONFIGURED',
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
    state: 'NOT_CONFIGURED',
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
  apiBase?: string;
}

export const ConnectAppsModal: React.FC<ConnectAppsModalProps> = ({
  isOpen,
  onClose,
  apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
}) => {
  const [connectors, setConnectors] = useState<AppConnector[]>(DEFAULT_CONNECTORS);
  const [loading, setLoading] = useState(false);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    const fetchStatuses = async () => {
      try {
        setLoading(true);
        setErrorMessage(null);
        const res = await authFetch(`${apiBase}/api/v1/integrations`);
        if (res.ok) {
          const data = await res.json();
          const statusMap = new Map<string, any>();
          data.forEach((item: any) => {
            statusMap.set(item.id, item);
          });

          setConnectors((prev) =>
            prev.map((c) => {
              const item = statusMap.get(c.id);
              if (item) {
                return {
                  ...c,
                  connected: Boolean(item.connected),
                  state: item.state,
                  account_name: item.account_name,
                  capabilities: item.capabilities || []
                };
              }
              return c;
            })
          );
        }
      } catch (err) {
        console.error('Failed to fetch connector statuses:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchStatuses();
  }, [isOpen, apiBase]);

  if (!isOpen) return null;

  const toggleConnect = async (c: AppConnector) => {
    setActionInProgress(c.id);
    setErrorMessage(null);
    const willConnect = !c.connected;

    let tokenToSubmit: string | undefined = undefined;

    if (willConnect) {
      if (c.id === 'github') {
        const input = window.prompt(
          'Connect GitHub to Sakura AI:\n\nEnter your GitHub Personal Access Token (classic with "repo" scope or fine-grained token with repository read/write access):'
        );
        if (!input || !input.trim()) {
          setActionInProgress(null);
          return;
        }
        tokenToSubmit = input.trim();
      }
    }

    try {
      if (willConnect) {
        const payload: Record<string, any> = {
          account_name: `${c.name} Workspace`
        };
        if (tokenToSubmit) {
          payload.access_token = tokenToSubmit;
        }

        const res = await authFetch(`${apiBase}/api/v1/integrations/${c.id}/connect`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({ detail: 'Failed to authenticate integration.' }));
          throw new Error(errData.detail || 'Connection failed.');
        }

        const updated = await res.json();
        setConnectors((prev) =>
          prev.map((item) =>
            item.id === c.id
              ? {
                  ...item,
                  connected: Boolean(updated.connected),
                  state: updated.state,
                  account_name: updated.account_name
                }
              : item
          )
        );
      } else {
        const res = await authFetch(`${apiBase}/api/v1/integrations/${c.id}/disconnect`, {
          method: 'POST'
        });
        if (res.ok) {
          const updated = await res.json();
          setConnectors((prev) =>
            prev.map((item) =>
              item.id === c.id
                ? {
                    ...item,
                    connected: false,
                    state: updated.state,
                    account_name: null
                  }
                : item
            )
          );
        }
      }
    } catch (err: any) {
      console.error('Failed to toggle connection on backend:', err);
      setErrorMessage(err.message || 'Action failed');
    } finally {
      setActionInProgress(null);
    }
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

        {errorMessage && (
          <div className="mx-4 mt-3 p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-400 text-[12px] flex items-center gap-2">
            <span>⚠ {errorMessage}</span>
          </div>
        )}

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
                    {c.connected && c.account_name && (
                      <span className="text-[10.5px] font-mono text-[#35D0BA] bg-[#1C2C26] px-1.5 py-0.5 rounded border border-[#35D0BA]/20">
                        @{c.account_name}
                      </span>
                    )}
                  </div>
                  <span className="text-[11.5px] text-[#999999] truncate mt-0.5">
                    {c.description}
                  </span>
                </div>
              </div>

              <button
                type="button"
                disabled={actionInProgress === c.id}
                onClick={() => toggleConnect(c)}
                className={`ml-4 px-3 py-1.5 text-[12px] font-medium rounded-lg transition-all cursor-pointer flex-shrink-0 ${
                  c.connected
                    ? 'bg-[#1C2C26] text-[#35D0BA] border border-[#35D0BA]/30 hover:bg-[#223930]'
                    : c.state === 'NOT_CONFIGURED'
                    ? 'bg-[#252525] text-[#AAAAAA] border border-[#353535] hover:bg-[#303030]'
                    : 'bg-[#2A2A2A] text-white border border-[#383838] hover:bg-[#333333]'
                }`}
              >
                {actionInProgress === c.id 
                  ? 'Updating...' 
                  : c.connected 
                  ? 'Connected ✓' 
                  : (c.state === 'NOT_CONFIGURED' ? 'Setup' : 'Connect')}
              </button>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="p-3.5 border-t border-[#2C2C2C] bg-[#191919] flex items-center justify-between">
          <span className="text-[11px] text-[#666666]">
            Credentials and tokens are encrypted and isolated per user session.
          </span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-[#2A2A2A] hover:bg-[#333333] text-white text-[12.5px] font-medium transition-colors cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
