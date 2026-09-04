import React, { useState, useEffect } from 'react';
import { 
  Folder, Plus, Search, GitBranch, FileText, MessageSquare, 
  Trash2, ExternalLink, ArrowLeft, MoreHorizontal, Settings,
  Check, AlertCircle, Loader2, BookOpen
} from 'lucide-react';
import { SakuraLogo } from './SakuraLogo';

interface Repository {
  id: string;
  name: string;
  repository_url: string;
  default_branch: string;
  created_at: string;
}

interface ProjectDoc {
  id: string;
  name: string;
  filename: string;
  mime_type: string;
  created_at: string;
}

interface ProjectConv {
  id: string;
  title: string;
  updated_at: string;
}

interface ProjectItem {
  id: string;
  name: string;
  description: string;
  instructions: string;
  created_at: string;
  updated_at: string;
  repositories_count: number;
  files_count: number;
  conversations_count: number;
  repositories?: Repository[];
  files?: ProjectDoc[];
  conversations?: ProjectConv[];
}

interface ProjectsViewProps {
  apiBase?: string;
  onNavigateToChat: (conversationId?: string) => void;
}

export const ProjectsView: React.FC<ProjectsViewProps> = ({
  apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  onNavigateToChat
}) => {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedProject, setSelectedProject] = useState<ProjectItem | null>(null);
  const [projectLoading, setProjectLoading] = useState(false);

  // New project modal
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectDesc, setNewProjectDesc] = useState('');
  const [newProjectInstructions, setNewProjectInstructions] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Attach repo modal
  const [isAttachRepoOpen, setIsAttachRepoOpen] = useState(false);
  const [repoUrl, setRepoUrl] = useState('');
  const [repoName, setRepoName] = useState('');

  const getAuthToken = () => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('token') || '';
    }
    return '';
  };

  const fetchProjects = async () => {
    try {
      setLoading(true);
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/projects`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setProjects(data);
      }
    } catch (err) {
      console.error('Failed to load projects:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  const fetchProjectDetails = async (id: string) => {
    try {
      setProjectLoading(true);
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/projects/${id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedProject(data);
      }
    } catch (err) {
      console.error('Failed to load project details:', err);
    } finally {
      setProjectLoading(false);
    }
  };

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    try {
      setSubmitting(true);
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/projects`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          name: newProjectName.trim(),
          description: newProjectDesc.trim(),
          instructions: newProjectInstructions.trim()
        })
      });
      if (res.ok) {
        const created = await res.json();
        setIsCreateModalOpen(false);
        setNewProjectName('');
        setNewProjectDesc('');
        setNewProjectInstructions('');
        await fetchProjects();
        setSelectedProject(created);
      }
    } catch (err) {
      console.error('Failed to create project:', err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteProject = async (id: string) => {
    if (!confirm('Are you sure you want to delete this project?')) return;
    try {
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/projects/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        setSelectedProject(null);
        await fetchProjects();
      }
    } catch (err) {
      console.error('Failed to delete project:', err);
    }
  };

  const handleAttachRepo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProject || !repoUrl.trim()) return;
    try {
      setSubmitting(true);
      const token = getAuthToken();
      const name = repoName.trim() || repoUrl.split('/').pop()?.replace('.git', '') || 'repo';
      const res = await fetch(`${apiBase}/api/v1/projects/${selectedProject.id}/repositories`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          repository_url: repoUrl.trim(),
          name
        })
      });
      if (res.ok) {
        setIsAttachRepoOpen(false);
        setRepoUrl('');
        setRepoName('');
        await fetchProjectDetails(selectedProject.id);
      }
    } catch (err) {
      console.error('Failed to attach repository:', err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateProjectConversation = async () => {
    if (!selectedProject) return;
    try {
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/projects/${selectedProject.id}/conversations`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          title: `Project: ${selectedProject.name}`
        })
      });
      if (res.ok) {
        const conv = await res.json();
        onNavigateToChat(conv.id);
      }
    } catch (err) {
      console.error('Failed to create project chat:', err);
    }
  };

  const filtered = projects.filter(p => 
    p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (p.description || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex-1 flex flex-col h-full bg-[#121212] text-[#ECECEC] overflow-y-auto">
      {/* Header bar */}
      <div className="sticky top-0 z-20 flex items-center justify-between px-8 py-4 bg-[#121212]/95 backdrop-blur-md border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          {selectedProject ? (
            <button
              onClick={() => setSelectedProject(null)}
              className="p-1.5 -ml-2 text-[#999999] hover:text-white hover:bg-white/[0.06] rounded-lg transition-colors cursor-pointer"
              title="Back to projects"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
          ) : (
            <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
              <Folder className="w-4 h-4" />
            </div>
          )}
          <div>
            <h1 className="text-[18px] font-semibold text-white tracking-tight">
              {selectedProject ? selectedProject.name : 'Projects'}
            </h1>
            <p className="text-[12px] text-[#8E8E8E]">
              {selectedProject 
                ? (selectedProject.description || 'Isolated engineering workspace')
                : 'Organize repositories, custom instructions, and domain knowledge'
              }
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {!selectedProject && (
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-white text-black text-[13px] font-medium hover:bg-[#E0E0E0] active:scale-[0.98] transition-all cursor-pointer shadow-sm"
            >
              <Plus className="w-4 h-4" />
              <span>New Project</span>
            </button>
          )}

          {selectedProject && (
            <div className="flex items-center gap-2">
              <button
                onClick={handleCreateProjectConversation}
                className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-white text-black text-[13px] font-medium hover:bg-[#E0E0E0] active:scale-[0.98] transition-all cursor-pointer shadow-sm"
              >
                <MessageSquare className="w-4 h-4" />
                <span>Start Chat</span>
              </button>
              <button
                onClick={() => handleDeleteProject(selectedProject.id)}
                className="p-2 text-[#8E8E8E] hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors cursor-pointer"
                title="Delete Project"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Main Container */}
      <div className="max-w-6xl w-full mx-auto p-8 flex-1">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-24 gap-3">
            <Loader2 className="w-6 h-6 animate-spin text-white/50" />
            <span className="text-[13px] text-[#8E8E8E]">Loading projects...</span>
          </div>
        ) : !selectedProject ? (
          /* Projects List View */
          <div>
            <div className="flex items-center justify-between mb-6 gap-4">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#777777]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search projects..."
                  className="w-full bg-[#1C1C1C] border border-white/[0.08] rounded-xl pl-10 pr-4 py-2 text-[13.5px] text-white placeholder-[#666666] focus:outline-none focus:border-white/20 transition-colors"
                />
              </div>
            </div>

            {filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 border border-dashed border-white/[0.08] rounded-2xl p-8 text-center">
                <div className="w-12 h-12 rounded-2xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-center mb-4 text-[#888888]">
                  <Folder className="w-6 h-6" />
                </div>
                <h3 className="text-[16px] font-medium text-white mb-1">No projects yet</h3>
                <p className="text-[13px] text-[#888888] max-w-sm mb-6">
                  Create a project to bundle repositories, documentation files, and customized engineering system prompts together.
                </p>
                <button
                  onClick={() => setIsCreateModalOpen(true)}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white text-black text-[13px] font-medium hover:bg-[#E0E0E0] transition-colors cursor-pointer"
                >
                  <Plus className="w-4 h-4" />
                  <span>Create First Project</span>
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {filtered.map((proj) => (
                  <div
                    key={proj.id}
                    onClick={() => fetchProjectDetails(proj.id)}
                    className="group bg-[#181818] hover:bg-[#1F1F1F] border border-white/[0.06] hover:border-white/[0.12] rounded-2xl p-5 transition-all cursor-pointer flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-start justify-between mb-3">
                        <div className="w-9 h-9 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
                          <Folder className="w-4 h-4" />
                        </div>
                        <span className="text-[11px] text-[#666666] font-mono">
                          {new Date(proj.updated_at || proj.created_at).toLocaleDateString()}
                        </span>
                      </div>
                      <h3 className="text-[15px] font-medium text-white group-hover:text-blue-300 transition-colors line-clamp-1 mb-1.5">
                        {proj.name}
                      </h3>
                      <p className="text-[12.5px] text-[#888888] line-clamp-2 leading-relaxed mb-4">
                        {proj.description || 'No description provided.'}
                      </p>
                    </div>

                    <div className="flex items-center gap-4 pt-3 border-t border-white/[0.06] text-[12px] text-[#888888]">
                      <div className="flex items-center gap-1.5" title="Connected Repositories">
                        <GitBranch className="w-3.5 h-3.5 text-[#AAAAAA]" />
                        <span>{proj.repositories_count || 0}</span>
                      </div>
                      <div className="flex items-center gap-1.5" title="Knowledge Base Files">
                        <FileText className="w-3.5 h-3.5 text-[#AAAAAA]" />
                        <span>{proj.files_count || 0}</span>
                      </div>
                      <div className="flex items-center gap-1.5" title="Conversations">
                        <MessageSquare className="w-3.5 h-3.5 text-[#AAAAAA]" />
                        <span>{proj.conversations_count || 0}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          /* Project Detail View */
          <div className="space-y-8">
            {/* Instructions box */}
            <div className="bg-[#181818] border border-white/[0.06] rounded-2xl p-6">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[12px] font-semibold tracking-wider uppercase text-[#888888]">
                  Custom Instructions
                </span>
              </div>
              <p className="text-[13.5px] text-[#CCCCCC] leading-relaxed whitespace-pre-wrap font-sans">
                {selectedProject.instructions || 'No specific instructions set. The assistant operates under Sakura standard software engineering directives.'}
              </p>
            </div>

            {/* Repositories section */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <GitBranch className="w-4 h-4 text-white/70" />
                  <h2 className="text-[15px] font-medium text-white">Linked Repositories</h2>
                </div>
                <button
                  onClick={() => setIsAttachRepoOpen(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-white text-[12.5px] font-medium transition-colors cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Attach Repository</span>
                </button>
              </div>

              {(!selectedProject.repositories || selectedProject.repositories.length === 0) ? (
                <div className="p-6 bg-[#161616] border border-dashed border-white/[0.06] rounded-xl text-center text-[#777777] text-[13px]">
                  No repositories attached to this project yet. Attach a git repo URL to enable repository-level indexing and code editing.
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {selectedProject.repositories.map((repo) => (
                    <div key={repo.id} className="p-4 bg-[#181818] border border-white/[0.06] rounded-xl flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
                          <GitBranch className="w-4 h-4" />
                        </div>
                        <div>
                          <h4 className="text-[13.5px] font-medium text-white">{repo.name}</h4>
                          <p className="text-[11.5px] text-[#777777] truncate max-w-xs">{repo.repository_url}</p>
                        </div>
                      </div>
                      <span className="text-[11px] px-2 py-0.5 rounded-md bg-white/[0.05] text-[#999999] font-mono">
                        {repo.default_branch || 'main'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Conversations section */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <MessageSquare className="w-4 h-4 text-white/70" />
                  <h2 className="text-[15px] font-medium text-white">Project Chats</h2>
                </div>
              </div>

              {(!selectedProject.conversations || selectedProject.conversations.length === 0) ? (
                <div className="p-6 bg-[#161616] border border-dashed border-white/[0.06] rounded-xl text-center text-[#777777] text-[13px]">
                  No chats started within this project yet. Click &quot;Start Chat&quot; above to begin coding.
                </div>
              ) : (
                <div className="divide-y divide-white/[0.04] bg-[#181818] border border-white/[0.06] rounded-xl overflow-hidden">
                  {selectedProject.conversations.map((conv) => (
                    <div
                      key={conv.id}
                      onClick={() => onNavigateToChat(conv.id)}
                      className="p-3.5 px-4 flex items-center justify-between hover:bg-white/[0.03] transition-colors cursor-pointer"
                    >
                      <div className="flex items-center gap-3">
                        <MessageSquare className="w-4 h-4 text-[#888888]" />
                        <span className="text-[13.5px] text-white">{conv.title}</span>
                      </div>
                      <span className="text-[11.5px] text-[#666666]">
                        {new Date(conv.updated_at).toLocaleDateString()}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Create Project Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
          <div className="w-full max-w-lg bg-[#212121] border border-white/[0.08] rounded-2xl p-6 shadow-2xl animate-in fade-in duration-150">
            <h2 className="text-[17px] font-semibold text-white mb-1">Create New Project</h2>
            <p className="text-[13px] text-[#8E8E8E] mb-5">
              Group your codebases, documents, and specialized instructions into a dedicated context.
            </p>

            <form onSubmit={handleCreateProject} className="space-y-4">
              <div>
                <label className="block text-[12px] font-medium text-[#AAAAAA] mb-1.5">Project Name</label>
                <input
                  type="text"
                  required
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  placeholder="e.g., Payment Gateway Microservice"
                  className="w-full bg-[#181818] border border-white/[0.08] rounded-xl px-3.5 py-2.5 text-[13.5px] text-white placeholder-[#555555] focus:outline-none focus:border-white/20 transition-colors"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[#AAAAAA] mb-1.5">Description (Optional)</label>
                <input
                  type="text"
                  value={newProjectDesc}
                  onChange={(e) => setNewProjectDesc(e.target.value)}
                  placeholder="Brief summary of what this project encompasses"
                  className="w-full bg-[#181818] border border-white/[0.08] rounded-xl px-3.5 py-2.5 text-[13.5px] text-white placeholder-[#555555] focus:outline-none focus:border-white/20 transition-colors"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[#AAAAAA] mb-1.5">
                  Custom System Instructions (Optional)
                </label>
                <textarea
                  rows={3}
                  value={newProjectInstructions}
                  onChange={(e) => setNewProjectInstructions(e.target.value)}
                  placeholder="e.g. Always use TypeScript strict mode, follow Clean Architecture patterns, and write unit tests for every new function."
                  className="w-full bg-[#181818] border border-white/[0.08] rounded-xl px-3.5 py-2.5 text-[13.5px] text-white placeholder-[#555555] focus:outline-none focus:border-white/20 transition-colors resize-none"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-4 py-2 text-[13px] text-[#AAAAAA] hover:text-white transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || !newProjectName.trim()}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white text-black text-[13px] font-medium hover:bg-[#E0E0E0] disabled:opacity-50 transition-all cursor-pointer"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>Create Project</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Attach Repo Modal */}
      {isAttachRepoOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
          <div className="w-full max-w-md bg-[#212121] border border-white/[0.08] rounded-2xl p-6 shadow-2xl animate-in fade-in duration-150">
            <h2 className="text-[17px] font-semibold text-white mb-1">Attach Git Repository</h2>
            <p className="text-[13px] text-[#8E8E8E] mb-5">
              Connect a GitHub repository to make its codebase accessible to Sakura Code.
            </p>

            <form onSubmit={handleAttachRepo} className="space-y-4">
              <div>
                <label className="block text-[12px] font-medium text-[#AAAAAA] mb-1.5">Repository URL</label>
                <input
                  type="text"
                  required
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  placeholder="https://github.com/org/repo"
                  className="w-full bg-[#181818] border border-white/[0.08] rounded-xl px-3.5 py-2.5 text-[13.5px] text-white placeholder-[#555555] focus:outline-none focus:border-white/20 transition-colors"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[#AAAAAA] mb-1.5">Display Name (Optional)</label>
                <input
                  type="text"
                  value={repoName}
                  onChange={(e) => setRepoName(e.target.value)}
                  placeholder="e.g. backend-api"
                  className="w-full bg-[#181818] border border-white/[0.08] rounded-xl px-3.5 py-2.5 text-[13.5px] text-white placeholder-[#555555] focus:outline-none focus:border-white/20 transition-colors"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3">
                <button
                  type="button"
                  onClick={() => setIsAttachRepoOpen(false)}
                  className="px-4 py-2 text-[13px] text-[#AAAAAA] hover:text-white transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || !repoUrl.trim()}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white text-black text-[13px] font-medium hover:bg-[#E0E0E0] disabled:opacity-50 transition-all cursor-pointer"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>Attach</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
