import { useState, useEffect, useCallback, useRef } from 'react';
import { authFetch } from '../lib/auth';
import { ChatSubmitPayload } from '../components/ChatComposer';

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at?: string;
  is_pinned?: boolean;
  character_id?: string;
}

export interface ChatMessage {
  id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
  metadata?: {
    tools?: string[];
    attachments?: any[];
    intensity?: string;
    model?: string;
    provider?: string;
    tool_calls?: any[];
    diff?: any;
    verification?: any;
  };
}

export function useConversation() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingResponse, setStreamingResponse] = useState<string>('');
  const [streamingProvider, setStreamingProvider] = useState<string>('');
  const [loadingResponse, setLoadingResponse] = useState<boolean>(false);
  const [feedbackState, setFeedbackState] = useState<Record<string, 'positive' | 'negative'>>({});
  const abortControllerRef = useRef<AbortController | null>(null);

  const activeConversation = conversations.find(c => c.id === activeConvId) || null;

  const fetchConversations = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/conversations');
      if (res.ok) {
        const data = await res.json();
        setConversations(data);
        if (data.length > 0 && !activeConvId) {
          selectConversation(data[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to fetch conversations:', err);
    }
  }, [activeConvId]);

  const selectConversation = useCallback(async (id: string) => {
    setActiveConvId(id);
    setMessages([]);
    setStreamingResponse('');
    setStreamingProvider('');
    try {
      const res = await authFetch(`/api/v1/conversations/${id}/messages`);
      if (res.ok) {
        const msgs = await res.json();
        setMessages(msgs);
      }
    } catch (err) {
      console.error(`Failed to load messages for conversation ${id}:`, err);
    }
  }, []);

  const createNewConversation = useCallback(() => {
    setActiveConvId(null);
    setMessages([]);
    setStreamingResponse('');
    setStreamingProvider('');
  }, []);

  const sendMessage = useCallback(async (payload: ChatSubmitPayload) => {
    if ((!payload.message.trim() && payload.attachments.length === 0) || loadingResponse) return;

    let cid = activeConvId;
    if (!cid) {
      try {
        const createRes = await authFetch('/api/v1/conversations?character_id=sakura', { method: 'POST' });
        if (createRes.ok) {
          const newConv = await createRes.json();
          setConversations(prev => [newConv, ...prev]);
          setActiveConvId(newConv.id);
          cid = newConv.id;
        } else {
          return;
        }
      } catch (err) {
        console.error('Failed to create new conversation:', err);
        return;
      }
    }

    const userText = payload.message;
    setStreamingResponse('');
    setStreamingProvider('');
    setLoadingResponse(true);

    const userMessage: ChatMessage = {
      role: 'user',
      content: userText,
      metadata: {
        tools: payload.tools,
        attachments: payload.attachments,
        intensity: payload.intensity
      }
    };

    setMessages(prev => [...prev, userMessage]);

    const ctrl = new AbortController();
    abortControllerRef.current = ctrl;

    try {
      const streamRes = await authFetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: cid,
          message: userText,
          intensity: payload.intensity,
          tools: payload.tools,
          attachments: payload.attachments,
          active_workspace_id: payload.active_workspace_id || null
        }),
        signal: ctrl.signal
      });

      if (!streamRes.ok) throw new Error(`Chat stream failed (HTTP ${streamRes.status})`);

      const reader = streamRes.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) return;

      let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('data: ')) {
            try {
              const data = JSON.parse(trimmed.slice(6));
              if (data.token) setStreamingResponse(prev => prev + data.token);
              if (data.provider) setStreamingProvider(data.provider);
            } catch {}
          }
        }
      }

      await selectConversation(cid!);
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        console.error('Error in chat stream:', err);
      }
    } finally {
      setLoadingResponse(false);
      abortControllerRef.current = null;
    }
  }, [activeConvId, loadingResponse, selectConversation]);

  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  }, []);

  const provideFeedback = useCallback(async (msg: ChatMessage, index: number, rating: 'positive' | 'negative') => {
    const key = msg.id || String(index);
    setFeedbackState(prev => ({ ...prev, [key]: rating }));
    if (!msg.id) return;
    try {
      await authFetch(`/api/v1/messages/${msg.id}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating })
      });
    } catch (err) {
      console.error('Feedback error:', err);
    }
  }, []);

  const togglePin = useCallback(async (id: string, currentlyPinned: boolean) => {
    const action = currentlyPinned ? 'unpin' : 'pin';
    setConversations(prev =>
      prev.map(c => (c.id === id ? { ...c, is_pinned: !currentlyPinned } : c))
    );
    try {
      await authFetch(`/api/v1/conversations/${id}/${action}`, { method: 'POST' });
    } catch (err) {
      console.error(`Failed to ${action} conversation:`, err);
    }
  }, []);

  const renameConversation = useCallback(async (id: string, title: string) => {
    setConversations(prev =>
      prev.map(c => (c.id === id ? { ...c, title } : c))
    );
    try {
      await authFetch(`/api/v1/conversations/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
      });
    } catch (err) {
      console.error('Failed to rename conversation:', err);
    }
  }, []);

  const deleteConversation = useCallback(async (id: string) => {
    setConversations(prev => prev.filter(c => c.id !== id));
    if (activeConvId === id) {
      createNewConversation();
    }
    try {
      await authFetch(`/api/v1/conversations/${id}`, { method: 'DELETE' });
    } catch (err) {
      console.error('Failed to delete conversation:', err);
    }
  }, [activeConvId, createNewConversation]);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  return {
    conversations,
    activeConvId,
    activeConversation,
    messages,
    streamingResponse,
    streamingProvider,
    loadingResponse,
    feedbackState,
    fetchConversations,
    selectConversation,
    createNewConversation,
    sendMessage,
    stopGeneration,
    provideFeedback,
    togglePin,
    renameConversation,
    deleteConversation,
    setConversations
  };
}
