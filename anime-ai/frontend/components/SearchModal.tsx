import React, { useState, useEffect, useRef } from 'react';
import { authFetch } from '../lib/auth';

export interface SearchResult {
  conversation_id: string;
  title: string;
  match_type: 'title' | 'message';
  snippet: string;
  updated_at?: string | null;
}

export interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectConversation: (conversationId: string) => void;
  initialQuery?: string;
}

export const SearchModal: React.FC<SearchModalProps> = ({
  isOpen,
  onClose,
  onSelectConversation,
  initialQuery = ''
}) => {
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setQuery(initialQuery);
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen, initialQuery]);

  useEffect(() => {
    if (!isOpen) return;

    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const res = await authFetch(`/api/v1/conversations/search?q=${encodeURIComponent(trimmed)}`);
        if (res.ok) {
          const data = await res.json();
          setResults(Array.isArray(data) ? data : []);
        } else {
          setResults([]);
        }
        setSelectedIndex(0);
      } catch (err) {
        console.error('Search failed:', err);
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [query, isOpen]);

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => (prev + 1 < results.length ? prev + 1 : prev));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => (prev > 0 ? prev - 1 : 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (results[selectedIndex]) {
        onSelectConversation(results[selectedIndex].conversation_id);
        onClose();
      }
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-black/60 backdrop-blur-sm p-4 animate-fade-in"
      onClick={onClose}
      onKeyDown={handleKeyDown}
    >
      <div
        className="relative w-full max-w-2xl bg-zinc-900 border border-zinc-700/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[75vh]"
        onClick={e => e.stopPropagation()}
      >
        {/* Search header & input */}
        <div className="flex items-center px-4 py-3.5 border-b border-zinc-800 gap-3 bg-zinc-900/90">
          <svg className="w-5 h-5 text-zinc-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            className="flex-1 bg-transparent text-zinc-100 placeholder-zinc-500 text-base outline-none"
            placeholder="Search conversations and messages..."
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          {loading && (
            <div className="w-4 h-4 border-2 border-pink-500 border-t-transparent rounded-full animate-spin shrink-0" />
          )}
          {query && !loading && (
            <button
              onClick={() => setQuery('')}
              className="text-zinc-500 hover:text-zinc-300 text-xs px-1.5 py-0.5 rounded"
            >
              Clear
            </button>
          )}
          <kbd className="hidden sm:inline-block px-2 py-0.5 text-xs text-zinc-400 bg-zinc-800 border border-zinc-700 rounded-md">
            ESC
          </kbd>
        </div>

        {/* Results container */}
        <div className="flex-1 overflow-y-auto p-2 divide-y divide-zinc-800/40">
          {query.trim() === '' ? (
            <div className="p-8 text-center text-zinc-500 text-sm">
              Type to search conversations by title or message content.
            </div>
          ) : results.length === 0 && !loading ? (
            <div className="p-8 text-center text-zinc-500 text-sm">
              No matching conversations found for &quot;{query}&quot;.
            </div>
          ) : (
            results.map((result, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <div
                  key={`${result.conversation_id}-${idx}`}
                  onClick={() => {
                    onSelectConversation(result.conversation_id);
                    onClose();
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`p-3 rounded-xl cursor-pointer transition-colors duration-150 flex flex-col gap-1 ${
                    isSelected ? 'bg-zinc-800/90 text-white' : 'hover:bg-zinc-800/50 text-zinc-300'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 font-medium text-sm text-zinc-100 truncate">
                      <svg className="w-4 h-4 text-pink-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                      </svg>
                      <span className="truncate">{result.title}</span>
                    </div>
                    <span className={`text-[10px] uppercase font-semibold px-2 py-0.5 rounded-full shrink-0 ${
                      result.match_type === 'title'
                        ? 'bg-pink-500/20 text-pink-300 border border-pink-500/30'
                        : 'bg-zinc-700/50 text-zinc-400 border border-zinc-600/30'
                    }`}>
                      {result.match_type}
                    </span>
                  </div>
                  {result.snippet && (
                    <p className="text-xs text-zinc-400 line-clamp-2 pl-6 font-normal">
                      {result.snippet}
                    </p>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="px-4 py-2 bg-zinc-950/60 border-t border-zinc-800 text-[11px] text-zinc-500 flex items-center justify-between">
          <span>Navigate with &uarr;&darr;</span>
          <span>Press Enter to select</span>
        </div>
      </div>
    </div>
  );
};
