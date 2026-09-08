import React, { useState, useEffect } from 'react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { ConversationView } from './ConversationView';
import { ContextPanel } from './ContextPanel';
import { LibraryView } from '../LibraryView';
import { ProjectsView } from '../ProjectsView';
import { ScheduledView } from '../ScheduledView';
import { PluginsView } from '../PluginsView';
import { ShareModal, DeleteConfirmModal } from '../ChatModals';
import { ImageLightboxModal, ImageMetadata } from '../ImageLightboxModal';
import { ConversationFilesSheet } from '../ConversationFilesSheet';
import { SearchModal } from '../SearchModal';
import { useConversation, Conversation } from '../../hooks/useConversation';
import { useCapabilities } from '../../hooks/useCapabilities';
import { useTasks } from '../../hooks/useTasks';
import { useWorkspace } from '../../hooks/useWorkspace';
import { useRealtime } from '../../hooks/useRealtime';

export interface AppShellProps {
  currentUser: string | null;
  onLogout: () => void;
}

export const AppShell: React.FC<AppShellProps> = ({ currentUser, onLogout }) => {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const [activeView, setActiveView] = useState<'chat' | 'library' | 'projects' | 'scheduled' | 'plugins'>('chat');
  const [pendingAttachment, setPendingAttachment] = useState<any>(null);
  const [windowWidth, setWindowWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1200);

  // Modals state
  const [shareModalChat, setShareModalChat] = useState<{ id: string; title: string } | null>(null);
  const [deleteModalChat, setDeleteModalChat] = useState<{ id: string; title: string } | null>(null);
  const [showFilesSheet, setShowFilesSheet] = useState(false);
  const [showSearchModal, setShowSearchModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  // Lightbox
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

  // Hooks
  const {
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
  } = useConversation();

  const { capabilities } = useCapabilities();
  const { tasks, cancelTask, retryTask, clearCompleted, setTasks } = useTasks();
  const { workspaces, activeWorkspaceId, selectWorkspace } = useWorkspace();

  // Realtime WebSocket integration
  useRealtime({
    onMessage: (msg) => {
      if (msg.type === 'tasks_list' && Array.isArray(msg.data)) {
        setTasks(msg.data);
      } else if (msg.type === 'task_update' && msg.data) {
        setTasks(prev => {
          const idx = prev.findIndex(t => t.id === msg.data.id);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = msg.data;
            return next;
          }
          return [msg.data, ...prev];
        });
      } else if (msg.type === 'conversation_created' && msg.data) {
        setConversations(prev => [msg.data, ...prev.filter(c => c.id !== msg.data.id)]);
      } else if (msg.type === 'conversation_updated' && msg.data) {
        setConversations(prev => prev.map(c => (c.id === msg.data.id ? { ...c, ...msg.data } : c)));
      } else if (msg.type === 'conversation_deleted' && msg.id) {
        setConversations(prev => prev.filter(c => c.id !== msg.id));
      }
    }
  });

  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const isMobile = windowWidth < 768;

  const handleCopyMessage = (content: string, idx: number) => {
    navigator.clipboard.writeText(content);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  const handleOpenLightbox = (src: string, alt: string, meta?: any) => {
    setLightboxState({
      isOpen: true,
      url: src,
      altText: alt,
      metadata: meta || null
    });
  };

  const currentChatTitle = activeConversation?.title || 'New Chat';

  return (
    <div className="flex h-screen w-screen bg-[#000000] text-neutral-100 font-sans overflow-hidden select-none">
      {/* Sidebar */}
      <Sidebar
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        conversations={conversations}
        activeConvId={activeConvId}
        onSelectConversation={selectConversation}
        onNewChat={() => {
          createNewConversation();
          setActiveView('chat');
        }}
        onOpenSearch={() => setShowSearchModal(true)}
        activeView={activeView}
        onSelectView={setActiveView}
        onPinConversation={(id, isPinned) => togglePin(id, isPinned)}
        onRenameConversation={(id, currentTitle) => {
          const newTitle = prompt('Rename conversation:', currentTitle);
          if (newTitle && newTitle.trim()) renameConversation(id, newTitle.trim());
        }}
        onDeleteConversation={(id, title) => setDeleteModalChat({ id, title })}
        onShareConversation={(id, title) => setShareModalChat({ id, title })}
        isMobile={isMobile}
      />

      {/* Main Workspace Column */}
      <div className="flex-1 flex flex-col h-full min-w-0 bg-[#000000]">
        {/* TopBar */}
        <TopBar
          title={currentChatTitle}
          conversationId={activeConvId}
          onRenameTitle={(newTitle) => activeConvId && renameConversation(activeConvId, newTitle)}
          workspaces={workspaces}
          activeWorkspaceId={activeWorkspaceId}
          onSelectWorkspace={selectWorkspace}
          capabilities={capabilities}
          rightPanelOpen={rightPanelOpen}
          onToggleRightPanel={() => setRightPanelOpen(!rightPanelOpen)}
          onOpenShareModal={() => activeConvId && setShareModalChat({ id: activeConvId, title: currentChatTitle })}
          onOpenFilesSheet={() => setShowFilesSheet(true)}
          currentUser={currentUser}
          onLogout={onLogout}
        />

        {/* Dynamic Center View */}
        <div className="flex-1 flex h-[calc(100vh-3.5rem)] overflow-hidden">
          <main className="flex-1 flex flex-col h-full overflow-hidden min-w-0 bg-[#000000]">
            {activeView === 'chat' && (
              <ConversationView
                messages={messages}
                streamingResponse={streamingResponse}
                streamingProvider={streamingProvider}
                loadingResponse={loadingResponse}
                onSendMessage={(payload) => {
                  sendMessage({
                    ...payload,
                    active_workspace_id: activeWorkspaceId
                  });
                }}
                onStopGeneration={stopGeneration}
                onCopyMessage={handleCopyMessage}
                copiedIdx={copiedIdx}
                onFeedback={provideFeedback}
                feedbackState={feedbackState}
                onSelectPrompt={(prompt) => {
                  sendMessage({
                    message: prompt,
                    intensity: 'medium',
                    tools: [],
                    attachments: [],
                    active_workspace_id: activeWorkspaceId
                  });
                }}
                onImageLightbox={handleOpenLightbox}
                externalAttachment={pendingAttachment}
                onClearExternalAttachment={() => setPendingAttachment(null)}
              />
            )}

            {activeView === 'library' && (
              <LibraryView
                onAttachToChat={(file) => {
                  setPendingAttachment(file);
                  setActiveView('chat');
                }}
                onNavigateToChat={() => setActiveView('chat')}
              />
            )}

            {activeView === 'projects' && (
              <ProjectsView
                onNavigateToChat={(conversationId) => {
                  if (conversationId) selectConversation(conversationId);
                  setActiveView('chat');
                }}
              />
            )}

            {activeView === 'scheduled' && (
              <ScheduledView />
            )}

            {activeView === 'plugins' && (
              <PluginsView />
            )}
          </main>

          {/* Collapsible Right Context Panel */}
          <ContextPanel
            isOpen={rightPanelOpen}
            onClose={() => setRightPanelOpen(false)}
            tasks={tasks}
            onCancelTask={cancelTask}
            onRetryTask={retryTask}
            onClearCompletedTasks={clearCompleted}
          />
        </div>
      </div>

      {/* Global Modals */}
      {shareModalChat && (
        <ShareModal
          isOpen={Boolean(shareModalChat)}
          chatId={shareModalChat.id}
          chatTitle={shareModalChat.title}
          onClose={() => setShareModalChat(null)}
        />
      )}

      {deleteModalChat && (
        <DeleteConfirmModal
          isOpen={Boolean(deleteModalChat)}
          chatTitle={deleteModalChat.title}
          onConfirm={() => {
            deleteConversation(deleteModalChat.id);
            setDeleteModalChat(null);
          }}
          onClose={() => setDeleteModalChat(null)}
        />
      )}

      {lightboxState.isOpen && (
        <ImageLightboxModal
          isOpen={lightboxState.isOpen}
          imageUrl={lightboxState.url}
          altText={lightboxState.altText}
          metadata={lightboxState.metadata}
          onClose={() => setLightboxState(prev => ({ ...prev, isOpen: false }))}
          onVariation={() => {
            setLightboxState(prev => ({ ...prev, isOpen: false }));
            sendMessage({
              message: `Create variations of this image: ${lightboxState.metadata?.prompt || ''}`,
              intensity: 'medium',
              tools: ['create_image'],
              attachments: lightboxState.metadata?.id ? [{ id: lightboxState.metadata.id, filename: lightboxState.metadata.filename || 'image.png', mime_type: 'image/png' }] : []
            });
          }}
          onEdit={() => {
            setLightboxState(prev => ({ ...prev, isOpen: false }));
          }}
        />
      )}

      {showFilesSheet && activeConvId && (
        <ConversationFilesSheet
          isOpen={showFilesSheet}
          conversationId={activeConvId}
          onClose={() => setShowFilesSheet(false)}
        />
      )}

      <SearchModal
        isOpen={showSearchModal}
        initialQuery={searchQuery}
        onClose={() => setShowSearchModal(false)}
        onSelectConversation={(id) => {
          selectConversation(id);
          setActiveView('chat');
          setShowSearchModal(false);
        }}
      />
    </div>
  );
};
