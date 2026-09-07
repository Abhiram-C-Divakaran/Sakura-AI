import React, { useRef, useEffect } from 'react';
import {
  Copy, Check, ThumbsUp, ThumbsDown, Sparkles, User,
  Bot, RefreshCw, AlertCircle
} from 'lucide-react';
import { ChatMessage } from '../../hooks/useConversation';
import { ChatComposer, ChatSubmitPayload } from '../ChatComposer';
import { EmptyConversation } from './EmptyConversation';
import { CodingActivity } from '../coding/CodingActivity';
import { ToolExecution } from '../coding/ToolExecution';
import { DiffViewer } from '../coding/DiffViewer';
import { VerificationSummary } from '../coding/VerificationSummary';
import { SakuraLogo } from '../SakuraLogo';

export interface ConversationViewProps {
  messages: ChatMessage[];
  streamingResponse: string;
  streamingProvider: string;
  loadingResponse: boolean;
  onSendMessage: (payload: ChatSubmitPayload) => void;
  onStopGeneration: () => void;
  onCopyMessage: (content: string, idx: number) => void;
  copiedIdx: number | null;
  onFeedback: (msg: ChatMessage, idx: number, rating: 'positive' | 'negative') => void;
  feedbackState: Record<string, 'positive' | 'negative'>;
  onSelectPrompt: (prompt: string) => void;
  onImageLightbox?: (src: string, alt: string, meta?: any) => void;
}

export const ConversationView: React.FC<ConversationViewProps> = ({
  messages,
  streamingResponse,
  streamingProvider,
  loadingResponse,
  onSendMessage,
  onStopGeneration,
  onCopyMessage,
  copiedIdx,
  onFeedback,
  feedbackState,
  onSelectPrompt,
  onImageLightbox
}) => {
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingResponse]);

  const isEmpty = messages.length === 0 && !streamingResponse && !loadingResponse;

  return (
    <div className="flex-1 flex flex-col h-full bg-[#000000] relative overflow-hidden">
      {/* Scrollable Message Area */}
      <div className="flex-1 overflow-y-auto sidebar-scroll px-4 md:px-8 py-6 space-y-6">
        {isEmpty ? (
          <EmptyConversation onSelectPrompt={onSelectPrompt} />
        ) : (
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.map((msg, idx) => {
              const isUser = msg.role === 'user';
              const feedbackKey = msg.id || String(idx);
              const currentRating = feedbackState[feedbackKey];

              return (
                <div
                  key={idx}
                  className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} space-y-2`}
                >
                  {/* Avatar & Sender Label */}
                  <div className={`flex items-center gap-2 text-xs text-neutral-400 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
                    {isUser ? (
                      <div className="w-5 h-5 rounded-full bg-neutral-700 flex items-center justify-center text-white text-[10px]">
                        <User className="w-3 h-3" />
                      </div>
                    ) : (
                      <div className="w-5 h-5 rounded-full bg-[#ff7597]/20 flex items-center justify-center text-[#ff7597]">
                        <SakuraLogo size={14} />
                      </div>
                    )}
                    <span className="font-semibold text-neutral-300">
                      {isUser ? 'You' : 'Sakura'}
                    </span>
                    {msg.metadata?.model && (
                      <span className="text-[10px] text-neutral-500 font-mono">
                        {msg.metadata.model}
                      </span>
                    )}
                  </div>

                  {/* Message Bubble */}
                  <div
                    className={`rounded-2xl px-4 py-3 text-sm leading-relaxed max-w-2xl ${
                      isUser
                        ? 'bg-[#181818] text-white border border-white/10 rounded-tr-sm'
                        : 'bg-transparent text-neutral-100 rounded-tl-sm w-full'
                    }`}
                  >
                    <div className="whitespace-pre-wrap break-words">{msg.content}</div>

                    {/* Integrated Coding Activity */}
                    {msg.metadata?.tool_calls && msg.metadata.tool_calls.length > 0 && (
                      <CodingActivity
                        status="completed"
                        tools={msg.metadata.tool_calls}
                        diffText={msg.metadata.diff}
                        verification={msg.metadata.verification}
                      />
                    )}
                  </div>

                  {/* Assistant Actions Bar */}
                  {!isUser && (
                    <div className="flex items-center gap-2 text-neutral-500 text-xs pl-1">
                      <button
                        onClick={() => onCopyMessage(msg.content, idx)}
                        className="flex items-center gap-1 p-1 hover:text-neutral-200 transition-colors"
                        title="Copy message"
                      >
                        {copiedIdx === idx ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                      </button>

                      <button
                        onClick={() => onFeedback(msg, idx, 'positive')}
                        className={`p-1 transition-colors ${currentRating === 'positive' ? 'text-emerald-400' : 'hover:text-neutral-200'}`}
                        title="Helpful"
                      >
                        <ThumbsUp className="w-3.5 h-3.5" />
                      </button>

                      <button
                        onClick={() => onFeedback(msg, idx, 'negative')}
                        className={`p-1 transition-colors ${currentRating === 'negative' ? 'text-rose-400' : 'hover:text-neutral-200'}`}
                        title="Not helpful"
                      >
                        <ThumbsDown className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}
                </div>
              );
            })}

            {/* Live Streaming Response */}
            {(streamingResponse || loadingResponse) && (
              <div className="flex flex-col items-start space-y-2">
                <div className="flex items-center gap-2 text-xs text-neutral-400">
                  <div className="w-5 h-5 rounded-full bg-[#ff7597]/20 flex items-center justify-center text-[#ff7597]">
                    <SakuraLogo size={14} />
                  </div>
                  <span className="font-semibold text-neutral-300">Sakura</span>
                  {streamingProvider && (
                    <span className="text-[10px] text-neutral-500 font-mono">
                      via {streamingProvider}
                    </span>
                  )}
                </div>

                <div className="text-sm leading-relaxed text-neutral-100 w-full pl-7">
                  {streamingResponse ? (
                    <div className="whitespace-pre-wrap break-words">{streamingResponse}</div>
                  ) : (
                    <div className="flex items-center gap-2 text-neutral-500 text-xs py-2">
                      <span className="w-2 h-2 rounded-full bg-[#ff7597] animate-pulse" />
                      <span>Thinking...</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>
        )}
      </div>

      {/* Bottom Composer Container */}
      <div className="shrink-0 p-4 border-t border-white/5 bg-[#000000]">
        <div className="max-w-3xl mx-auto">
          <ChatComposer
            onSendMessage={onSendMessage}
            isGenerating={loadingResponse}
            onStopGeneration={onStopGeneration}
          />
        </div>
      </div>
    </div>
  );
};
