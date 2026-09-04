import React, { useState, useEffect } from 'react';
import { 
  Clock, Plus, Play, Pause, Trash2, CheckCircle2, 
  AlertCircle, Loader2, Calendar, Search, MoreHorizontal, ArrowRight
} from 'lucide-react';

interface ScheduledTask {
  id: string;
  title: string;
  prompt: string;
  schedule: string;
  timezone: string;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

interface ScheduledViewProps {
  apiBase?: string;
}

export const ScheduledView: React.FC<ScheduledViewProps> = ({
  apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
}) => {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [runningId, setRunningId] = useState<string | null>(null);

  // New task modal
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [prompt, setPrompt] = useState('');
  const [schedulePreset, setSchedulePreset] = useState('daily_9am');
  const [customCron, setCustomCron] = useState('0 9 * * *');
  const [submitting, setSubmitting] = useState(false);

  const getAuthToken = () => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('token') || '';
    }
    return '';
  };

  const fetchTasks = async () => {
    try {
      setLoading(true);
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/scheduled`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setTasks(data);
      }
    } catch (err) {
      console.error('Failed to load scheduled tasks:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
  }, []);

  const handleToggleTask = async (task: ScheduledTask) => {
    try {
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/scheduled/${task.id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          enabled: !task.enabled
        })
      });
      if (res.ok) {
        await fetchTasks();
      }
    } catch (err) {
      console.error('Failed to toggle scheduled task:', err);
    }
  };

  const handleRunNow = async (id: string) => {
    try {
      setRunningId(id);
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/scheduled/${id}/run`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        await fetchTasks();
      }
    } catch (err) {
      console.error('Failed to trigger task run:', err);
    } finally {
      setRunningId(null);
    }
  };

  const handleDeleteTask = async (id: string) => {
    if (!confirm('Are you sure you want to delete this scheduled task?')) return;
    try {
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/scheduled/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        await fetchTasks();
      }
    } catch (err) {
      console.error('Failed to delete scheduled task:', err);
    }
  };

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !prompt.trim()) return;

    let sched = '0 9 * * *';
    if (schedulePreset === 'hourly') sched = '0 * * * *';
    else if (schedulePreset === 'daily_9am') sched = '0 9 * * *';
    else if (schedulePreset === 'weekly_mon') sched = '0 9 * * 1';
    else if (schedulePreset === 'custom') sched = customCron;

    try {
      setSubmitting(true);
      const token = getAuthToken();
      const res = await fetch(`${apiBase}/api/v1/scheduled`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          title: title.trim(),
          prompt: prompt.trim(),
          schedule: sched,
          timezone: 'UTC',
          enabled: true
        })
      });
      if (res.ok) {
        setIsCreateModalOpen(false);
        setTitle('');
        setPrompt('');
        await fetchTasks();
      }
    } catch (err) {
      console.error('Failed to create scheduled task:', err);
    } finally {
      setSubmitting(false);
    }
  };

  const filtered = tasks.filter(t => 
    t.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    t.prompt.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex-1 flex flex-col h-full bg-[#121212] text-[#ECECEC] overflow-y-auto">
      {/* Header bar */}
      <div className="sticky top-0 z-20 flex items-center justify-between px-8 py-4 bg-[#121212]/95 backdrop-blur-md border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
            <Clock className="w-4 h-4" />
          </div>
          <div>
            <h1 className="text-[18px] font-semibold text-white tracking-tight">Scheduled Tasks</h1>
            <p className="text-[12px] text-[#8E8E8E]">
              Automate periodic engineering jobs, daily reports, and background repository maintenance
            </p>
          </div>
        </div>

        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-white text-black text-[13px] font-medium hover:bg-[#E0E0E0] active:scale-[0.98] transition-all cursor-pointer shadow-sm"
        >
          <Plus className="w-4 h-4" />
          <span>New Scheduled Task</span>
        </button>
      </div>

      {/* Main content */}
      <div className="max-w-5xl w-full mx-auto p-8 flex-1">
        <div className="flex items-center justify-between mb-6 gap-4">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#777777]" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search scheduled tasks..."
              className="w-full bg-[#1C1C1C] border border-white/[0.08] rounded-xl pl-10 pr-4 py-2 text-[13.5px] text-white placeholder-[#666666] focus:outline-none focus:border-white/20 transition-colors"
            />
          </div>
        </div>

        {loading ? (
          <div className="flex flex-col items-center justify-center py-24 gap-3">
            <Loader2 className="w-6 h-6 animate-spin text-white/50" />
            <span className="text-[13px] text-[#8E8E8E]">Loading scheduled tasks...</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 border border-dashed border-white/[0.08] rounded-2xl p-8 text-center">
            <div className="w-12 h-12 rounded-2xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-center mb-4 text-[#888888]">
              <Clock className="w-6 h-6" />
            </div>
            <h3 className="text-[16px] font-medium text-white mb-1">No scheduled tasks</h3>
            <p className="text-[13px] text-[#888888] max-w-sm mb-6">
              Create recurring prompts to audit pull requests, build documentation, or produce morning research summaries.
            </p>
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white text-black text-[13px] font-medium hover:bg-[#E0E0E0] transition-colors cursor-pointer"
            >
              <Plus className="w-4 h-4" />
              <span>Schedule a Task</span>
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((task) => (
              <div
                key={task.id}
                className="bg-[#181818] border border-white/[0.06] hover:border-white/[0.12] rounded-2xl p-5 transition-all flex flex-col md:flex-row items-start md:items-center justify-between gap-4"
              >
                <div className="space-y-1.5 flex-1 min-w-0">
                  <div className="flex items-center gap-2.5">
                    <h3 className="text-[15px] font-medium text-white truncate">{task.title}</h3>
                    <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${
                      task.enabled 
                        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' 
                        : 'bg-white/[0.04] text-[#777777] border-white/[0.06]'
                    }`}>
                      {task.enabled ? 'ACTIVE' : 'PAUSED'}
                    </span>
                  </div>
                  <p className="text-[13px] text-[#888888] line-clamp-1">{task.prompt}</p>
                  
                  <div className="flex items-center gap-4 text-[11.5px] text-[#666666] pt-1">
                    <div className="flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5" />
                      <span>{task.schedule} ({task.timezone})</span>
                    </div>
                    {task.last_run_at && (
                      <div className="flex items-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                        <span>Last run: {new Date(task.last_run_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0 self-end md:self-center">
                  <button
                    onClick={() => handleRunNow(task.id)}
                    disabled={runningId === task.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-white text-[12px] font-medium transition-colors cursor-pointer disabled:opacity-50"
                    title="Trigger immediate execution"
                  >
                    {runningId === task.id ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Play className="w-3.5 h-3.5" />
                    )}
                    <span>Run Now</span>
                  </button>

                  <button
                    onClick={() => handleToggleTask(task)}
                    className="p-2 text-[#8E8E8E] hover:text-white hover:bg-white/[0.06] rounded-lg transition-colors cursor-pointer"
                    title={task.enabled ? 'Pause Task' : 'Resume Task'}
                  >
                    {task.enabled ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                  </button>

                  <button
                    onClick={() => handleDeleteTask(task.id)}
                    className="p-2 text-[#8E8E8E] hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors cursor-pointer"
                    title="Delete Task"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
          <div className="w-full max-w-lg bg-[#212121] border border-white/[0.08] rounded-2xl p-6 shadow-2xl animate-in fade-in duration-150">
            <h2 className="text-[17px] font-semibold text-white mb-1">Create Scheduled Task</h2>
            <p className="text-[13px] text-[#8E8E8E] mb-5">
              Set up automated prompts that execute on a schedule.
            </p>

            <form onSubmit={handleCreateTask} className="space-y-4">
              <div>
                <label className="block text-[12px] font-medium text-[#AAAAAA] mb-1.5">Task Title</label>
                <input
                  type="text"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g., Morning Repository Hygiene Check"
                  className="w-full bg-[#181818] border border-white/[0.08] rounded-xl px-3.5 py-2.5 text-[13.5px] text-white placeholder-[#555555] focus:outline-none focus:border-white/20 transition-colors"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[#AAAAAA] mb-1.5">Agent Prompt</label>
                <textarea
                  rows={3}
                  required
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="e.g. Inspect the latest git commits, check for test failures, and generate a markdown summary."
                  className="w-full bg-[#181818] border border-white/[0.08] rounded-xl px-3.5 py-2.5 text-[13.5px] text-white placeholder-[#555555] focus:outline-none focus:border-white/20 transition-colors resize-none"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[#AAAAAA] mb-1.5">Frequency</label>
                <select
                  value={schedulePreset}
                  onChange={(e) => setSchedulePreset(e.target.value)}
                  className="w-full bg-[#181818] border border-white/[0.08] rounded-xl px-3.5 py-2.5 text-[13.5px] text-white focus:outline-none focus:border-white/20 transition-colors cursor-pointer"
                >
                  <option value="hourly">Every Hour (0 * * * *)</option>
                  <option value="daily_9am">Daily at 9:00 AM UTC (0 9 * * *)</option>
                  <option value="weekly_mon">Weekly on Monday at 9:00 AM UTC (0 9 * * 1)</option>
                  <option value="custom">Custom Cron Expression</option>
                </select>
              </div>

              {schedulePreset === 'custom' && (
                <div>
                  <label className="block text-[12px] font-medium text-[#AAAAAA] mb-1.5">Cron String</label>
                  <input
                    type="text"
                    value={customCron}
                    onChange={(e) => setCustomCron(e.target.value)}
                    placeholder="0 9 * * *"
                    className="w-full bg-[#181818] border border-white/[0.08] rounded-xl px-3.5 py-2.5 text-[13.5px] text-white placeholder-[#555555] font-mono focus:outline-none focus:border-white/20 transition-colors"
                  />
                </div>
              )}

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
                  disabled={submitting || !title.trim() || !prompt.trim()}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white text-black text-[13px] font-medium hover:bg-[#E0E0E0] disabled:opacity-50 transition-all cursor-pointer"
                >
                  {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>Save Schedule</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
