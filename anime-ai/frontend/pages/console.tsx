import React, { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/router';
import {
  Plus, LogOut, Loader2, ChevronDown, Share, MoreHorizontal,
  Clock, Folder, MessageSquare, Mic, ArrowUp, Search,
  PanelRightClose, PanelRightOpen,
  CheckCircle, Copy, RefreshCw, ThumbsUp, ThumbsDown,
  FileText, ImageIcon, Code, BarChart2, Pencil, Pin, Archive, Trash2,
  ZoomIn, Download, Check, Sparkles, Info, Settings, Moon, HelpCircle, X,
  Compass, Store
} from 'lucide-react';
import { ChatComposer, ChatSubmitPayload } from '../components/ChatComposer';
import { LibraryView } from '../components/LibraryView';
import { ShareModal, DeleteConfirmModal } from '../components/ChatModals';
import { ChatPopoverMenu } from '../components/ChatPopoverMenu';
import { ImageLightboxModal, ImageMetadata } from '../components/ImageLightboxModal';
import { SakuraLogo, SakuraWordmark, SakuraBrandHeader } from '../components/SakuraLogo';
import { ConversationFilesSheet } from '../components/ConversationFilesSheet';

export default function Console() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<string | null>(null);

  const [windowWidth, setWindowWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1200);

  const [sidebarOpen, setSidebarOpen] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('sidebar_open');
      return saved !== null ? JSON.parse(saved) : true;
    }
    return true;
  });

  const [rightOpen, setRightOpen] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('right_panel_open');
      return saved !== null ? JSON.parse(saved) : true;
    }
    return true;
  });

  const [activeTab, setActiveTab] = useState<'agent' | 'memories' | 'files'>('agent');
  const [taskFilter, setTaskFilter] = useState<'ALL' | 'ACTIVE' | 'DONE'>('ALL');

  useEffect(() => {
    localStorage.setItem('sidebar_open', JSON.stringify(sidebarOpen));
  }, [sidebarOpen]);

  useEffect(() => {
    localStorage.setItem('right_panel_open', JSON.stringify(rightOpen));
  }, [rightOpen]);

  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const isDesktop = windowWidth >= 1200;
  const isTablet = windowWidth >= 768 && windowWidth < 1200;
  const isMobile = windowWidth < 768;

  const [wsState, setWsState] = useState<'LIVE' | 'CONNECTING' | 'RECONNECTING' | 'DEGRADED' | 'OFFLINE'>('OFFLINE');
  const [telemetry, setTelemetry] = useState<any>(null);
  const [tasks, setTasks] = useState<any[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<any>(null);
  const [isTabVisible, setIsTabVisible] = useState(true);
  const [secondsSinceUpdate, setSecondsSinceUpdate] = useState(0);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dataPointsRef = useRef<number[]>([]);

  // Modals / Dropdowns / Actions state
  const [showNewTaskModal, setShowNewTaskModal] = useState(false);
  const [newTaskType, setNewTaskType] = useState<'code_analysis' | 'doc_summary' | 'dataset_analysis' | 'web_research'>('code_analysis');
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskPayload, setNewTaskPayload] = useState<any>({});
  const [showContextDetails, setShowContextDetails] = useState(false);
  const [fileSearchQuery, setFileSearchQuery] = useState('');
  const [selectedFileForRename, setSelectedFileForRename] = useState<any | null>(null);
  const [newFileName, setNewFileName] = useState('');
  const [showRenameModal, setShowRenameModal] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  const [conversations, setConversations] = useState<any[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);

  const [messages, setMessages] = useState<any[]>([]);
  const [inputText, setInputText] = useState('');
  const [streamingResponse, setStreamingResponse] = useState('');
  const [streamingProvider, setStreamingProvider] = useState('');
  const [loadingResponse, setLoadingResponse] = useState(false);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  const [activeView, setActiveView] = useState<'chat' | 'library' | 'projects' | 'scheduled' | 'plugins'>('chat');
  const [attachedFromLibrary, setAttachedFromLibrary] = useState<any>(null);
  const [isPinnedCollapsed, setIsPinnedCollapsed] = useState(false);
  const [isRecentsCollapsed, setIsRecentsCollapsed] = useState(false);
  const [editingChatId, setEditingChatId] = useState<string | null>(null);
  const [shareModalChat, setShareModalChat] = useState<{ id: string; title: string } | null>(null);
  const [deleteModalChat, setDeleteModalChat] = useState<{ id: string; title: string } | null>(null);

  // Search & Account modal state
  const [showSearchModal, setShowSearchModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showAccountMenu, setShowAccountMenu] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  // Top-right conversation contextual menu & files sheet
  const [showTopConversationMenu, setShowTopConversationMenu] = useState(false);
  const [showConversationFilesSheet, setShowConversationFilesSheet] = useState(false);
  const topMenuRef = useRef<HTMLDivElement>(null);
  const topMenuButtonRef = useRef<HTMLButtonElement>(null);
  const menuItemsRef = useRef<(HTMLButtonElement | null)[]>([]);

  const handleMenuKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = (index + 1) % 4;
      menuItemsRef.current[next]?.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = (index - 1 + 4) % 4;
      menuItemsRef.current[prev]?.focus();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setShowTopConversationMenu(false);
      topMenuButtonRef.current?.focus();
    }
  };

  // Auto focus first menu item on open
  useEffect(() => {
    if (showTopConversationMenu) {
      setTimeout(() => {
        menuItemsRef.current[0]?.focus();
      }, 50);
    }
  }, [showTopConversationMenu]);

  // Close conversation menu on outside click or Escape
  useEffect(() => {
    if (!showTopConversationMenu) return;
    const handleOutside = (e: MouseEvent) => {
      if (topMenuRef.current && !topMenuRef.current.contains(e.target as Node)) {
        setShowTopConversationMenu(false);
      }
    };
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setShowTopConversationMenu(false);
        topMenuButtonRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', handleOutside);
    window.addEventListener('keydown', handleEsc);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      window.removeEventListener('keydown', handleEsc);
    };
  }, [showTopConversationMenu]);

  // Close conversation menu when active conversation changes
  useEffect(() => {
    setShowTopConversationMenu(false);
  }, [activeConvId]);

  // Keyboard shortcut listener (Ctrl+[ for sidebar, Ctrl+K for search)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '[') {
        e.preventDefault();
        setSidebarOpen(prev => !prev);
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        setShowSearchModal(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const filteredConversations = conversations.filter(c => {
    if (!searchQuery.trim()) return true;
    return (c.title || '').toLowerCase().includes(searchQuery.toLowerCase());
  });

  // Lightbox state for generated images
  const [lightboxState, setLightboxState] = useState<{
    isOpen: boolean;
    url: string;
    altText: string;
    metadata?: ImageMetadata | null;
  }>({
    isOpen: false,
    url: '',
    altText: '',
    metadata: null
  });

  const handleOpenLightbox = (src: string, alt: string, meta?: ImageMetadata | null) => {
    setLightboxState({
      isOpen: true,
      url: src,
      altText: alt,
      metadata: meta || null
    });
  };

  const [editingImage, setEditingImage] = useState<{ id?: string; filename?: string; url?: string; prompt?: string } | null>(null);

  const handleImageEdit = (meta: ImageMetadata) => {
    setEditingImage({
      id: meta.id,
      filename: meta.filename || 'reference_image.png',
      url: meta.url,
      prompt: meta.prompt
    });
    setActiveView('chat');
  };

  const handleImageRegenerate = (promptText: string) => {
    handleSendMessage({
      message: promptText,
      intensity: 'medium',
      tools: ['create_image'],
      attachments: []
    });
  };

  const handleImageVariation = (meta: ImageMetadata) => {
    handleSendMessage({
      message: `Create variations of this image: ${meta.prompt || ''}`,
      intensity: 'medium',
      tools: ['create_image'],
      attachments: meta.id ? [{ id: meta.id, filename: meta.filename || 'parent_image.png', mime_type: 'image/png' }] : []
    });
  };

  const handleImageUpscale = (meta: ImageMetadata) => {
    handleSendMessage({
      message: `Upscale this image to ultra-high resolution: ${meta.prompt || ''}`,
      intensity: 'high',
      tools: ['create_image'],
      attachments: meta.id ? [{ id: meta.id, filename: meta.filename || 'parent_image.png', mime_type: 'image/png' }] : []
    });
  };

  const [systemStatus, setSystemStatus] = useState({ cpu: 24, memory: 56 });

  const [memories, setMemories] = useState<any[]>([]);
  const [documents, setDocuments] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const getHeaders = () => {
    const token = localStorage.getItem('access_token');
    return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
  };

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) { router.push('/login'); return; }
    try { setCurrentUser(JSON.parse(atob(token.split('.')[1])).sub); }
    catch { setCurrentUser('Operator'); }
    try {
      const savedPinnedCollapse = localStorage.getItem('sakura_pinned_collapsed');
      if (savedPinnedCollapse !== null) setIsPinnedCollapsed(JSON.parse(savedPinnedCollapse));
      const savedRecentsCollapse = localStorage.getItem('sakura_recents_collapsed');
      if (savedRecentsCollapse !== null) setIsRecentsCollapsed(JSON.parse(savedRecentsCollapse));
    } catch {}
    fetchConversations(); fetchMemories(); fetchDocuments();
  }, [router]);

  // Tab Visibility handler
  useEffect(() => {
    const handleVisibilityChange = () => {
      setIsTabVisible(!document.hidden);
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  // Track seconds since last update
  useEffect(() => {
    const timer = setInterval(() => {
      if (lastUpdated) {
        setSecondsSinceUpdate(Math.round((new Date().getTime() - lastUpdated.getTime()) / 1000));
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [lastUpdated]);

  // Connect WebSocket with exponential backoff & keepalive
  const connectWS = () => {
    if (!isTabVisible) return;
    const token = localStorage.getItem('access_token');
    if (!token) return;

    setWsState(prev => prev === 'OFFLINE' ? 'CONNECTING' : 'RECONNECTING');

    const wsUrl = apiBase.replace('http', 'ws') + '/api/v1/ws?token=' + token;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    let pingIntv: any;

    ws.onopen = () => {
      setWsState('LIVE');
      setLastUpdated(new Date());
      // Ping keepalive every 10s
      pingIntv = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 10000);
    };

    ws.onmessage = (event) => {
      setLastUpdated(new Date());
      if (event.data === 'pong') return;
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'system_status') {
          setTelemetry(msg.data);
        } else if (msg.type === 'tasks_list') {
          setTasks(msg.data);
        } else if (msg.type === 'task_update') {
          setTasks(prev => {
            const idx = prev.findIndex(t => t.id === msg.data.id);
            if (idx >= 0) {
              const next = [...prev];
              next[idx] = msg.data;
              return next;
            }
            return [msg.data, ...prev];
          });
        } else if (msg.type === 'document_status') {
          fetchDocuments();
        } else if (msg.type === 'conversation_created') {
          const created = msg.data;
          setConversations(prev => [created, ...prev.filter(c => c.id !== created.id)]);
        } else if (msg.type === 'conversation_updated') {
          const updated = msg.data;
          setConversations(prev => prev.map(c => c.id === updated.id ? { ...c, ...updated } : c));
        } else if (msg.type === 'conversation_deleted') {
          setConversations(prev => prev.filter(c => c.id !== msg.id));
        }
      } catch (e) {
        console.error("WS error parsing:", e);
      }
    };

    ws.onclose = () => {
      setWsState('OFFLINE');
      clearInterval(pingIntv);
      if (isTabVisible) {
        reconnectTimeoutRef.current = setTimeout(connectWS, 4000);
      }
    };

    ws.onerror = () => {
      setWsState('DEGRADED');
    };
  };

  useEffect(() => {
    connectWS();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, [isTabVisible]);

  // Telemetry fallback HTTP polling (if websocket is offline)
  useEffect(() => {
    const fetchTelemetryFallback = async () => {
      if (wsState === 'LIVE') return;
      try {
        const token = localStorage.getItem('access_token');
        if (!token) return;
        const res = await fetch(`${apiBase}/api/v1/system/status`, { headers: { 'Authorization': `Bearer ${token}` } });
        if (res.ok) {
          setTelemetry(await res.json());
          setLastUpdated(new Date());
        }
      } catch {}
    };
    fetchTelemetryFallback();
    const intv = setInterval(fetchTelemetryFallback, 5000);
    return () => clearInterval(intv);
  }, [wsState]);

  // Tasks fallback HTTP polling (if websocket is offline)
  useEffect(() => {
    const fetchTasksFallback = async () => {
      if (wsState === 'LIVE') return;
      try {
        const res = await fetch(`${apiBase}/api/v1/tasks`, { headers: getHeaders() });
        if (res.ok) {
          setTasks(await res.json());
        }
      } catch {}
    };
    fetchTasksFallback();
    const intv = setInterval(fetchTasksFallback, 5000);
    return () => clearInterval(intv);
  }, [wsState]);

  // Update canvas dataPoints
  useEffect(() => {
    if (!telemetry || !rightOpen || !isTabVisible) return;
    const newPoint = telemetry.latency || 100;
    dataPointsRef.current.push(newPoint);
    if (dataPointsRef.current.length > 40) {
      dataPointsRef.current.shift();
    }
  }, [telemetry, rightOpen, isTabVisible]);

  // Canvas drawing loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !rightOpen) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId: number;

    const draw = () => {
      const w = canvas.width;
      const h = canvas.height;
      ctx.fillStyle = '#000000';
      ctx.fillRect(0, 0, w, h);

      // Grid
      ctx.strokeStyle = '#121212';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(0, h / 2);
      ctx.lineTo(w, h / 2);
      ctx.moveTo(0, h / 4);
      ctx.lineTo(w, h / 4);
      ctx.moveTo(0, (3 * h) / 4);
      ctx.lineTo(w, (3 * h) / 4);
      ctx.stroke();

      const pts = dataPointsRef.current;
      if (pts.length < 2) {
        ctx.strokeStyle = '#35D0BA';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, h / 2);
        ctx.lineTo(w, h / 2);
        ctx.stroke();
        animId = requestAnimationFrame(draw);
        return;
      }

      const max = Math.max(...pts, 200);
      const min = Math.min(...pts, 0);
      const diff = max - min;
      const step = w / (pts.length - 1);

      ctx.strokeStyle = '#35D0BA';
      ctx.lineWidth = 1;
      ctx.beginPath();

      pts.forEach((val, idx) => {
        const x = idx * step;
        const norm = diff > 0 ? (val - min) / diff : 0.5;
        const y = h - (norm * (h - 8) + 4);
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      // Draw faint gradient under the curve
      ctx.fillStyle = 'rgba(53, 208, 186, 0.05)';
      ctx.lineTo(w, h);
      ctx.lineTo(0, h);
      ctx.closePath();
      ctx.fill();

      animId = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(animId);
  }, [rightOpen, isTabVisible]);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, streamingResponse]);

  const fetchConversations = async () => {
    try {
      const res = await fetch(`${apiBase}/api/v1/conversations`, { headers: getHeaders() });
      if (res.status === 401) handleLogout();
      if (res.ok) { const d = await res.json(); setConversations(d); if (d.length > 0 && !activeConvId) selectConversation(d[0].id); }
    } catch (e) { console.error(e); }
  };

  const selectConversation = async (id: string) => {
    setActiveConvId(id); setMessages([]); setStreamingResponse(''); setActiveView('chat');
    try {
      const res = await fetch(`${apiBase}/api/v1/conversations/${id}/messages`, { headers: getHeaders() });
      if (res.ok) setMessages(await res.json());
    } catch (e) { console.error(e); }
  };

  const createNewConversation = () => {
    setActiveConvId(null);
    setMessages([]);
    setActiveView('chat');
  };

  const fetchMemories = async () => {
    try { const r = await fetch(`${apiBase}/api/v1/memory`, { headers: getHeaders() }); if (r.ok) setMemories(await r.json()); } catch {}
  };
  const fetchDocuments = async () => {
    try { const r = await fetch(`${apiBase}/api/v1/documents`, { headers: getHeaders() }); if (r.ok) setDocuments(await r.json()); } catch {}
  };

  const handleUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files; if (!f || !f.length) return;
    await handleUploadFileDirectly(f[0]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleUploadFileDirectly = async (file: File) => {
    setUploading(true); setUploadSuccess(false);
    const fd = new FormData(); fd.append('file', file);
    const token = localStorage.getItem('access_token');
    try {
      const r = await fetch(`${apiBase}/api/v1/documents/upload`, { method: 'POST', headers: { 'Authorization': `Bearer ${token}` }, body: fd });
      if (r.ok) { setUploadSuccess(true); fetchDocuments(); setTimeout(() => setUploadSuccess(false), 3000); }
    } catch {} finally { setUploading(false); }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      await handleUploadFileDirectly(e.dataTransfer.files[0]);
    }
  };

  const handleCreateTask = async () => {
    if (!newTaskTitle.trim()) return;
    try {
      const res = await fetch(`${apiBase}/api/v1/tasks`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          type: newTaskType,
          title: newTaskTitle,
          payload: newTaskPayload
        })
      });
      if (res.ok) {
        setShowNewTaskModal(false);
        setNewTaskTitle('');
        setNewTaskPayload({});
        const updated = await res.json();
        setTasks(prev => [updated, ...prev]);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleCancelTask = async (taskId: string) => {
    try {
      const res = await fetch(`${apiBase}/api/v1/tasks/${taskId}/cancel`, { method: 'POST', headers: getHeaders() });
      if (res.ok) {
        const updated = await res.json();
        setTasks(prev => prev.map(t => t.id === taskId ? updated : t));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleRetryTask = async (taskId: string) => {
    try {
      const res = await fetch(`${apiBase}/api/v1/tasks/${taskId}/retry`, { method: 'POST', headers: getHeaders() });
      if (res.ok) {
        const updated = await res.json();
        setTasks(prev => prev.map(t => t.id === taskId ? updated : t));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteTask = async (taskId: string) => {
    try {
      const res = await fetch(`${apiBase}/api/v1/tasks/${taskId}`, { method: 'DELETE', headers: getHeaders() });
      if (res.ok) {
        setTasks(prev => prev.filter(t => t.id !== taskId));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleClearCompletedTasks = async () => {
    try {
      const res = await fetch(`${apiBase}/api/v1/tasks/clear_completed`, { method: 'DELETE', headers: getHeaders() });
      if (res.ok) {
        setTasks(prev => prev.filter(t => ["Queued", "Starting", "Running", "Waiting"].includes(t.status)));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteFile = async (docId: string, filename: string) => {
    if (!confirm(`Are you sure you want to remove "${filename}"?`)) return;
    try {
      const res = await fetch(`${apiBase}/api/v1/documents/${docId}`, { method: 'DELETE', headers: getHeaders() });
      if (res.ok) {
        setDocuments(prev => prev.filter(d => d.id !== docId));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleRenameFile = async () => {
    if (!selectedFileForRename || !newFileName.trim()) return;
    try {
      const res = await fetch(`${apiBase}/api/v1/documents/${selectedFileForRename.id}/rename`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ filename: newFileName })
      });
      if (res.ok) {
        setShowRenameModal(false);
        setDocuments(prev => prev.map(d => d.id === selectedFileForRename.id ? { ...d, filename: newFileName } : d));
        setSelectedFileForRename(null);
        setNewFileName('');
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleRetryFileIndexing = async (docId: string) => {
    try {
      await fetch(`${apiBase}/api/v1/documents/${docId}/retry`, { method: 'POST', headers: getHeaders() });
      fetchDocuments();
    } catch (e) {
      console.error(e);
    }
  };

  const handleAttachFileToChat = (filename: string) => {
    setInputText(prev => prev + ` [File: ${filename}] `);
  };

  const handleSendMessage = async (payload: ChatSubmitPayload) => {
    if ((!payload.message.trim() && payload.attachments.length === 0) || loadingResponse) return;
    let cid = activeConvId;
    if (!cid) {
      try {
        const r = await fetch(`${apiBase}/api/v1/conversations?character_id=sakura`, { method: 'POST', headers: getHeaders() });
        if (r.ok) { const d = await r.json(); setConversations(p => [d, ...p]); setActiveConvId(d.id); cid = d.id; } else return;
      } catch { return; }
    }
    const txt = payload.message;
    setStreamingResponse('');
    setStreamingProvider('');
    setLoadingResponse(true);
    setMessages(p => [...p, {
      role: 'user',
      content: txt,
      metadata: {
        tools: payload.tools,
        attachments: payload.attachments,
        intensity: payload.intensity
      }
    }]);
    const ctrl = new AbortController();
    abortControllerRef.current = ctrl;
    try {
      const res = await fetch(`${apiBase}/api/v1/chat/stream`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          conversation_id: cid,
          message: txt,
          intensity: payload.intensity,
          tools: payload.tools,
          attachments: payload.attachments
        }),
        signal: ctrl.signal
      });
      if (!res.ok) throw new Error('fail');
      const reader = res.body?.getReader();
      const dec = new TextDecoder();
      if (!reader) return;
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() || '';
        for (const l of lines) {
          const cl = l.trim();
          if (cl.startsWith('data: ')) {
            try {
              const d = JSON.parse(cl.slice(6));
              if (d.token) setStreamingResponse(p => p + d.token);
              if (d.provider) setStreamingProvider(d.provider);
            } catch {}
          }
        }
      }
      await selectConversation(cid!);
      fetchMemories();
    } catch (err: any) {
      if (err.name !== 'AbortError') console.error(err);
    } finally {
      setLoadingResponse(false);
      abortControllerRef.current = null;
    }
  };

  const handleStopGeneration = () => { abortControllerRef.current?.abort(); };
  const handleLogout = () => { localStorage.removeItem('access_token'); router.push('/login'); };
  const getActiveTitle = () => { if (!activeConvId) return 'New chat'; return conversations.find(c => c.id === activeConvId)?.title || 'Chat'; };

  const handleCopy = (content: string, idx: number) => {
    navigator.clipboard.writeText(content);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  const handleTogglePinChat = async (id: string, isCurrentlyPinned: boolean) => {
    const action = isCurrentlyPinned ? 'unpin' : 'pin';
    // Optimistic update
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, pinned: !isCurrentlyPinned, pinned_at: !isCurrentlyPinned ? new Date().toISOString() : null } : c))
    );

    try {
      const res = await fetch(`${apiBase}/api/v1/conversations/${id}/${action}`, {
        method: 'POST',
        headers: getHeaders()
      });
      if (res.ok) {
        const updated = await res.json();
        setConversations((prev) =>
          prev.map((c) => (c.id === id ? { ...c, ...updated } : c))
        );
      }
    } catch (e) {
      console.error(`Failed to ${action} chat:`, e);
      fetchConversations();
    }
  };

  const handleSaveRenameChat = async (id: string, newTitle: string) => {
    const cleanTitle = newTitle.trim();
    setEditingChatId(null);
    if (!cleanTitle) return;

    const currentConv = conversations.find((c) => c.id === id);
    const oldTitle = currentConv ? currentConv.title : '';
    if (cleanTitle === oldTitle) return;

    // Optimistic UI update
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title: cleanTitle, updated_at: new Date().toISOString() } : c))
    );

    try {
      const res = await fetch(`${apiBase}/api/v1/conversations/${id}`, {
        method: 'PUT',
        headers: getHeaders(),
        body: JSON.stringify({ title: cleanTitle })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.conversation) {
          setConversations((prev) =>
            prev.map((c) => (c.id === id ? { ...c, ...data.conversation } : c))
          );
        }
      } else {
        console.error('Rename failed on server, reverting.');
        setConversations((prev) =>
          prev.map((c) => (c.id === id ? { ...c, title: oldTitle } : c))
        );
      }
    } catch (e) {
      console.error('Rename network error:', e);
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, title: oldTitle } : c))
      );
    }
  };

  const handleConfirmDeleteChat = async (id: string) => {
    try {
      const res = await fetch(`${apiBase}/api/v1/conversations/${id}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (res.ok) {
        const remaining = conversations.filter((c) => c.id !== id);
        setConversations(remaining);
        if (activeConvId === id) {
          if (remaining.length > 0) {
            selectConversation(remaining[0].id);
          } else {
            setActiveConvId(null);
            setMessages([]);
          }
        }
      }
    } catch (e) {
      console.error('Delete chat failed:', e);
    }
  };

  const handleArchiveChat = async (id: string) => {
    const remaining = conversations.filter((c) => c.id !== id);
    setConversations(remaining);
    if (activeConvId === id) {
      if (remaining.length > 0) {
        selectConversation(remaining[0].id);
      } else {
        setActiveConvId(null);
        setMessages([]);
      }
    }
    try {
      await fetch(`${apiBase}/api/v1/conversations/${id}/archive`, {
        method: 'POST',
        headers: getHeaders()
      });
    } catch (e) {
      console.error('Archive chat failed:', e);
      fetchConversations();
    }
  };

  const groupConversationsByDate = () => {
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    
    const groups: { [key: string]: any[] } = {
      "Today": [],
      "Yesterday": [],
      "Previous 7 Days": [],
      "Previous 30 Days": [],
      "Older": []
    };
    
    // Exclude pinned and archived conversations
    const unpinned = conversations.filter(c => !c.pinned && !c.archived_at);

    unpinned.forEach(c => {
      const d = new Date(c.updated_at || c.created_at || new Date());
      const isToday = d.toDateString() === today.toDateString();
      const isYesterday = d.toDateString() === yesterday.toDateString();
      const diffTime = Math.abs(today.getTime() - d.getTime());
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
      
      if (isToday) {
        groups["Today"].push(c);
      } else if (isYesterday) {
        groups["Yesterday"].push(c);
      } else if (diffDays <= 7) {
        groups["Previous 7 Days"].push(c);
      } else if (diffDays <= 30) {
        groups["Previous 30 Days"].push(c);
      } else {
        groups["Older"].push(c);
      }
    });
    
    return groups;
  };

  const renderPanelContent = () => {
    const filteredDocs = documents.filter(d => 
      d.filename.toLowerCase().includes(fileSearchQuery.toLowerCase())
    );

    const contextPct = telemetry?.contextUsed && telemetry?.contextLimit 
      ? Math.round((telemetry.contextUsed / telemetry.contextLimit) * 100) 
      : 0;

    const getContextColor = (pct: number) => {
      if (pct >= 95) return '#FF453A';
      if (pct >= 85) return '#FF9F0A';
      if (pct >= 70) return '#FFD60A';
      return '#9880ED';
    };

    const formatBytes = (bytes: number) => {
      if (!bytes) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    };

    return (
      <div className="flex flex-col gap-6">
        {secondsSinceUpdate > 15 && (
          <div className="bg-[#210c0c] border border-[#3e1b1b] text-[#FF453A] text-[10px] p-2 rounded font-mono flex items-center justify-between animate-pulse">
            <span>⚠️ STALE TELEMETRY DATA</span>
            <button onClick={connectWS} className="underline font-bold text-[9px] hover:text-white cursor-pointer">RECONNECT</button>
          </div>
        )}

        <div className="flex flex-col gap-2.5">
          <div className="flex justify-between items-center">
            <PanelHeading label="SYSTEM STATUS" />
            <span className={`text-[8px] font-mono font-bold tracking-wider px-1.5 py-0.5 rounded ${
              wsState === 'LIVE' ? 'bg-[#141414] text-[#35D0BA]' :
              wsState === 'CONNECTING' || wsState === 'RECONNECTING' ? 'bg-[#1a1306] text-[#FF9F0A] animate-pulse' :
              'bg-[#210c0c] text-[#FF453A]'
            }`}>
              {wsState}
            </span>
          </div>

          <div className="bg-[#050505] border border-[#1F1F1F] rounded overflow-hidden relative">
            <canvas 
              ref={canvasRef} 
              width={240} 
              height={50} 
              className="w-full h-[50px] block"
              title="Live latency telemetry stream"
            />
            <div className="absolute bottom-1 right-1.5 text-[7px] text-[#555] font-mono select-none pointer-events-none">
              LATENCY (30S WINDOW)
            </div>
          </div>

          <div className="flex flex-col gap-2 font-mono text-[9px] text-[#A3A3A3] border border-[#1F1F1F] rounded p-2.5 bg-[#050505] divide-y divide-[#151515]">
            <div className="flex justify-between py-1">
              <span>RESPONSE LATENCY</span>
              <span className="text-white font-bold">{telemetry?.latency !== undefined ? `${telemetry.latency} ms` : '—'}</span>
            </div>
            
            <div className="flex flex-col py-1 gap-1">
              <div className="flex justify-between">
                <span>CONTEXT WINDOW</span>
                <span className="text-white font-bold">{contextPct}%</span>
              </div>
              <div className="w-full h-1 bg-[#151515] rounded overflow-hidden">
                <div 
                  className="h-full rounded transition-all duration-300" 
                  style={{ width: `${Math.min(100, contextPct)}%`, backgroundColor: getContextColor(contextPct) }} 
                />
              </div>
              <div className="flex justify-between items-center text-[7px] text-[#555]">
                <button 
                  onClick={() => setShowContextDetails(!showContextDetails)} 
                  className="hover:text-white underline cursor-pointer text-[7px]"
                >
                  {showContextDetails ? 'HIDE DETAILS' : 'VIEW DETAILS'}
                </button>
                <span>{telemetry?.contextUsed !== undefined ? `${telemetry.contextUsed} / ${telemetry.contextLimit} T` : '—'}</span>
              </div>
              {showContextDetails && (
                <div className="bg-[#0A0A0A] border border-[#1F1F1F] p-1.5 rounded mt-1 text-[8px] text-[#8E8E8E] flex flex-col gap-0.5">
                  <div className="flex justify-between"><span>System Tokens:</span><span className="text-white">~350</span></div>
                  <div className="flex justify-between"><span>Message Context:</span><span className="text-[#35D0BA]">~{Math.max(0, (telemetry?.contextUsed || 0) - 350)}</span></div>
                  <div className="flex justify-between"><span>Reserved Output:</span><span className="text-white">4,096</span></div>
                </div>
              )}
            </div>

            <div className="flex justify-between py-1">
              <span>ACTIVE TASKS</span>
              <span className="text-white font-bold">{telemetry?.activeTasks !== undefined ? telemetry.activeTasks : '0'}</span>
            </div>

            <div className="flex justify-between py-1">
              <span>TOKENS / SEC</span>
              <span className="text-[#35D0BA] font-bold">{telemetry?.tokensPerSecond !== undefined ? telemetry.tokensPerSecond : '0.0'}</span>
            </div>

            <div className="flex justify-between py-1">
              <span>SERVER REGION</span>
              <span className="text-white">{telemetry?.region || 'IN / AP-SOUTH'}</span>
            </div>

            <div className="flex justify-between py-1">
              <span>SERVER UPTIME</span>
              <span className="text-white">{telemetry?.uptime || '—'}</span>
            </div>
          </div>
        </div>

        <div className="h-px bg-[#1F1F1F]" />

        <div className="flex flex-col gap-2.5">
          <div className="flex justify-between items-center">
            <PanelHeading label="TASKS QUEUE" />
            {tasks.some(t => ["Completed", "Failed", "Cancelled"].includes(t.status)) && (
              <button 
                onClick={handleClearCompletedTasks}
                className="text-[8px] font-bold tracking-wider text-[#6B6B6B] hover:text-white transition-colors cursor-pointer" 
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                CLEAR
              </button>
            )}
          </div>
          
          <div className="flex flex-col gap-1">
            {loadingResponse && (
              <div className="flex flex-col gap-1.5 p-2 bg-[#050505] border border-[#1F1F1F] rounded">
                <div className="flex justify-between items-center">
                  <div className="flex items-center gap-2 text-[11px] text-[#35D0BA]">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>LLM GENERATION</span>
                  </div>
                  <span className="text-[8px] font-mono text-[#6B6B6B]">ACTIVE</span>
                </div>
                <div className="w-full h-1 bg-[#151515] rounded overflow-hidden">
                  <div className="h-full bg-[#35D0BA] animate-pulse" style={{ width: '80%' }} />
                </div>
              </div>
            )}

            {tasks.length === 0 && !loadingResponse ? (
              <span className="text-[10px] text-[#555] font-mono text-center py-2">NO TASKS IN QUEUE</span>
            ) : (
              tasks.map(t => {
                const getIcon = () => {
                  if (t.type === 'code_analysis') return <Code className="w-3.5 h-3.5 text-[#E98297]" />;
                  if (t.type === 'doc_summary') return <FileText className="w-3.5 h-3.5 text-[#4A8EFF]" />;
                  if (t.type === 'dataset_analysis') return <BarChart2 className="w-3.5 h-3.5 text-[#9880ED]" />;
                  return <Search className="w-3.5 h-3.5 text-[#35D0BA]" />;
                };

                const getStatusColor = () => {
                  if (t.status === 'Completed') return 'text-[#35D0BA]';
                  if (t.status === 'Failed') return 'text-[#FF453A]';
                  if (t.status === 'Cancelled') return 'text-[#6B6B6B]';
                  return 'text-[#FF9F0A]';
                };

                return (
                  <div key={t.id} className="flex flex-col p-2 bg-[#050505] border border-[#1F1F1F] rounded gap-1.5 group/task relative">
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-2 truncate text-left">
                        {getIcon()}
                        <span className="text-[11px] font-bold text-white truncate max-w-[130px]">{t.title}</span>
                      </div>
                      <span className={`text-[8px] font-mono ${getStatusColor()}`}>{t.status}</span>
                    </div>

                    {["Running", "Starting", "Waiting"].includes(t.status) && (
                      <div className="w-full h-1 bg-[#151515] rounded overflow-hidden">
                        <div className="h-full bg-[#35D0BA] transition-all duration-300" style={{ width: `${t.progress}%` }} />
                      </div>
                    )}

                    {t.error && (
                      <div className="text-[8px] font-mono text-[#FF453A] bg-[#210c0c] p-1 border border-[#3e1b1b] rounded overflow-x-auto whitespace-pre-wrap">
                        ERROR: {t.error}
                      </div>
                    )}

                    {t.result && (
                      <details className="text-[8px] font-mono text-[#A3A3A3] cursor-pointer">
                        <summary className="hover:text-white select-none">VIEW RESULT SUMMARY</summary>
                        <div className="bg-[#080808] p-1.5 border border-[#151515] rounded mt-1 select-text max-h-24 overflow-y-auto whitespace-pre-wrap">
                          {t.result}
                        </div>
                      </details>
                    )}

                    <div className="flex justify-end gap-1.5 opacity-0 group-hover/task:opacity-100 transition-opacity">
                      {["Queued", "Starting", "Running", "Waiting"].includes(t.status) && (
                        <button 
                          onClick={() => handleCancelTask(t.id)} 
                          className="text-[8px] font-mono text-[#FF453A] hover:underline cursor-pointer"
                        >
                          CANCEL
                        </button>
                      )}
                      {["Failed", "Cancelled"].includes(t.status) && (
                        <button 
                          onClick={() => handleRetryTask(t.id)} 
                          className="text-[8px] font-mono text-[#35D0BA] hover:underline cursor-pointer"
                        >
                          RETRY
                        </button>
                      )}
                      <button 
                        onClick={() => handleDeleteTask(t.id)} 
                        className="text-[8px] font-mono text-[#6B6B6B] hover:text-white cursor-pointer"
                      >
                        REMOVE
                      </button>
                    </div>
                  </div>
                );
              })
            )}
            
            <button 
              onClick={() => {
                setShowNewTaskModal(true);
                setNewTaskTitle('');
                setNewTaskPayload({});
              }}
              className="mt-2 w-full border border-[#1F1F1F] hover:border-[#6B6B6B] py-1.5 text-[9px] font-bold tracking-[.15em] text-[#6B6B6B] hover:text-white transition-colors flex items-center justify-center gap-1.5 cursor-pointer rounded" 
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              <Plus className="w-3 h-3" /> NEW OPERATIONAL TASK
            </button>
          </div>
        </div>

        <div className="h-px bg-[#1F1F1F]" />

        <div className="flex flex-col gap-2.5">
          <div className="flex justify-between items-center">
            <PanelHeading label="KNOWLEDGE BASE" />
            <span className="text-[8px] font-bold font-mono text-[#6B6B6B]">FILES: {documents.length}</span>
          </div>

          <div className="bg-[#050505] border border-[#1F1F1F] px-2 py-1 rounded flex items-center gap-1.5">
            <Search className="w-3 h-3 text-[#555]" />
            <input 
              type="text" 
              value={fileSearchQuery}
              onChange={(e) => setFileSearchQuery(e.target.value)}
              placeholder="Search files..."
              className="bg-transparent border-none text-[10px] text-white placeholder:text-[#555] focus:outline-none w-full font-mono"
            />
            {fileSearchQuery && (
              <button onClick={() => setFileSearchQuery('')} className="text-[#6B6B6B] hover:text-white text-[9px] font-mono">&times;</button>
            )}
          </div>

          <div 
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`w-full border border-dashed py-4 rounded text-center transition-all cursor-pointer flex flex-col items-center justify-center gap-1 select-none ${
              dragActive 
                ? 'border-[#35D0BA] bg-[#35d0ba]/5 text-[#35D0BA]' 
                : 'border-[#1F1F1F] hover:border-[#6B6B6B] text-[#6B6B6B] hover:text-[#A3A3A3] bg-[#030303]'
            }`}
          >
            <input 
              type="file" 
              ref={fileInputRef} 
              onChange={handleUploadFile} 
              className="hidden" 
              accept=".pdf,.txt,.md" 
            />
            {uploading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin text-[#9880ED]" />
                <span className="text-[9px] font-mono font-bold tracking-wider text-[#9880ED]">UPLOADING...</span>
              </>
            ) : uploadSuccess ? (
              <>
                <CheckCircle className="w-4 h-4 text-[#35D0BA]" />
                <span className="text-[9px] font-mono font-bold text-[#35D0BA]">FILE INGESTED</span>
              </>
            ) : (
              <>
                <Plus className="w-4 h-4" />
                <span className="text-[9px] font-bold tracking-wider font-mono">DRAG & DROP OR CHOOSE FILE</span>
                <span className="text-[7px] text-[#555] font-mono">SUPPORTED: PDF, TXT, MD</span>
              </>
            )}
          </div>

          <div className="flex flex-col gap-1.5 max-h-[220px] overflow-y-auto pr-1">
            {filteredDocs.length === 0 ? (
              <span className="text-[10px] text-[#555] font-mono text-center py-2">NO DOCUMENTS INDEXED</span>
            ) : (
              filteredDocs.map(d => {
                const getIngestBadge = () => {
                  const status = d.metadata?.indexing_status || 'Ready';
                  if (status === 'Ready') return 'bg-[#141414] text-[#35D0BA] border border-[#222]';
                  if (status === 'Failed') return 'bg-[#210c0c] text-[#FF453A] border border-[#3e1b1b]';
                  return 'bg-[#121215] text-[#9880ED] border border-[#2d223c] animate-pulse';
                };

                return (
                  <div key={d.id} className="flex flex-col p-2 bg-[#050505] border border-[#1F1F1F] rounded gap-1 group/file">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 truncate text-left">
                        <FileText className="w-3.5 h-3.5 text-[#6B6B6B] flex-shrink-0" />
                        <span className="text-[11px] text-white truncate max-w-[130px] font-medium">{d.filename}</span>
                      </div>
                      <span className={`text-[7px] font-mono px-1 py-0.5 rounded ${getIngestBadge()}`}>
                        {d.metadata?.indexing_status || 'Ready'}
                      </span>
                    </div>

                    <div className="flex justify-between items-center text-[7px] font-mono text-[#555]">
                      <span>{formatBytes(d.metadata?.size)}</span>
                      <span>{d.created_at ? new Date(d.created_at).toLocaleDateString() : '—'}</span>
                    </div>

                    {d.metadata?.error && (
                      <div className="text-[7px] font-mono text-[#FF453A] bg-[#210c0c] p-1 border border-[#3e1b1b] rounded mt-0.5 max-h-16 overflow-y-auto">
                        {d.metadata.error}
                      </div>
                    )}

                    <div className="flex justify-end gap-2 mt-1 opacity-0 group-hover/file:opacity-100 transition-opacity">
                      {d.metadata?.indexing_status === 'Failed' && (
                        <button 
                          onClick={() => handleRetryFileIndexing(d.id)}
                          className="text-[7px] font-mono text-[#35D0BA] hover:underline cursor-pointer"
                        >
                          RETRY
                        </button>
                      )}
                      <button 
                        onClick={() => {
                          setSelectedFileForRename(d);
                          setNewFileName(d.filename);
                          setShowRenameModal(true);
                        }}
                        className="text-[7px] font-mono text-white hover:underline cursor-pointer"
                      >
                        RENAME
                      </button>
                      <button 
                        onClick={() => handleAttachFileToChat(d.filename)}
                        className="text-[7px] font-mono text-[#4A8EFF] hover:underline cursor-pointer"
                      >
                        ATTACH
                      </button>
                      <button 
                        onClick={() => handleDeleteFile(d.id, d.filename)}
                        className="text-[7px] font-mono text-[#FF453A] hover:underline cursor-pointer"
                      >
                        DELETE
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="h-screen w-screen bg-black text-[#F5F5F5] flex overflow-hidden" style={{ fontFamily: "'Inter', -apple-system, system-ui, 'Segoe UI', Helvetica, Arial, sans-serif" }}>

      {/* Mobile Backdrop when sidebar is open */}
      {isMobile && sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-xs z-30"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ═══ LEFT SIDEBAR ═══ */}
      <aside
        aria-label="Sidebar navigation"
        className={`flex-shrink-0 flex flex-col bg-black border-r border-[#202020] transition-all duration-200 ease-in-out select-none ${
          isMobile
            ? (sidebarOpen ? 'fixed inset-y-0 left-0 z-40 w-[272px]' : 'hidden')
            : (sidebarOpen ? 'w-[272px]' : 'w-[56px]')
        }`}
      >
        {sidebarOpen ? (
          /* ─── EXPANDED SIDEBAR (272px) ─── */
          <div className="w-[272px] flex flex-col h-full overflow-hidden bg-black">
            {/* Top Header: Brand on Left, Search & Toggle on Right */}
            <div className="pt-3 pb-2 px-3 flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-2.5 select-none min-w-0">
                <SakuraLogo size={26} alt="Sakura AI" className="flex-shrink-0" />
                <span className="font-semibold text-[15px] tracking-wide text-white font-sans flex items-center">
                  SAKURA AI
                </span>
              </div>
              <div className="flex items-center gap-0.5">
                <button
                  onClick={() => setShowSearchModal(true)}
                  className="p-1.5 text-[#8E8E8E] hover:text-white hover:bg-[#181818] rounded-lg transition-colors cursor-pointer"
                  title="Search (Ctrl+K)"
                  aria-label="Search"
                >
                  <Search className="w-[17px] h-[17px]" />
                </button>
                <div className="relative group/sidebarToggle">
                  <button
                    type="button"
                    onClick={() => setSidebarOpen(false)}
                    className="w-9 h-9 flex items-center justify-center text-[#B0B0B0] hover:text-white hover:bg-white/[0.08] active:bg-white/[0.12] rounded-lg transition-colors cursor-pointer focus:outline-none focus-visible:ring-1 focus-visible:ring-white/20"
                    aria-label="Collapse sidebar"
                    aria-expanded="true"
                  >
                    <SidebarToggleIcon className="w-[19px] h-[19px]" />
                  </button>
                  <div className="absolute right-0 top-full mt-1.5 hidden group-hover/sidebarToggle:flex group-focus-within/sidebarToggle:flex items-center z-50 pointer-events-none">
                    <div className="bg-[#242424] text-[#F5F5F5] text-[12px] font-medium px-2.5 py-1 rounded-md shadow-xl border border-white/[0.08] whitespace-nowrap">
                      Close sidebar
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Primary Navigation Stack */}
            <div className="flex flex-col gap-0.5 px-2 pt-1 pb-1 flex-shrink-0">
              <SidebarNavItem
                icon={<NewChatIcon className="w-[17px] h-[17px] text-[#EDEDED] group-hover:text-white flex-shrink-0" />}
                label="New chat"
                onClick={createNewConversation}
              />
              <SidebarNavItem
                icon={<LibraryIcon className="w-[17px] h-[17px] text-[#EDEDED] group-hover:text-white flex-shrink-0" />}
                label="Library"
                active={activeView === 'library'}
                onClick={() => setActiveView('library')}
              />
              <SidebarNavItem
                icon={<Folder className="w-[17px] h-[17px]" />}
                label="Projects"
                active={activeView === 'projects'}
                onClick={() => setActiveView('projects')}
              />
              <SidebarNavItem
                icon={<Clock className="w-[17px] h-[17px]" />}
                label="Scheduled"
                active={activeView === 'scheduled'}
                onClick={() => setActiveView('scheduled')}
              />
              <SidebarNavItem
                icon={<Compass className="w-[17px] h-[17px]" />}
                label="Plugins"
                active={activeView === 'plugins'}
                onClick={() => setActiveView('plugins')}
              />
              <SidebarNavItem
                icon={<MoreHorizontal className="w-[17px] h-[17px]" />}
                label="More"
                onClick={() => setShowAccountMenu(true)}
              />
            </div>

            {/* Middle Scrollable Section: Pinned and Recents */}
            <div className="flex-1 overflow-y-auto px-2 pb-2 flex flex-col sidebar-scroll">
              {/* Pinned Chats Section */}
              <div className="mt-2 mb-1">
                <div className="flex items-center justify-between px-2 py-1 select-none">
                  <span className="text-[12px] font-medium text-[#8E8E8E]">Pinned</span>
                  {conversations.filter(c => c.pinned && !c.archived_at).length > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        const nextState = !isPinnedCollapsed;
                        setIsPinnedCollapsed(nextState);
                        if (typeof window !== 'undefined') {
                          localStorage.setItem('sakura_pinned_collapsed', JSON.stringify(nextState));
                        }
                      }}
                      className="text-[#666666] hover:text-white p-0.5 rounded cursor-pointer"
                      aria-label="Toggle pinned section"
                    >
                      <ChevronDown className={`w-3.5 h-3.5 transition-transform duration-150 ${isPinnedCollapsed ? '-rotate-90' : ''}`} />
                    </button>
                  )}
                </div>

                {!isPinnedCollapsed && (
                  <div className="flex flex-col gap-0.5">
                    {conversations.filter(c => c.pinned && !c.archived_at).length === 0 ? (
                      <div className="px-2.5 py-1 text-[13px] text-[#555555]">No pinned chats</div>
                    ) : (
                      conversations
                        .filter(c => c.pinned && !c.archived_at)
                        .sort((a, b) => {
                          const tA = new Date(a.pinned_at || a.updated_at || a.created_at).getTime();
                          const tB = new Date(b.pinned_at || b.updated_at || b.created_at).getTime();
                          return tB - tA;
                        })
                        .map((c: any) => (
                          <SidebarChatItem 
                            key={c.id} 
                            label={c.title} 
                            active={activeConvId === c.id} 
                            isPinned={true}
                            showIcon={true}
                            isEditing={editingChatId === c.id}
                            onStartRename={() => setEditingChatId(c.id)}
                            onSaveRename={(newTitle) => handleSaveRenameChat(c.id, newTitle)}
                            onCancelRename={() => setEditingChatId(null)}
                            onClick={() => selectConversation(c.id)} 
                            onShare={() => setShareModalChat({ id: c.id, title: c.title })}
                            onDelete={() => setDeleteModalChat({ id: c.id, title: c.title })}
                            onTogglePin={() => handleTogglePinChat(c.id, true)}
                            onArchive={() => handleArchiveChat(c.id)}
                          />
                        ))
                    )}
                  </div>
                )}
              </div>

              {/* Recents Section */}
              <div className="mt-2.5 mb-1">
                <div className="flex items-center justify-between px-2 py-1 select-none">
                  <span className="text-[12px] font-medium text-[#8E8E8E]">Recents</span>
                  {conversations.filter(c => !c.archived_at).length > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        const nextState = !isRecentsCollapsed;
                        setIsRecentsCollapsed(nextState);
                        if (typeof window !== 'undefined') {
                          localStorage.setItem('sakura_recents_collapsed', JSON.stringify(nextState));
                        }
                      }}
                      className="text-[#666666] hover:text-white p-0.5 rounded cursor-pointer"
                      aria-label="Toggle recents section"
                    >
                      <ChevronDown className={`w-3.5 h-3.5 transition-transform duration-150 ${isRecentsCollapsed ? '-rotate-90' : ''}`} />
                    </button>
                  )}
                </div>

                {!isRecentsCollapsed && (
                  <div className="flex flex-col gap-0.5">
                    {conversations.filter(c => !c.archived_at).length === 0 ? (
                      <div className="px-2.5 py-1 text-[13px] text-[#555555]">No recent chats</div>
                    ) : (
                      conversations
                        .filter(c => !c.archived_at)
                        .sort((a, b) => {
                          const tA = new Date(a.updated_at || a.created_at).getTime();
                          const tB = new Date(b.updated_at || b.created_at).getTime();
                          return tB - tA;
                        })
                        .map((c: any) => (
                          <SidebarChatItem 
                            key={c.id} 
                            label={c.title} 
                            active={activeConvId === c.id} 
                            isPinned={!!c.pinned}
                            showIcon={false}
                            isEditing={editingChatId === c.id}
                            onStartRename={() => setEditingChatId(c.id)}
                            onSaveRename={(newTitle) => handleSaveRenameChat(c.id, newTitle)}
                            onCancelRename={() => setEditingChatId(null)}
                            onClick={() => selectConversation(c.id)} 
                            onShare={() => setShareModalChat({ id: c.id, title: c.title })}
                            onDelete={() => setDeleteModalChat({ id: c.id, title: c.title })}
                            onTogglePin={() => handleTogglePinChat(c.id, !!c.pinned)}
                            onArchive={() => handleArchiveChat(c.id)}
                          />
                        ))
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Expanded Account Footer (Anchored at Bottom) */}
            <div className="flex-shrink-0 border-t border-[#181818] p-2">
              <div
                onClick={() => setShowAccountMenu(!showAccountMenu)}
                className="flex items-center justify-between px-2 py-1.5 rounded-lg hover:bg-[#141414] transition-colors cursor-pointer select-none"
                title="Account menu"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#9880ED] to-[#E98297] flex items-center justify-center text-[13px] font-bold text-white flex-shrink-0">
                    {currentUser ? currentUser.substring(0, 1).toUpperCase() : 'K'}
                  </div>
                  <div className="flex flex-col min-w-0">
                    <span className="text-[13.5px] text-white leading-tight font-medium truncate">{currentUser || 'Kira Light'}</span>
                    <span className="text-[11px] text-[#8E8E8E] leading-tight">Plus</span>
                  </div>
                </div>
                <Store className="w-4 h-4 text-[#8E8E8E] hover:text-white flex-shrink-0" />
              </div>
            </div>
          </div>
        ) : (
          /* ─── COLLAPSED ICON RAIL (56px) ─── */
          <div className="w-[56px] flex flex-col h-full items-center py-3 bg-black">
            {/* Top: Official Transparent Sakura Flower Logo */}
            <div className="relative group flex items-center justify-center">
              <button
                type="button"
                onClick={() => setSidebarOpen(true)}
                className="w-11 h-11 flex items-center justify-center rounded-lg hover:bg-[#191919] transition-colors cursor-pointer"
                aria-label="Expand sidebar"
              >
                <SakuraLogo size={30} alt="Sakura AI" className="transition-transform group-hover:scale-105" />
              </button>
              <div className="absolute left-[54px] top-1/2 -translate-y-1/2 hidden group-hover:flex items-center z-50 pointer-events-none">
                <div className="bg-[#2A2A2A] text-[#F5F5F5] text-[13px] font-medium px-2.5 py-1 rounded-md shadow-xl border border-[#383838]/80 whitespace-nowrap">
                  Expand sidebar (Ctrl+[)
                </div>
              </div>
            </div>

            {/* Vertical rhythm navigation icons (center-to-center ~48px) */}
            <div className="mt-4 flex flex-col items-center gap-1.5 w-full">
              {/* 1. New chat */}
              <RailIconButton
                icon={
                  <svg className="w-[21px] h-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                    <path d="M18.375 2.625a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4Z" />
                  </svg>
                }
                label="New chat"
                onClick={createNewConversation}
                ariaLabel="New chat"
              />

              {/* 2. Search */}
              <RailIconButton
                icon={
                  <svg className="w-[21px] h-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="11" cy="11" r="8" />
                    <path d="m21 21-4.3-4.3" />
                  </svg>
                }
                label="Search"
                onClick={() => setShowSearchModal(true)}
                ariaLabel="Search"
              />

              {/* 3. Pinned chats */}
              <RailIconButton
                icon={
                  <svg className="w-[21px] h-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="m16 2-4.5 4.5" />
                    <path d="m9 7-5 5 4 4 5-5" />
                    <path d="m15 13 4.5-4.5" />
                    <path d="m19 5-2-2" />
                    <path d="m3 21 6-6" />
                  </svg>
                }
                label="Pinned chats"
                onClick={() => {
                  setSidebarOpen(true);
                  setIsPinnedCollapsed(false);
                }}
                ariaLabel="Pinned chats"
              />

              {/* 4. Chats (History) */}
              <RailIconButton
                icon={
                  <svg className="w-[21px] h-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
                  </svg>
                }
                label="Chats"
                active={activeView === 'chat'}
                onClick={() => {
                  setSidebarOpen(true);
                  setActiveView('chat');
                  setIsRecentsCollapsed(false);
                }}
                ariaLabel="Chats"
              />
            </div>

            {/* Large flexible pitch-black space */}
            <div className="flex-1 w-full" />

            {/* Bottom User Avatar (Anchored via margin-top: auto) */}
            <div className="relative group flex items-center justify-center mt-auto mb-1">
              <button
                type="button"
                onClick={() => setShowAccountMenu(!showAccountMenu)}
                aria-label="Account"
                className="w-11 h-11 flex items-center justify-center rounded-lg hover:bg-[#191919] transition-colors cursor-pointer"
              >
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[#9880ED] to-[#E98297] flex items-center justify-center text-[12px] font-bold text-white shadow-sm select-none">
                  {currentUser ? currentUser.substring(0, 1).toUpperCase() : 'S'}
                </div>
              </button>
              <div className="absolute left-[54px] top-1/2 -translate-y-1/2 hidden group-hover:flex items-center z-50 pointer-events-none">
                <div className="bg-[#2A2A2A] text-[#F5F5F5] text-[13px] font-medium px-2.5 py-1 rounded-md shadow-xl border border-[#383838]/80 whitespace-nowrap">
                  {currentUser || 'Operator'} · Plus
                </div>
              </div>
            </div>
          </div>
        )}
      </aside>

      {/* ═══ CENTER CHAT ═══ */}
      <div className="flex-1 flex flex-col min-w-0 bg-black">

        <div className="h-[52px] flex items-center justify-between px-4 flex-shrink-0">
          <div className="flex items-center gap-1">
            {!sidebarOpen && (
              <div className="flex items-center gap-1 mr-1">
                <div className="relative group/sidebarToggle">
                  <button
                    type="button"
                    onClick={() => setSidebarOpen(true)}
                    className="w-9 h-9 flex items-center justify-center text-[#B0B0B0] hover:text-white hover:bg-white/[0.08] active:bg-white/[0.12] rounded-lg transition-colors cursor-pointer focus:outline-none focus-visible:ring-1 focus-visible:ring-white/20"
                    aria-label="Expand sidebar"
                    aria-expanded="false"
                  >
                    <SidebarToggleIcon className="w-[19px] h-[19px]" />
                  </button>
                  <div className="absolute left-0 top-full mt-1.5 hidden group-hover/sidebarToggle:flex group-focus-within/sidebarToggle:flex items-center z-50 pointer-events-none">
                    <div className="bg-[#242424] text-[#F5F5F5] text-[12px] font-medium px-2.5 py-0.5 rounded-md shadow-xl border border-white/[0.08] whitespace-nowrap">
                      Open sidebar
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {/* Share Button */}
            <button
              type="button"
              onClick={() => {
                if (activeConvId) {
                  const conv = conversations.find(c => c.id === activeConvId);
                  setShareModalChat({ id: activeConvId, title: conv?.title || getActiveTitle() });
                }
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[#EDEDED] hover:text-white hover:bg-white/[0.08] rounded-lg transition-colors cursor-pointer select-none"
              title="Share conversation"
            >
              <ShareIcon />
              <span className="text-[14.5px] font-medium">Share</span>
            </button>

            {/* Conversation Options (...) Button & Popover Menu */}
            <div className="relative inline-block" ref={topMenuRef}>
              <button
                ref={topMenuButtonRef}
                type="button"
                onClick={() => setShowTopConversationMenu(!showTopConversationMenu)}
                aria-label="Conversation options"
                aria-haspopup="true"
                aria-expanded={showTopConversationMenu}
                className={`p-1.5 rounded-lg transition-colors cursor-pointer select-none ${
                  showTopConversationMenu
                    ? 'bg-white/[0.12] text-white'
                    : 'text-[#EDEDED] hover:text-white hover:bg-white/[0.08]'
                }`}
                title="Conversation options"
              >
                <MoreHorizontal className="w-5 h-5" />
              </button>

              {showTopConversationMenu && (
                <div
                  role="menu"
                  aria-label="Conversation options"
                  className="absolute right-0 top-full mt-2 w-[240px] bg-[#323232] rounded-[20px] p-2 shadow-2xl z-50 animate-in fade-in duration-100 border border-white/[0.06] select-none"
                  style={{
                    boxShadow: '0 16px 40px rgba(0, 0, 0, 0.85), 0 0 0 1px rgba(255, 255, 255, 0.06)',
                  }}
                >
                  <div className="flex flex-col gap-0.5">
                    {/* 1. View files in chat */}
                    <button
                      ref={el => { menuItemsRef.current[0] = el; }}
                      onKeyDown={(e) => handleMenuKeyDown(e, 0)}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setShowTopConversationMenu(false);
                        setShowConversationFilesSheet(true);
                      }}
                      className="flex items-center gap-3 px-3.5 py-2.5 rounded-[14px] hover:bg-white/[0.08] text-[#F5F5F5] transition-colors cursor-pointer w-full text-left focus:bg-white/[0.08] focus:outline-none"
                    >
                      <svg className="w-5 h-5 text-[#F0F0F0] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <rect x="3" y="4" width="4.5" height="16" rx="1.8" />
                        <rect x="9.5" y="4" width="4.5" height="16" rx="1.8" />
                        <path d="M16 4.8a1.8 1.8 0 0 1 2.2-.9l.2.1a1.8 1.8 0 0 1 1 2.2l-4.2 13.5a1.8 1.8 0 0 1-2.2 1l-.2-.1a1.8 1.8 0 0 1-1-2.2l4.2-13.6z" />
                      </svg>
                      <span className="text-[15px] font-normal leading-tight">View files in chat</span>
                    </button>

                    {/* 2. Pin chat / Unpin chat */}
                    <button
                      ref={el => { menuItemsRef.current[1] = el; }}
                      onKeyDown={(e) => handleMenuKeyDown(e, 1)}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setShowTopConversationMenu(false);
                        if (activeConvId) {
                          const isPinned = !!conversations.find(c => c.id === activeConvId)?.pinned;
                          handleTogglePinChat(activeConvId, isPinned);
                        }
                      }}
                      className="flex items-center gap-3 px-3.5 py-2.5 rounded-[14px] hover:bg-white/[0.08] text-[#F5F5F5] transition-colors cursor-pointer w-full text-left focus:bg-white/[0.08] focus:outline-none"
                    >
                      <svg className="w-5 h-5 text-[#F0F0F0] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="12" y1="17" x2="12" y2="22" />
                        <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.76V6h1a1 1 0 0 0 0-2H8a1 1 0 0 0 0 2h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
                      </svg>
                      <span className="text-[15px] font-normal leading-tight">
                        {conversations.find(c => c.id === activeConvId)?.pinned ? 'Unpin chat' : 'Pin chat'}
                      </span>
                    </button>

                    {/* 3. Archive */}
                    <button
                      ref={el => { menuItemsRef.current[2] = el; }}
                      onKeyDown={(e) => handleMenuKeyDown(e, 2)}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setShowTopConversationMenu(false);
                        if (activeConvId) {
                          handleArchiveChat(activeConvId);
                        }
                      }}
                      className="flex items-center gap-3 px-3.5 py-2.5 rounded-[14px] hover:bg-white/[0.08] text-[#F5F5F5] transition-colors cursor-pointer w-full text-left focus:bg-white/[0.08] focus:outline-none"
                    >
                      <svg className="w-5 h-5 text-[#F0F0F0] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="21 8 21 21 3 21 3 8" />
                        <rect x="1" y="3" width="22" height="5" rx="1.5" />
                        <line x1="10" y1="12" x2="14" y2="12" />
                      </svg>
                      <span className="text-[15px] font-normal leading-tight">Archive</span>
                    </button>

                    {/* 4. Delete */}
                    <button
                      ref={el => { menuItemsRef.current[3] = el; }}
                      onKeyDown={(e) => handleMenuKeyDown(e, 3)}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setShowTopConversationMenu(false);
                        if (activeConvId) {
                          const conv = conversations.find(c => c.id === activeConvId);
                          setDeleteModalChat({ id: activeConvId, title: conv?.title || 'Chat' });
                        }
                      }}
                      className="flex items-center gap-3 px-3.5 py-2.5 rounded-[14px] hover:bg-white/[0.08] transition-colors cursor-pointer w-full text-left focus:bg-white/[0.08] focus:outline-none"
                    >
                      <svg className="w-5 h-5 text-[#FF4242] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      </svg>
                      <span className="text-[15px] font-normal text-[#FF4242] leading-tight">Delete</span>
                    </button>
                  </div>
                </div>
              )}
            </div>

            {!rightOpen && (
              <button onClick={() => setRightOpen(true)} className="p-2 text-[#6B6B6B] hover:text-white hover:bg-white/[0.08] rounded-lg transition-colors cursor-pointer ml-1" title="Open operations panel">
                <PanelRightOpen className="w-[18px] h-[18px]" />
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {activeView === 'chat' ? (
            <div className="max-w-[48rem] mx-auto px-6 pb-36 pt-2">

            {messages.length === 0 && !streamingResponse ? (
              <div className="flex flex-col items-center justify-center pt-[28vh] gap-3 select-none">
                <SakuraLogo size={36} className="opacity-80 hover:opacity-100 transition-opacity" alt="Sakura AI" />
                <h1 className="text-[26px] font-medium text-[#EDEDED] tracking-tight">Ask Sakura AI</h1>
              </div>
            ) : (
              <div className="flex flex-col gap-7">
                {messages.map((m, i) => (
                  <div key={i}>
                    {m.role === 'user' ? (
                      <div className="flex justify-end">
                        <div className="bg-[#0E0E0E] border border-[#1F1F1F] px-5 py-3 rounded-3xl max-w-[70%] text-[16px] leading-[1.65]">
                          {m.content}
                        </div>
                      </div>
                    ) : (
                      <div className="flex gap-3.5">
                        <div className="flex-shrink-0 mt-0.5 select-none">
                          <SakuraLogo size={20} alt="Sakura" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <MarkdownContent
                            content={m.content}
                            onOpenLightbox={handleOpenLightbox}
                            onEdit={handleImageEdit}
                            onRegenerate={handleImageRegenerate}
                            onVariation={handleImageVariation}
                            onUpscale={handleImageUpscale}
                          />
                          <div className="flex items-center gap-0.5 mt-3 -ml-1.5">
                            <button onClick={() => handleCopy(m.content, i)} className="p-1.5 text-[#6B6B6B] hover:text-white hover:bg-[#1A1A1A] rounded-lg transition-colors cursor-pointer" title="Copy">
                              {copiedIdx === i ? <CheckCircle className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
                            </button>
                            <button className="p-1.5 text-[#6B6B6B] hover:text-white hover:bg-[#1A1A1A] rounded-lg transition-colors cursor-pointer" title="Retry"><RefreshCw className="w-4 h-4" /></button>
                            <button className="p-1.5 text-[#6B6B6B] hover:text-white hover:bg-[#1A1A1A] rounded-lg transition-colors cursor-pointer" title="Good"><ThumbsUp className="w-4 h-4" /></button>
                            <button className="p-1.5 text-[#6B6B6B] hover:text-white hover:bg-[#1A1A1A] rounded-lg transition-colors cursor-pointer" title="Bad"><ThumbsDown className="w-4 h-4" /></button>
                            <button className="p-1.5 text-[#6B6B6B] hover:text-white hover:bg-[#1A1A1A] rounded-lg transition-colors cursor-pointer" title="More"><MoreHorizontal className="w-4 h-4" /></button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                ))}

                {(streamingResponse || loadingResponse) && (
                  <div className="flex gap-3.5">
                    <div className="flex-shrink-0 mt-0.5 select-none animate-pulse">
                      <SakuraLogo size={20} alt="Sakura" />
                    </div>
                    <div className="flex-1 min-w-0">
                      {streamingResponse ? (
                        <MarkdownContent
                          content={streamingResponse}
                          onOpenLightbox={handleOpenLightbox}
                          onEdit={handleImageEdit}
                          onRegenerate={handleImageRegenerate}
                          onVariation={handleImageVariation}
                          onUpscale={handleImageUpscale}
                        />
                      ) : (
                        <div className="flex items-center gap-2.5 py-2 text-[#8D8D8D] text-[13.5px]">
                          <span>Thinking...</span>
                          <span className="flex gap-1">
                            <span className="w-1.5 h-1.5 bg-[#8D8D8D] rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                            <span className="w-1.5 h-1.5 bg-[#8D8D8D] rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                            <span className="w-1.5 h-1.5 bg-[#8D8D8D] rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
            <div ref={chatEndRef} />
            </div>
          ) : activeView === 'library' ? (
            <LibraryView
              onAttachToChat={(file) => {
                setAttachedFromLibrary(file);
                setActiveView('chat');
              }}
              onNavigateToChat={() => setActiveView('chat')}
              apiBase={apiBase}
            />
          ) : (
            <div className="max-w-[48rem] mx-auto px-6 pb-36 pt-20 flex flex-col items-center justify-center h-full text-[#6B6B6B]">
              <SakuraIcon size={48} opacity={0.15} />
              <h2 className="text-[20px] text-white mt-6 mb-2 tracking-wide font-semibold capitalize">{activeView}</h2>
              <p className="text-[14px]">This module is currently offline.</p>
            </div>
          )}
        </div>

        {/* Composer */}
        {activeView === 'chat' && (
          <div className="flex-shrink-0 pb-4 px-4">
            <ChatComposer
              onSendMessage={handleSendMessage}
              onStopGeneration={handleStopGeneration}
              isGenerating={loadingResponse}
              documents={documents}
              onRefreshDocuments={fetchDocuments}
              apiBase={apiBase}
              placeholder="Ask Sakura AI"
              externalAttachment={attachedFromLibrary}
              onClearExternalAttachment={() => setAttachedFromLibrary(null)}
              editingImage={editingImage}
              onClearEditingImage={() => setEditingImage(null)}
            />
          </div>
        )}
      </div>

      {/* ═══ COLLAPSED RAIL (DESKTOP) ═══ */}
      {!rightOpen && isDesktop && (
        <div 
          onClick={() => setRightOpen(true)} 
          className="flex-shrink-0 w-12 bg-black border-l border-[#1F1F1F] flex flex-col items-center py-4 cursor-pointer hover:bg-[#050505] transition-colors gap-6 justify-between select-none"
          title="Click to expand Operations Panel"
        >
          <div className="flex flex-col items-center gap-4">
            <div className={`w-2 h-2 rounded-full ${wsState === 'LIVE' ? 'bg-[#35D0BA] animate-pulse' : 'bg-[#FF453A]'}`} title={`Status: ${wsState}`} />
            <PanelRightOpen className="w-4 h-4 text-[#6B6B6B]" />
          </div>
          
          <div className="flex flex-col gap-4 text-[#8E8E8E] font-mono text-[9px]">
            {tasks.filter(t => ["Queued", "Starting", "Running", "Waiting"].includes(t.status)).length > 0 && (
              <div className="flex flex-col items-center" title="Active Tasks">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[#35D0BA]" />
                <span className="mt-1">{tasks.filter(t => ["Queued", "Starting", "Running", "Waiting"].includes(t.status)).length}</span>
              </div>
            )}
            
            <div className="flex flex-col items-center" title="Knowledge Base Files">
              <Folder className="w-3.5 h-3.5 text-[#4A8EFF]" />
              <span className="mt-1">{documents.length}</span>
            </div>
          </div>
          
          <div className="text-[#3A3A3A] font-bold text-[8px] rotate-90 my-4 select-none whitespace-nowrap">SAKURA AI</div>
        </div>
      )}

      {/* ═══ DESKTOP SIDEBAR ═══ */}
      {isDesktop && rightOpen && (
        <div className="flex-shrink-0 flex flex-col bg-black border-l border-[#1F1F1F] w-[280px] h-full transition-all duration-200">
          <div className="h-[52px] flex items-center justify-between px-3 flex-shrink-0 border-b border-[#1F1F1F]">
            <div className="flex items-center gap-2 px-1">
              <div className={`w-1.5 h-1.5 rounded-full ${wsState === 'LIVE' ? 'bg-[#35D0BA] animate-pulse' : 'bg-[#FF453A]'}`} />
              <span className="text-[10px] font-bold tracking-[.12em] uppercase text-[#A3A3A3]" style={{ fontFamily: "'JetBrains Mono', monospace" }}>OP: {currentUser?.substring(0, 1).toUpperCase() || 'A'}</span>
            </div>
            <div className="flex items-center gap-1">
              <button onClick={handleLogout} className="p-1.5 text-[#6B6B6B] hover:text-white transition-colors cursor-pointer rounded-lg hover:bg-[#1A1A1A]">
                <LogOut className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => setRightOpen(false)} className="p-1.5 text-[#6B6B6B] hover:text-white transition-colors cursor-pointer rounded-lg hover:bg-[#1A1A1A]">
                <PanelRightClose className="w-4 h-4" />
              </button>
            </div>
          </div>
          
          <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-6">
            {renderPanelContent()}
          </div>
          
          <div className="flex-shrink-0 border-t border-[#1F1F1F] px-4 py-3">
            <span className="text-[8px] font-bold tracking-[.15em] text-[#3A3A3A]" style={{ fontFamily: "'JetBrains Mono', monospace" }}>SAKURA AI · Operations Panel</span>
          </div>
        </div>
      )}

      {/* ═══ TABLET / MOBILE OVERLAY DRAWER ═══ */}
      {(isTablet || isMobile) && rightOpen && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 bg-black/60 z-40 backdrop-blur-xs transition-opacity duration-200" onClick={() => setRightOpen(false)} />
          
          {/* Drawer Container */}
          <div className={`fixed right-0 top-0 h-full bg-black z-50 border-l border-[#1F1F1F] shadow-2xl flex flex-col transition-all duration-300 ${
            isMobile ? 'w-full' : 'w-[320px]'
          }`}>
            <div className="h-[52px] flex items-center justify-between px-4 flex-shrink-0 border-b border-[#1F1F1F]">
              <div className="flex items-center gap-2">
                <div className={`w-1.5 h-1.5 rounded-full ${wsState === 'LIVE' ? 'bg-[#35D0BA] animate-pulse' : 'bg-[#FF453A]'}`} />
                <span className="text-[10px] font-bold tracking-[.12em] uppercase text-[#A3A3A3]" style={{ fontFamily: "'JetBrains Mono', monospace" }}>OP: {currentUser?.substring(0, 1).toUpperCase() || 'A'}</span>
              </div>
              <button onClick={() => setRightOpen(false)} className="p-1.5 text-[#6B6B6B] hover:text-white transition-colors cursor-pointer rounded-lg hover:bg-[#1A1A1A]">
                <PanelRightClose className="w-5 h-5" />
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-6">
              {renderPanelContent()}
            </div>
            
            <div className="flex-shrink-0 border-t border-[#1F1F1F] px-4 py-3 pb-safe">
              <span className="text-[8px] font-bold tracking-[.15em] text-[#3A3A3A]" style={{ fontFamily: "'JetBrains Mono', monospace" }}>SAKURA AI</span>
            </div>
          </div>
        </>
      )}

      {/* ─── NEW TASK MODAL ─── */}
      {showNewTaskModal && (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4 backdrop-blur-xs">
          <div className="bg-[#0A0A0A] border border-[#1F1F1F] rounded-xl w-full max-w-md overflow-hidden shadow-2xl flex flex-col p-5 gap-4">
            <div className="flex justify-between items-center border-b border-[#1F1F1F] pb-3">
              <h3 className="text-[14px] font-bold text-white tracking-wider font-mono">CREATE NEW OPERATIONAL TASK</h3>
              <button onClick={() => setShowNewTaskModal(false)} className="text-[#6B6B6B] hover:text-white font-bold">&times;</button>
            </div>
            
            <div className="flex flex-col gap-3 font-mono text-[12px]">
              <div className="flex flex-col gap-1">
                <label className="text-[#6B6B6B]">Task Type</label>
                <select 
                  value={newTaskType} 
                  onChange={(e) => {
                    setNewTaskType(e.target.value as any);
                    setNewTaskPayload({});
                  }}
                  className="bg-black border border-[#1F1F1F] text-white p-2 rounded focus:outline-none"
                >
                  <option value="code_analysis">Code Analysis</option>
                  <option value="doc_summary">Document Summary</option>
                  <option value="dataset_analysis">Dataset Analysis</option>
                  <option value="web_research">Web Research</option>
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-[#6B6B6B]">Task Name/Title</label>
                <input 
                  type="text" 
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  placeholder="e.g. Analyze router.py performance"
                  className="bg-black border border-[#1F1F1F] text-white p-2 rounded focus:outline-none"
                />
              </div>

              {newTaskType === 'code_analysis' && (
                <>
                  <div className="flex flex-col gap-1">
                    <label className="text-[#6B6B6B]">Instruction</label>
                    <input 
                      type="text" 
                      placeholder="e.g. explain, debug, optimize"
                      value={newTaskPayload.task || ''}
                      onChange={(e) => setNewTaskPayload({ ...newTaskPayload, task: e.target.value })}
                      className="bg-black border border-[#1F1F1F] text-white p-2 rounded focus:outline-none"
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[#6B6B6B]">Code Snippet</label>
                    <textarea 
                      rows={5}
                      placeholder="Paste your source code here..."
                      value={newTaskPayload.code || ''}
                      onChange={(e) => setNewTaskPayload({ ...newTaskPayload, code: e.target.value })}
                      className="bg-black border border-[#1F1F1F] text-white p-2 rounded focus:outline-none font-mono text-[11px]"
                    />
                  </div>
                </>
              )}

              {newTaskType === 'doc_summary' && (
                <div className="flex flex-col gap-1">
                  <label className="text-[#6B6B6B]">Select Target Document</label>
                  <select
                    value={newTaskPayload.document_id || ''}
                    onChange={(e) => setNewTaskPayload({ ...newTaskPayload, document_id: e.target.value })}
                    className="bg-black border border-[#1F1F1F] text-white p-2 rounded focus:outline-none"
                  >
                    <option value="">-- Choose Document --</option>
                    {documents.map(d => (
                      <option key={d.id} value={d.id}>{d.filename}</option>
                    ))}
                  </select>
                </div>
              )}

              {newTaskType === 'dataset_analysis' && (
                <div className="flex flex-col gap-1">
                  <label className="text-[#6B6B6B]">Dataset Text (CSV / Values)</label>
                  <textarea 
                    rows={5}
                    placeholder="column1,column2,column3..."
                    value={newTaskPayload.dataset_text || ''}
                    onChange={(e) => setNewTaskPayload({ ...newTaskPayload, dataset_text: e.target.value })}
                    className="bg-black border border-[#1F1F1F] text-white p-2 rounded focus:outline-none font-mono text-[11px]"
                  />
                </div>
              )}

              {newTaskType === 'web_research' && (
                <div className="flex flex-col gap-1">
                  <label className="text-[#6B6B6B]">Search/Research Query</label>
                  <input 
                    type="text" 
                    placeholder="e.g. NextJS 15 React Compiler features"
                    value={newTaskPayload.query || ''}
                    onChange={(e) => setNewTaskPayload({ ...newTaskPayload, query: e.target.value })}
                    className="bg-black border border-[#1F1F1F] text-white p-2 rounded focus:outline-none"
                  />
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 mt-2">
              <button 
                onClick={() => setShowNewTaskModal(false)}
                className="px-4 py-2 border border-[#1F1F1F] text-[#A3A3A3] hover:text-white rounded text-[11px] font-mono hover:bg-[#111] transition-colors"
              >
                CANCEL
              </button>
              <button 
                onClick={handleCreateTask}
                className="px-4 py-2 bg-white text-black font-bold rounded text-[11px] font-mono hover:bg-neutral-200 transition-colors"
              >
                CREATE TASK
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── RENAME FILE MODAL ─── */}
      {showRenameModal && (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4 backdrop-blur-xs">
          <div className="bg-[#0A0A0A] border border-[#1F1F1F] rounded-xl w-full max-w-sm overflow-hidden shadow-2xl flex flex-col p-5 gap-4">
            <div className="flex justify-between items-center border-b border-[#1F1F1F] pb-3">
              <h3 className="text-[13px] font-bold text-white tracking-wider font-mono">RENAME DOCUMENT</h3>
              <button onClick={() => setShowRenameModal(false)} className="text-[#6B6B6B] hover:text-white font-bold">&times;</button>
            </div>
            
            <div className="flex flex-col gap-1 font-mono text-[12px]">
              <label className="text-[#6B6B6B]">New Filename</label>
              <input 
                type="text" 
                value={newFileName}
                onChange={(e) => setNewFileName(e.target.value)}
                className="bg-black border border-[#1F1F1F] text-white p-2 rounded focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-2 mt-2">
              <button 
                onClick={() => setShowRenameModal(false)}
                className="px-4 py-2 border border-[#1F1F1F] text-[#A3A3A3] hover:text-white rounded text-[11px] font-mono hover:bg-[#111] transition-colors"
              >
                CANCEL
              </button>
              <button 
                onClick={handleRenameFile}
                className="px-4 py-2 bg-white text-black font-bold rounded text-[11px] font-mono hover:bg-neutral-200 transition-colors"
              >
                SAVE
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── CHAT OPTION MODALS ─── */}
      {shareModalChat && (
        <ShareModal
          isOpen={true}
          onClose={() => setShareModalChat(null)}
          chatId={shareModalChat.id}
          chatTitle={shareModalChat.title}
        />
      )}

      {deleteModalChat && (
        <DeleteConfirmModal
          isOpen={true}
          onClose={() => setDeleteModalChat(null)}
          chatTitle={deleteModalChat.title}
          onConfirm={() => handleConfirmDeleteChat(deleteModalChat.id)}
        />
      )}

      {/* ─── CONVERSATION FILES SHEET ─── */}
      <ConversationFilesSheet
        isOpen={showConversationFilesSheet}
        onClose={() => setShowConversationFilesSheet(false)}
        conversationId={activeConvId}
        conversationTitle={getActiveTitle()}
        onAttachToChat={(file) => setAttachedFromLibrary(file)}
        apiBase={apiBase}
      />

      {/* ─── IMAGE LIGHTBOX MODAL ─── */}
      <ImageLightboxModal
        isOpen={lightboxState.isOpen}
        onClose={() => setLightboxState(prev => ({ ...prev, isOpen: false }))}
        imageUrl={lightboxState.url}
        altText={lightboxState.altText}
        metadata={lightboxState.metadata}
        onEdit={handleImageEdit}
        onVariation={handleImageVariation}
        onUpscale={handleImageUpscale}
      />

      {/* ─── ACCOUNT MENU POPOVER ─── */}
      {showAccountMenu && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setShowAccountMenu(false)}
          />
          <div
            className={`fixed z-50 bg-[#121212] border border-[#262626] rounded-xl shadow-2xl p-1.5 flex flex-col gap-0.5 text-[13px] text-[#E0E0E0] select-none animate-in fade-in duration-100 ${
              sidebarOpen ? 'left-[268px] bottom-3 w-60' : 'left-[62px] bottom-3 w-60'
            }`}
          >
            <div className="px-3 py-2.5 flex items-center gap-2.5 border-b border-[#202020] mb-1">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#9880ED] to-[#E98297] flex items-center justify-center text-[12px] font-bold text-white flex-shrink-0">
                {currentUser ? currentUser.substring(0, 1).toUpperCase() : 'S'}
              </div>
              <div className="flex flex-col min-w-0">
                <span className="font-semibold text-white truncate text-[13.5px]">{currentUser || 'Operator'}</span>
                <span className="text-[11px] text-[#7A7A7A]">Sakura Plus</span>
              </div>
            </div>

            <button
              onClick={() => { setShowAccountMenu(false); setShowSettingsModal(true); }}
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-[#1E1E1E] hover:text-white transition-colors cursor-pointer text-left"
            >
              <Settings className="w-4 h-4 text-[#888888]" />
              <span>Settings</span>
            </button>

            <button
              onClick={() => { setShowAccountMenu(false); }}
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-[#1E1E1E] hover:text-white transition-colors cursor-pointer text-left"
            >
              <Moon className="w-4 h-4 text-[#888888]" />
              <span>Appearance: Pitch Black</span>
            </button>

            <button
              onClick={() => { setShowAccountMenu(false); }}
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-[#1E1E1E] hover:text-white transition-colors cursor-pointer text-left"
            >
              <HelpCircle className="w-4 h-4 text-[#888888]" />
              <span>Help & FAQ</span>
            </button>

            <div className="h-[1px] bg-[#202020] my-1" />

            <button
              onClick={() => { setShowAccountMenu(false); handleLogout(); }}
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-[#2A1519] hover:text-[#FF6B8B] text-[#E08A9A] transition-colors cursor-pointer text-left"
            >
              <LogOut className="w-4 h-4" />
              <span>Log out</span>
            </button>
          </div>
        </>
      )}

      {/* ─── SEARCH MODAL ─── */}
      {showSearchModal && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-xs z-50 flex items-start justify-center pt-24 px-4">
          <div
            className="fixed inset-0"
            onClick={() => setShowSearchModal(false)}
          />
          <div className="relative bg-[#121212] border border-[#262626] rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden flex flex-col z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center px-4 py-3.5 border-b border-[#222222] gap-3">
              <Search className="w-5 h-5 text-[#888888]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search conversations..."
                className="flex-1 bg-transparent text-[#F5F5F5] placeholder-[#666666] outline-none text-[15px]"
                autoFocus
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="text-[#888888] hover:text-white text-xs px-2 py-0.5 rounded bg-[#202020] cursor-pointer"
                >
                  Clear
                </button>
              )}
              <button
                onClick={() => setShowSearchModal(false)}
                className="text-[#888888] hover:text-white p-1 rounded-lg hover:bg-[#202020] transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="max-h-[380px] overflow-y-auto p-2 flex flex-col gap-1">
              {filteredConversations.length === 0 ? (
                <div className="py-10 text-center text-[#666666] text-sm">
                  {searchQuery ? 'No matching conversations found' : 'No conversations yet'}
                </div>
              ) : (
                filteredConversations.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => {
                      selectConversation(c.id);
                      setShowSearchModal(false);
                      setSearchQuery('');
                    }}
                    className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl hover:bg-[#1C1C1C] transition-colors text-left group cursor-pointer w-full"
                  >
                    <MessageSquare className="w-4 h-4 text-[#888888] group-hover:text-white flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-[14px] text-[#EDEDED] group-hover:text-white truncate font-normal">
                        {c.title}
                      </div>
                      <div className="text-[11px] text-[#666666]">
                        {c.pinned ? 'Pinned · ' : ''}{new Date(c.updated_at || c.created_at).toLocaleDateString()}
                      </div>
                    </div>
                  </button>
                ))
              )}
            </div>

            <div className="px-4 py-2 bg-[#0A0A0A] border-t border-[#1F1F1F] flex items-center justify-between text-[11.5px] text-[#666666]">
              <span>Search conversations</span>
              <span>ESC to close</span>
            </div>
          </div>
        </div>
      )}

      {/* ─── SETTINGS MODAL ─── */}
      {showSettingsModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-xs z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0" onClick={() => setShowSettingsModal(false)} />
          <div className="relative bg-[#121212] border border-[#262626] rounded-2xl w-full max-w-md shadow-2xl p-5 flex flex-col gap-4 z-10 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex justify-between items-center border-b border-[#222222] pb-3">
              <div className="flex items-center gap-2">
                <Settings className="w-5 h-5 text-[#FF7597]" />
                <h3 className="text-[15px] font-semibold text-white">Settings</h3>
              </div>
              <button onClick={() => setShowSettingsModal(false)} className="text-[#888888] hover:text-white p-1 rounded-lg hover:bg-[#202020] cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex flex-col gap-4 text-[13.5px]">
              <div className="flex items-center justify-between py-1">
                <div>
                  <div className="text-white font-medium">Theme</div>
                  <div className="text-xs text-[#777777]">Ultra-minimal pitch-black aesthetic</div>
                </div>
                <span className="text-xs font-mono bg-[#1E1E1E] text-[#FF7597] px-2.5 py-1 rounded-md border border-[#333333]">
                  Pitch Black (#000000)
                </span>
              </div>

              <div className="flex items-center justify-between py-1">
                <div>
                  <div className="text-white font-medium">Keyboard Shortcuts</div>
                  <div className="text-xs text-[#777777]">Quick console navigation</div>
                </div>
                <div className="flex flex-col gap-1 items-end text-xs font-mono text-[#888888]">
                  <span>Toggle Sidebar: <kbd className="bg-[#202020] px-1.5 py-0.5 rounded text-white">Ctrl+[</kbd></span>
                  <span>Search: <kbd className="bg-[#202020] px-1.5 py-0.5 rounded text-white">Ctrl+K</kbd></span>
                </div>
              </div>

              <div className="flex items-center justify-between py-1">
                <div>
                  <div className="text-white font-medium">Platform</div>
                  <div className="text-xs text-[#777777]">Sakura AI Autonomous Core</div>
                </div>
                <span className="text-xs font-mono text-[#888888]">v2.4.0</span>
              </div>
            </div>

            <div className="flex justify-end pt-2 border-t border-[#222222]">
              <button
                onClick={() => setShowSettingsModal(false)}
                className="px-4 py-1.5 bg-[#202020] hover:bg-[#282828] text-white rounded-lg text-[13px] font-medium transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════ Sub-components ═══════════════ */

function SidebarToggleIcon({ className = "w-[19px] h-[19px]" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="3.5" y="4" width="17" height="16" rx="3.5" />
      <line x1="9" y1="4" x2="9" y2="20" />
    </svg>
  );
}

function SakuraIcon({ size = 18, opacity = 1 }: { size?: number; opacity?: number }) {
  return <SakuraLogo size={size} style={{ opacity }} alt="Sakura AI" />;
}

function NewChatIcon({ className = "w-[18px] h-[18px] text-white flex-shrink-0" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3H6a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3h12a3 3 0 0 0 3-3v-6" />
      <path d="M18.4 2.6a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4Z" />
    </svg>
  );
}

function ShareIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>;
}

function LibraryIcon({ className = "w-[18px] h-[18px] text-white flex-shrink-0" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="4.5" height="16" rx="1.8" />
      <rect x="9.5" y="4" width="4.5" height="16" rx="1.8" />
      <path d="M16 4.8a1.8 1.8 0 0 1 2.2-.9l.2.1a1.8 1.8 0 0 1 1 2.2l-4.2 13.5a1.8 1.8 0 0 1-2.2 1l-.2-.1a1.8 1.8 0 0 1-1-2.2l4.2-13.6z" />
    </svg>
  );
}

function ProjectsIcon({ className = "w-[18px] h-[18px] text-white flex-shrink-0" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 20a2.5 2.5 0 0 0 2.5-2.5V8.5A2.5 2.5 0 0 0 20 6h-7.8a2 2 0 0 1-1.6-.8l-.8-1A2 2 0 0 0 8.2 3.5H4A2.5 2.5 0 0 0 1.5 6v11.5A2.5 2.5 0 0 0 4 20Z" />
      <line x1="1.5" y1="10" x2="22.5" y2="10" />
    </svg>
  );
}

function ScheduledIcon({ className = "w-[18px] h-[18px] text-white flex-shrink-0" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9.5" />
      <polyline points="12 6.5 12 12 15 15" />
    </svg>
  );
}

function GridIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>;
}

function ChatBubbleIcon({ className = "w-[15px] h-[15px] text-[#A0A0A0] flex-shrink-0" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
    </svg>
  );
}

function RailIconButton({
  icon,
  label,
  active = false,
  onClick,
  ariaLabel
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick: () => void;
  ariaLabel?: string;
}) {
  return (
    <div className="relative group flex items-center justify-center w-full">
      <button
        type="button"
        onClick={onClick}
        aria-label={ariaLabel || label}
        className={`w-11 h-11 flex items-center justify-center rounded-lg transition-colors cursor-pointer text-[#F2F2F2] hover:text-white ${
          active ? 'bg-[#1F1F1F]' : 'hover:bg-[#191919]'
        }`}
      >
        {icon}
      </button>
      {/* Dark tooltip appearing to the right */}
      <div className="absolute left-[54px] top-1/2 -translate-y-1/2 hidden group-hover:flex items-center z-50 pointer-events-none">
        <div className="bg-[#2A2A2A] text-[#F5F5F5] text-[13px] font-medium px-2.5 py-1 rounded-md shadow-xl border border-[#383838]/80 whitespace-nowrap">
          {label}
        </div>
      </div>
    </div>
  );
}

function SidebarNavItem({
  icon,
  label,
  active,
  onClick
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group flex items-center gap-3 px-2.5 h-[36px] rounded-[8px] text-[14px] transition-colors cursor-pointer w-full text-left select-none ${
        active
          ? 'bg-[#212121] text-white font-medium'
          : 'text-[#EDEDED] hover:text-white hover:bg-[#161616]'
      }`}
    >
      <span className="text-[#ECECEC] group-hover:text-white flex-shrink-0 flex items-center justify-center">{icon}</span>
      <span className="leading-tight font-normal truncate">{label}</span>
    </button>
  );
}

function SidebarChatItem({
  label,
  active,
  isPinned,
  showIcon = false,
  isEditing,
  onStartRename,
  onSaveRename,
  onCancelRename,
  onClick,
  onDelete,
  onTogglePin,
  onShare,
  onArchive
}: {
  label: string;
  active?: boolean;
  isPinned?: boolean;
  showIcon?: boolean;
  isEditing?: boolean;
  onStartRename?: () => void;
  onSaveRename?: (newTitle: string) => void;
  onCancelRename?: () => void;
  onClick?: () => void;
  onDelete?: () => void;
  onTogglePin?: () => void;
  onShare?: () => void;
  onArchive?: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [editValue, setEditValue] = useState(label);
  const inputRef = useRef<HTMLInputElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setEditValue(label);
  }, [label]);

  useEffect(() => {
    if (isEditing) {
      if (inputRef.current) {
        inputRef.current.focus();
        inputRef.current.select();
      }
    }
  }, [isEditing]);

  const handleToggleMenu = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (buttonRef.current) {
      setAnchorRect(buttonRef.current.getBoundingClientRect());
    }
    setMenuOpen(prev => !prev);
  };

  const handleCommitRename = () => {
    const trimmed = editValue.trim();
    if (!trimmed) {
      setEditValue(label);
      if (onCancelRename) onCancelRename();
      return;
    }
    if (trimmed !== label) {
      if (onSaveRename) onSaveRename(trimmed);
    } else {
      if (onCancelRename) onCancelRename();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleCommitRename();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setEditValue(label);
      if (onCancelRename) onCancelRename();
    } else if (e.key === 'Tab') {
      handleCommitRename();
    }
  };

  return (
    <>
      <div
        className={`relative group flex items-center justify-between px-2.5 h-[36px] rounded-[8px] text-[14px] transition-colors cursor-pointer w-full select-none ${
          active
            ? 'bg-[#212121] text-white font-medium'
            : 'text-[#EDEDED] hover:bg-[#161616] hover:text-white'
        }`}
        onClick={() => {
          if (!isEditing && onClick) onClick();
        }}
        title={!isEditing ? label : undefined}
      >
        <div className="flex items-center gap-2.5 min-w-0 flex-1 pr-1">
          {showIcon && (
            <ChatBubbleIcon className={`w-[15px] h-[15px] ${active ? 'text-white' : 'text-[#8E8E8E] group-hover:text-[#CCCCCC]'} transition-colors flex-shrink-0`} />
          )}
          
          {isEditing ? (
            <input
              ref={inputRef}
              type="text"
              aria-label="Rename conversation"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onKeyDown={handleKeyDown}
              onBlur={handleCommitRename}
              onClick={(e) => e.stopPropagation()}
              maxLength={200}
              className="bg-transparent border-none outline-none shadow-none p-0 m-0 w-full min-w-0 text-[14px] leading-tight text-[#F5F5F5] font-normal caret-white selection:bg-[#4A8EFF]/40"
            />
          ) : (
            <span className="truncate flex-1 text-left text-[14px] leading-tight font-normal">
              {label}
            </span>
          )}
        </div>

        {!isEditing && (
          <div className="flex items-center gap-1 flex-shrink-0">
            {isPinned && !showIcon && (
              <Pin className="w-3.5 h-3.5 text-[#8E8E8E] flex-shrink-0" />
            )}

            <button
              ref={buttonRef}
              type="button"
              aria-label="Conversation options"
              onClick={handleToggleMenu}
              className={`p-1 rounded-md text-[#8E8E8E] hover:text-white hover:bg-[#2A2A2A] transition-all cursor-pointer ${
                active || menuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus:opacity-100'
              }`}
              title="Options"
            >
              <MoreHorizontal className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>

      <ChatPopoverMenu
        isOpen={menuOpen}
        onClose={() => setMenuOpen(false)}
        isPinned={isPinned}
        anchorRect={anchorRect}
        onShare={() => { if (onShare) onShare(); setMenuOpen(false); }}
        onRename={() => {
          setMenuOpen(false);
          if (onStartRename) onStartRename();
        }}
        onTogglePin={() => { if (onTogglePin) onTogglePin(); setMenuOpen(false); }}
        onArchive={() => { if (onArchive) onArchive(); setMenuOpen(false); }}
        onDelete={() => { if (onDelete) onDelete(); setMenuOpen(false); }}
      />
    </>
  );
}

function PanelHeading({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="w-1.5 h-1.5 bg-[#9880ED]" />
      <span className="text-[10px] font-bold tracking-[.12em] uppercase text-[#A3A3A3]" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{label}</span>
    </div>
  );
}

function MiniMeter({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-[9px] text-[#6B6B6B]"><span>{label}</span><span>{value}%</span></div>
      <div className="w-full h-[2px] bg-[#1F1F1F] rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${value}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

function MiniTask({ icon, label, time }: { icon: React.ReactNode; label: string; time: string }) {
  return (
    <div className="flex justify-between py-1.5 border-b border-[#1F1F1F] text-[#A3A3A3]">
      <div className="flex items-center gap-2 text-[12px]">{icon} {label}</div>
      <span className="text-[9px] text-[#6B6B6B]" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{time}</span>
    </div>
  );
}

/* ═══════════════ Interactive Image Card ═══════════════ */
function InteractiveImageCard({
  src,
  alt,
  metadata,
  onOpenLightbox,
  onEdit,
  onRegenerate,
  onVariation,
  onUpscale
}: {
  src: string;
  alt: string;
  metadata?: ImageMetadata | null;
  onOpenLightbox: (src: string, alt: string, meta?: ImageMetadata | null) => void;
  onEdit?: (meta: ImageMetadata) => void;
  onRegenerate?: (prompt: string) => void;
  onVariation?: (meta: ImageMetadata) => void;
  onUpscale?: (meta: ImageMetadata) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [isUpscaling, setIsUpscaling] = useState(false);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    const fullUrl = src.startsWith('http') ? src : (typeof window !== 'undefined' ? window.location.origin + src : src);
    navigator.clipboard.writeText(fullUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = (e: React.MouseEvent) => {
    e.stopPropagation();
    const a = document.createElement('a');
    a.href = src;
    const dateStr = new Date().toISOString().split('T')[0];
    a.download = metadata?.filename || `sakura-ai-image-${dateStr}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleUpscaleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onUpscale) {
      setIsUpscaling(true);
      onUpscale(metadata || { prompt: alt, url: src });
      setTimeout(() => setIsUpscaling(false), 4000);
    }
  };

  const formattedMeta = `${metadata?.aspect_ratio || '1:1'} · ${metadata?.width || 1024}×${metadata?.height || 1024}`;

  return (
    <div className="my-4 rounded-[16px] overflow-hidden border border-[#292929] bg-[#101010] max-w-[680px] shadow-2xl group transition-all">
      {/* Generated Image Container */}
      <div
        onClick={() => onOpenLightbox(src, alt, metadata)}
        className="relative overflow-hidden cursor-zoom-in bg-[#000000] flex items-center justify-center min-h-[240px] max-h-[540px]"
      >
        <img
          src={src}
          alt={alt}
          className="w-full h-auto max-h-[540px] object-contain transition-transform duration-200 group-hover:scale-[1.008]"
          loading="lazy"
        />
        {/* Subtle temporary overlay on hover */}
        <div className="absolute inset-0 bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center justify-center pointer-events-none">
          <div className="px-3.5 py-1.5 rounded-full bg-[#181818]/90 backdrop-blur-md text-[#F4F4F4] text-[12px] font-medium flex items-center gap-1.5 border border-[#292929] shadow-lg">
            <ZoomIn className="w-3.5 h-3.5 text-[#8D8D8D]" />
            <span>Click to expand</span>
          </div>
        </div>
      </div>

      {/* Card Footer */}
      <div className="p-3.5 bg-[#111111] border-t border-[#292929] flex flex-col gap-2.5">
        {/* Description & Metadata Row */}
        <div className="flex items-center justify-between gap-3">
          <span className="text-[13.5px] font-normal text-[#F4F4F4] truncate flex-1 leading-snug">
            {metadata?.prompt || alt}
          </span>
          <span className="text-[12px] text-[#8D8D8D] font-mono flex-shrink-0 whitespace-nowrap">
            {formattedMeta}
          </span>
        </div>

        {/* Action Toolbar */}
        <div className="flex items-center justify-between pt-1 border-t border-[#1F1F1F] gap-1.5 flex-wrap">
          {/* Left Action Buttons */}
          <div className="flex items-center gap-1.5 flex-wrap">
            {onEdit && (
              <button
                type="button"
                onClick={() => onEdit(metadata || { prompt: alt, url: src })}
                className="px-3 py-1.5 rounded-[9px] bg-[#181818] hover:bg-[#252525] text-[#F4F4F4] text-[12px] font-medium transition-colors flex items-center gap-1.5 border border-[#292929] cursor-pointer"
                title="Edit this image in chat"
              >
                <Pencil className="w-3.5 h-3.5 text-[#8D8D8D]" />
                <span>Edit</span>
              </button>
            )}

            {onVariation && (
              <button
                type="button"
                onClick={() => onVariation(metadata || { prompt: alt, url: src })}
                className="px-3 py-1.5 rounded-[9px] bg-[#181818] hover:bg-[#252525] text-[#F4F4F4] text-[12px] font-medium transition-colors flex items-center gap-1.5 border border-[#292929] cursor-pointer"
                title="Create variations"
              >
                <span>Variations</span>
              </button>
            )}

            {onRegenerate && (
              <button
                type="button"
                onClick={() => onRegenerate(metadata?.prompt || alt)}
                className="px-3 py-1.5 rounded-[9px] bg-[#181818] hover:bg-[#252525] text-[#F4F4F4] text-[12px] font-medium transition-colors flex items-center gap-1.5 border border-[#292929] cursor-pointer"
                title="Regenerate artwork"
              >
                <RefreshCw className="w-3.5 h-3.5 text-[#8D8D8D]" />
                <span>Regenerate</span>
              </button>
            )}

            {onUpscale && (
              <button
                type="button"
                onClick={handleUpscaleClick}
                disabled={isUpscaling}
                className="px-3 py-1.5 rounded-[9px] bg-[#181818] hover:bg-[#252525] text-[#F4F4F4] text-[12px] font-medium transition-colors flex items-center gap-1.5 border border-[#292929] cursor-pointer disabled:opacity-50"
                title="Upscale 2×"
              >
                <span>{isUpscaling ? 'Upscaling...' : 'Upscale'}</span>
              </button>
            )}
          </div>

          {/* Right Utility Icons */}
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleCopy}
              className="p-1.5 rounded-[8px] text-[#8D8D8D] hover:text-[#F4F4F4] hover:bg-[#181818] transition-colors cursor-pointer"
              title={copied ? "Copied image link" : "Copy image"}
            >
              {copied ? <Check className="w-4 h-4 text-[#35D0BA]" /> : <Copy className="w-4 h-4" />}
            </button>

            <button
              type="button"
              onClick={handleDownload}
              className="p-1.5 rounded-[8px] text-[#8D8D8D] hover:text-[#F4F4F4] hover:bg-[#181818] transition-colors cursor-pointer"
              title="Download image"
            >
              <Download className="w-4 h-4" />
            </button>

            <button
              type="button"
              onClick={() => onOpenLightbox(src, alt, metadata)}
              className="p-1.5 rounded-[8px] text-[#8D8D8D] hover:text-[#F4F4F4] hover:bg-[#181818] transition-colors cursor-pointer"
              title="Image info"
            >
              <Info className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════ Markdown Renderer ═══════════════ */
function MarkdownContent({
  content,
  onOpenLightbox,
  onEdit,
  onRegenerate,
  onVariation,
  onUpscale
}: {
  content: string;
  onOpenLightbox?: (src: string, alt: string, meta?: ImageMetadata | null) => void;
  onEdit?: (meta: ImageMetadata) => void;
  onRegenerate?: (prompt: string) => void;
  onVariation?: (meta: ImageMetadata) => void;
  onUpscale?: (meta: ImageMetadata) => void;
}) {
  let extractedMeta: ImageMetadata | null = null;
  const metaMatch = content.match(/<!--\s*SAKURA_IMAGE_DATA:\s*(\{.*?\})\s*-->/);
  if (metaMatch) {
    try {
      extractedMeta = JSON.parse(metaMatch[1]);
    } catch (e) {
      console.error('Failed to parse image metadata', e);
    }
  }

  const cleaned = content
    .replace(/<think>[\s\S]*?(?:<\/think>|$)/g, '')
    .replace(/<!--\s*SAKURA_IMAGE_DATA:\s*\{.*?\}\s*-->/g, '')
    .trim();

  const parts = cleaned.split('```');
  return (
    <div className="text-[16px] leading-[1.7] text-[#D1D1D1]">
      {parts.map((part, i) => {
        if (i % 2 === 1) {
          const lines = part.trim().split('\n');
          const lang = lines[0] || '';
          const code = lines.slice(1).join('\n');
          return (
            <div key={i} className="my-4 bg-[#0A0A0A] rounded-xl overflow-hidden border border-[#1F1F1F]" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {lang && (
                <div className="px-4 py-2 border-b border-[#1F1F1F] text-[12px] text-[#6B6B6B] flex justify-between items-center">
                  <span>{lang}</span>
                  <button className="text-[#6B6B6B] hover:text-white transition-colors cursor-pointer text-[11px] flex items-center gap-1"><Copy className="w-3.5 h-3.5" /> Copy</button>
                </div>
              )}
              <div className="p-4 overflow-x-auto text-[14px] leading-[1.6]">
                <pre className="text-[#E8E8E8]"><code>{code}</code></pre>
              </div>
            </div>
          );
        }
        return (
          <TextBlock
            key={i}
            text={part}
            imageMetadata={extractedMeta}
            onOpenLightbox={onOpenLightbox}
            onEdit={onEdit}
            onRegenerate={onRegenerate}
            onVariation={onVariation}
            onUpscale={onUpscale}
          />
        );
      })}
    </div>
  );
}

function TextBlock({
  text,
  imageMetadata,
  onOpenLightbox,
  onEdit,
  onRegenerate,
  onVariation,
  onUpscale
}: {
  text: string;
  imageMetadata?: ImageMetadata | null;
  onOpenLightbox?: (src: string, alt: string, meta?: ImageMetadata | null) => void;
  onEdit?: (meta: ImageMetadata) => void;
  onRegenerate?: (prompt: string) => void;
  onVariation?: (meta: ImageMetadata) => void;
  onUpscale?: (meta: ImageMetadata) => void;
}) {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let listItems: { text: string; ordered: boolean }[] = [];
  let tableRows: string[][] = [];

  const flushList = (key: string) => {
    if (listItems.length > 0) {
      const isOrdered = listItems[0].ordered;
      const Tag = isOrdered ? 'ol' : 'ul';
      const cls = isOrdered ? 'list-decimal' : 'list-disc';
      elements.push(
        <Tag key={key} className={`${cls} pl-6 flex flex-col gap-1.5 my-3 text-[#D1D1D1] marker:text-[#6B6B6B]`}>
          {listItems.map((li, j) => <li key={j}><InlineFormat text={li.text} /></li>)}
        </Tag>
      );
      listItems = [];
    }
  };

  const flushTable = (key: string) => {
    if (tableRows.length > 0) {
      const header = tableRows[0];
      const rows = tableRows.slice(1).filter(r => !r.every(c => c.match(/^:?-+:?$/)));
      elements.push(
        <div key={key} className="my-4 overflow-x-auto rounded-xl border border-[#262626] bg-[#0E0E0E]">
          <table className="w-full text-left text-[13.5px]">
            {header && (
              <thead className="bg-[#181818] border-b border-[#262626] text-white">
                <tr>
                  {header.map((th, hi) => (
                    <th key={hi} className="px-3.5 py-2.5 font-medium"><InlineFormat text={th} /></th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody className="divide-y divide-[#1A1A1A]">
              {rows.map((row, ri) => (
                <tr key={ri} className="hover:bg-[#141414] transition-colors">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-3.5 py-2 text-[#CCCCCC]"><InlineFormat text={cell} /></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      tableRows = [];
    }
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList(`f-${idx}`);
      flushTable(`t-${idx}`);
      return;
    }

    // Image detection: ![alt](url)
    const imgMatch = trimmed.match(/^!\[(.*?)\]\((.*?)\)$/);
    if (imgMatch) {
      flushList(`f-${idx}`);
      flushTable(`t-${idx}`);
      const alt = imgMatch[1];
      const src = imgMatch[2];
      elements.push(
        <InteractiveImageCard
          key={idx}
          src={src}
          alt={alt}
          metadata={imageMetadata}
          onOpenLightbox={onOpenLightbox || ((s, a, m) => {})}
          onEdit={onEdit}
          onRegenerate={onRegenerate}
          onVariation={onVariation}
          onUpscale={onUpscale}
        />
      );
      return;
    }

    // Table row detection: | col1 | col2 |
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      flushList(`f-${idx}`);
      const cols = trimmed.split('|').slice(1, -1).map(c => c.trim());
      tableRows.push(cols);
      return;
    } else {
      flushTable(`t-${idx}`);
    }

    const h3m = trimmed.match(/^###\s+(.+)/); if (h3m) { flushList(`f-${idx}`); elements.push(<h4 key={idx} className="text-[16px] font-semibold text-white mt-6 mb-2">{h3m[1]}</h4>); return; }
    const h2m = trimmed.match(/^##\s+(.+)/); if (h2m) { flushList(`f-${idx}`); elements.push(<h3 key={idx} className="text-[18px] font-semibold text-white mt-6 mb-2">{h2m[1]}</h3>); return; }
    const h1m = trimmed.match(/^#\s+(.+)/); if (h1m) { flushList(`f-${idx}`); elements.push(<h2 key={idx} className="text-[22px] font-semibold text-white mt-6 mb-3">{h1m[1]}</h2>); return; }
    const bm = trimmed.match(/^[-*]\s+(.+)/); if (bm) { listItems.push({ text: bm[1], ordered: false }); return; }
    const nm = trimmed.match(/^\d+\.\s+(.+)/); if (nm) { listItems.push({ text: nm[1], ordered: true }); return; }
    flushList(`f-${idx}`);
    elements.push(<p key={idx} className="my-2"><InlineFormat text={trimmed} /></p>);
  });
  flushList('final');
  flushTable('final-tbl');
  return <>{elements}</>;
}

function InlineFormat({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**')) return <strong key={i} className="font-semibold text-white">{p.slice(2, -2)}</strong>;
        if (p.startsWith('`') && p.endsWith('`')) return <code key={i} className="bg-[#141414] border border-[#1F1F1F] px-1.5 py-0.5 rounded text-[14px] text-[#E8E8E8]" style={{ fontFamily: "'JetBrains Mono', monospace" }}>{p.slice(1, -1)}</code>;
        const linkMatch = p.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        if (linkMatch) {
          return (
            <a key={i} href={linkMatch[2]} target="_blank" rel="noopener noreferrer" className="text-[#35D0BA] underline hover:text-[#5EEAD4] transition-colors">
              {linkMatch[1]}
            </a>
          );
        }
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}
