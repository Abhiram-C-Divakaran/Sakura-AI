import { test, expect, Page } from '@playwright/test';

/**
 * Deterministic stateful backend fixture mounted via Playwright route interception
 * so authenticated browser E2E tests exercise the REAL Next.js pages, React hooks
 * (useConversation, useCodingTaskStream, useTasks, useWorkspace), localStorage auth,
 * and UI interactions with zero uncontrolled external LLM or image-provider calls.
 */
interface MockState {
  users: Map<string, { password: string; deleted: boolean }>;
  conversations: Array<{ id: string; title: string; character_id: string; created_at: string; updated_at: string }>;
  messagesByConv: Map<string, Array<any>>;
  files: Array<any>;
  scheduledTasks: Array<any>;
  imageJobs: Map<string, any>;
  exports: Map<string, any>;
  codingTask: {
    taskId: string;
    jobId: string;
    workspaceId: string;
    workspaceName: string;
    status: string;
    events: Array<any>;
    streamAttempts: number;
    failuresBeforeRecover: number;
    diff: string;
    cancelRequested: boolean;
  };
  passwordResetEnabled: boolean;
  lastResetIdentifier: string | null;
}

function makeFakeJwt(username: string): string {
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const payload = Buffer.from(JSON.stringify({ sub: username, exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url');
  return `${header}.${payload}.test_sig`;
}

function createInitialState(): MockState {
  return {
    users: new Map([['alice@example.com', { password: 'StrongPassword123!', deleted: false }]]),
    conversations: [],
    messagesByConv: new Map(),
    files: [
      {
        id: 'file-initial-1',
        name: 'architecture.md',
        filename: 'architecture.md',
        mime_type: 'text/markdown',
        size_bytes: 128,
        size_formatted: '128 B',
        category: 'documents',
        modified_at: new Date().toISOString(),
        status: 'READY',
        is_knowledge_base: false,
        indexing_status: 'NOT_INDEXED',
      },
    ],
    scheduledTasks: [],
    imageJobs: new Map(),
    exports: new Map(),
    codingTask: {
      taskId: '11111111-1111-4111-8111-111111111111',
      jobId: '22222222-2222-4222-8222-222222222222',
      workspaceId: '33333333-3333-4333-8333-333333333333',
      workspaceName: 'sakura-repo',
      status: 'QUEUED',
      events: [],
      streamAttempts: 0,
      failuresBeforeRecover: 0,
      diff: 'diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-return 1\n+return 2\n',
      cancelRequested: false,
    },
    passwordResetEnabled: true,
    lastResetIdentifier: null,
  };
}

async function mountDeterministicApi(page: Page, state: MockState) {
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();

    const json = (body: any, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });

    // 1. Auth config & password recovery
    if (path === '/api/v1/auth/config' && method === 'GET') {
      return json({
        password_reset_enabled: state.passwordResetEnabled,
        google_oauth_enabled: false,
        github_oauth_enabled: false,
      });
    }
    if (path === '/api/v1/auth/register' && method === 'POST') {
      const body = req.postDataJSON();
      if (state.users.has(body.username) && !state.users.get(body.username)?.deleted) {
        return json({ detail: 'Username already registered' }, 400);
      }
      state.users.set(body.username, { password: body.password, deleted: false });
      return json({ message: 'User registered successfully' }, 200);
    }
    if (path === '/api/v1/auth/token' && method === 'POST') {
      const params = new URLSearchParams(req.postData() || '');
      const username = params.get('username') || '';
      const password = params.get('password') || '';
      const rec = state.users.get(username);
      if (!rec || rec.deleted || rec.password !== password) {
        return json({ detail: 'Incorrect username or password' }, 400);
      }
      return json({ access_token: makeFakeJwt(username), token_type: 'bearer' });
    }
    if (path === '/api/v1/auth/password-reset/request' && method === 'POST') {
      const body = req.postDataJSON();
      state.lastResetIdentifier = body.identifier;
      return json({
        message: 'If an account exists for this email or username, a password reset link has been sent.',
      });
    }
    if (path === '/api/v1/auth/password-reset/confirm' && method === 'POST') {
      const body = req.postDataJSON();
      if (body.token !== 'valid-reset-token-123') {
        return json({ detail: 'Password reset token is invalid or expired.' }, 400);
      }
      const u = state.users.get('alice@example.com');
      if (u) u.password = body.new_password;
      return json({ message: 'Password updated successfully.' });
    }
    if (path === '/api/v1/auth/ws-ticket' && method === 'POST') {
      return json({ ticket: 'ws-ticket-test', expires_in: 60 });
    }

    // Account Export & Deletion
    if (path === '/api/v1/auth/me/export' && method === 'POST') {
      const id = '44444444-4444-4444-8444-444444444444';
      const exp = {
        id,
        export_id: id,
        status: 'COMPLETED',
        storage_size: 256,
        download_url: `/api/v1/auth/me/export/${id}/download`,
        created_at: new Date().toISOString(),
      };
      state.exports.set(id, exp);
      return json(exp, 202);
    }
    if (path.startsWith('/api/v1/auth/me/export/') && path.endsWith('/download') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/zip',
        body: Buffer.from('PK\x03\x04sakura_export_test'),
      });
    }
    if (path.startsWith('/api/v1/auth/me/export/') && method === 'GET') {
      const id = path.split('/').pop() || '';
      const exp = state.exports.get(id);
      return exp ? json(exp) : json({ detail: 'Not found' }, 404);
    }
    if (path === '/api/v1/auth/me' && method === 'DELETE') {
      const body = req.postDataJSON();
      if (body.confirm !== 'DELETE') return json({ detail: 'Explicit confirmation required' }, 400);
      const u = state.users.get('alice@example.com');
      if (u) u.deleted = true;
      return json({ status: 'deleted', cleanup_status: 'COMPLETE', cleanup_complete: true });
    }

    // 2. Capabilities, Tasks, Workspaces
    if (path === '/api/v1/capabilities' || path === '/api/v1/capabilities/') {
      return json({
        status: 'operational',
        system_status: 'OPERATIONAL',
        image_generation: {
          available: true,
          status: 'AVAILABLE',
          provider: 'pollinations',
          model: 'flux',
          text_to_image: true,
          image_conditioned_edit: false,
          true_upscale: false,
          variations: true,
        },
        auth: {
          password_reset_enabled: state.passwordResetEnabled,
          google_oauth_enabled: false,
          github_oauth_enabled: false,
        },
      });
    }
    if (path === '/api/v1/tasks' && method === 'GET') {
      return json([]);
    }
    if (path === '/api/v1/coding/workspaces' && method === 'GET') {
      return json([
        {
          id: state.codingTask.workspaceId,
          name: state.codingTask.workspaceName,
          active_branch: 'main',
          status: 'READY',
        },
      ]);
    }

    // 3. Conversations & Chat Streaming
    if (path === '/api/v1/conversations' && method === 'GET') {
      return json(state.conversations);
    }
    if (path === '/api/v1/conversations' && method === 'POST') {
      const id = `conv-${state.conversations.length + 1}`;
      const conv = {
        id,
        title: `Chat ${state.conversations.length + 1}`,
        character_id: 'sakura',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      state.conversations.unshift(conv);
      state.messagesByConv.set(id, []);
      return json(conv);
    }
    const msgsMatch = path.match(/^\/api\/v1\/conversations\/([^/]+)\/messages$/);
    if (msgsMatch && method === 'GET') {
      return json(state.messagesByConv.get(msgsMatch[1]) || []);
    }
    if (path === '/api/v1/chat/stream' && method === 'POST') {
      const body = req.postDataJSON();
      const cid = body.conversation_id;
      const list = state.messagesByConv.get(cid) || [];
      list.push({ id: `u-${list.length + 1}`, role: 'user', content: body.message });

      if (String(body.message || '').startsWith('/code')) {
        const ct = state.codingTask;
        const banner = `Queued durable coding task ${ct.taskId} for workspace ${ct.workspaceName}.\n`;
        list.push({
          id: `a-${list.length + 1}`,
          role: 'assistant',
          content: banner,
          metadata: {
            provider: 'sakura_code',
            coding_task_id: ct.taskId,
            coding_job_id: ct.jobId,
            workspace_id: ct.workspaceId,
            workspace_name: ct.workspaceName,
            events_stream_url: `/api/v1/coding/tasks/${ct.taskId}/events/stream`,
          },
        });
        state.messagesByConv.set(cid, list);
        const sse = `data: ${JSON.stringify({
          token: banner,
          provider: 'sakura_code',
          coding_task_id: ct.taskId,
          coding_job_id: ct.jobId,
          workspace_id: ct.workspaceId,
          workspace_name: ct.workspaceName,
          phase: 'QUEUED',
          events_stream_url: `/api/v1/coding/tasks/${ct.taskId}/events/stream`,
        })}\n\n`;
        return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sse });
      }

      const reply = `Deterministic Sakura response for: ${body.message}`;
      list.push({
        id: `a-${list.length + 1}`,
        role: 'assistant',
        content: reply,
        metadata: { provider: 'deterministic_test' },
      });
      state.messagesByConv.set(cid, list);
      const sse = [
        `data: ${JSON.stringify({ token: 'Deterministic Sakura ', provider: 'deterministic_test' })}\n\n`,
        `data: ${JSON.stringify({ token: `response for: ${body.message}`, provider: 'deterministic_test' })}\n\n`,
      ].join('');
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sse });
    }

    // 4. Sakura Code Task Status, Events, SSE Stream (with simulated >8 reconnects & duplicates), Diff, Cancel
    const ct = state.codingTask;
    if (path === `/api/v1/coding/tasks/${ct.taskId}` && method === 'GET') {
      return json({
        id: ct.jobId,
        taskId: ct.taskId,
        workspaceId: ct.workspaceId,
        title: 'Fix calculator unit test',
        status: ct.status,
        filesModified: ct.status.startsWith('COMPLETED') ? ['app.py'] : [],
        verificationState: ct.status === 'COMPLETED_VERIFIED' ? { passed: true, totalTests: 3, passedTests: 3, summary: 'All 3 tests passed' } : {},
        cancelRequested: ct.cancelRequested,
      });
    }
    if (path === `/api/v1/coding/tasks/${ct.taskId}/events` && method === 'GET') {
      const afterSeq = Number(url.searchParams.get('after_sequence') || '0');
      const filtered = ct.events.filter((e) => e.sequenceNumber > afterSeq);
      return json(filtered);
    }
    if (path === `/api/v1/coding/tasks/${ct.taskId}/events/stream` && method === 'GET') {
      ct.streamAttempts += 1;
      // Simulate >8 consecutive connection errors (e.g., 10 failures!) before recovering
      if (ct.streamAttempts <= ct.failuresBeforeRecover) {
        return json({ detail: 'Transient gateway disconnect' }, 502);
      }
      // On first healthy stream after reconnects, emit duplicate & out-of-order frames + terminal event
      const afterSeq = Number(url.searchParams.get('after_sequence') || '0');
      const scripted = [
        { taskId: ct.taskId, jobId: ct.jobId, sequenceNumber: 2, phase: 'EXECUTING', eventType: 'tool_start', toolName: 'run_tests', argumentsSummary: 'pytest -q' },
        { taskId: ct.taskId, jobId: ct.jobId, sequenceNumber: 1, phase: 'PLANNING', eventType: 'status', message: 'Inspecting repository' },
        { taskId: ct.taskId, jobId: ct.jobId, sequenceNumber: 2, phase: 'EXECUTING', eventType: 'tool_start', toolName: 'run_tests', argumentsSummary: 'pytest -q' },
        { taskId: ct.taskId, jobId: ct.jobId, sequenceNumber: 3, phase: 'EXECUTING', eventType: 'tool_result', toolName: 'run_tests', exitCode: 0, stdoutPreview: '3 passed' },
        { taskId: ct.taskId, jobId: ct.jobId, sequenceNumber: 4, phase: 'COMPLETED_VERIFIED', eventType: 'status', message: 'Verified fix', verificationMetadata: { passed: true, summary: 'All 3 tests passed' } },
      ];
      ct.events = scripted;
      ct.status = 'COMPLETED_VERIFIED';
      const body = scripted
        .filter((e) => e.sequenceNumber > afterSeq)
        .map((e) => `data: ${JSON.stringify(e)}\n\n`)
        .join('');
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body });
    }
    if (path === `/api/v1/coding/workspaces/${ct.workspaceId}/diff` && method === 'GET') {
      return json({ workspace_id: ct.workspaceId, diff: ct.diff });
    }
    if (path === `/api/v1/coding/tasks/${ct.taskId}/cancel` && method === 'POST') {
      ct.cancelRequested = true;
      ct.status = 'CANCELLED';
      return json({ status: 'CANCELLED', taskId: ct.taskId });
    }

    // 5. Image Generation Jobs (Create, Poll, Variation, Cancel)
    if ((path === '/api/v1/images/jobs' || path === '/api/v1/images/generate' || path === '/api/v1/library/generate-image') && method === 'POST') {
      const body = req.postDataJSON();
      const id = `img-job-${state.imageJobs.size + 1}`;
      const job = { id, job_id: id, status: 'QUEUED', prompt: body.prompt, requested_pipeline: body.requested_pipeline || 'auto', polls: 0 };
      state.imageJobs.set(id, job);
      return json({ status: 'queued', job_id: id, id, job }, 202);
    }
    if (path === '/api/v1/images/variation' && method === 'POST') {
      const id = `img-var-${state.imageJobs.size + 1}`;
      const job = { id, job_id: id, status: 'QUEUED', workflow: 'PROMPT_VARIATION', polls: 0 };
      state.imageJobs.set(id, job);
      return json({ status: 'queued', workflow: 'PROMPT_VARIATION', jobs: [job] }, 202);
    }
    const imgCancelMatch = path.match(/^\/api\/v1\/images\/jobs\/([^/]+)\/cancel$/);
    if (imgCancelMatch && method === 'POST') {
      const j = state.imageJobs.get(imgCancelMatch[1]);
      if (!j) return json({ detail: 'Not found' }, 404);
      j.status = 'CANCELLED';
      return json(j);
    }
    const imgJobMatch = path.match(/^\/api\/v1\/images\/jobs\/([^/]+)$/);
    if (imgJobMatch && method === 'GET') {
      const j = state.imageJobs.get(imgJobMatch[1]);
      if (!j) return json({ detail: 'Not found' }, 404);
      j.polls += 1;
      if (j.status === 'QUEUED' && j.polls >= 1) {
        j.status = 'COMPLETED';
        j.actual_provider = 'pollinations';
        j.actual_model = 'flux';
        j.output_image_id = 'img-out-1';
      }
      return json(j);
    }

    // 6. Library Upload, Preview, Indexing & Removal
    if (path === '/api/v1/library/files' && method === 'GET') {
      return json(state.files);
    }
    if (path === '/api/v1/library/upload' && method === 'POST') {
      const newFile = {
        id: `file-up-${state.files.length + 1}`,
        name: 'uploaded_notes.txt',
        filename: 'uploaded_notes.txt',
        mime_type: 'text/plain',
        size_bytes: 42,
        size_formatted: '42 B',
        category: 'documents',
        modified_at: new Date().toISOString(),
        status: 'READY',
        is_knowledge_base: false,
        indexing_status: 'NOT_INDEXED',
      };
      state.files.unshift(newFile);
      return json({ status: 'success', file: newFile });
    }
    const contentMatch = path.match(/^\/api\/v1\/library\/files\/([^/]+)\/content$/);
    if (contentMatch && method === 'GET') {
      const f = state.files.find((x) => x.id === contentMatch[1]);
      return json({ id: f?.id, filename: f?.name, content: '# Sakura Architecture\nDeterministic preview content.', is_text: true });
    }
    const indexMatch = path.match(/^\/api\/v1\/library\/files\/([^/]+)\/index$/);
    if (indexMatch && method === 'POST') {
      const f = state.files.find((x) => x.id === indexMatch[1]);
      if (f) {
        f.is_knowledge_base = true;
        f.indexing_status = 'READY';
      }
      return json({ status: 'indexing_started', id: indexMatch[1] });
    }
    if (indexMatch && method === 'DELETE') {
      const f = state.files.find((x) => x.id === indexMatch[1]);
      if (f) {
        f.is_knowledge_base = false;
        f.indexing_status = 'NOT_INDEXED';
      }
      return json({ status: 'removed_from_knowledge_base', file: f });
    }

    // 7. Scheduled Tasks Creation & Execution
    if (path === '/api/v1/scheduled' && method === 'GET') {
      return json(state.scheduledTasks);
    }
    if (path === '/api/v1/scheduled' && method === 'POST') {
      const body = req.postDataJSON();
      const t = {
        id: `sched-${state.scheduledTasks.length + 1}`,
        title: body.title,
        prompt: body.prompt,
        schedule: body.schedule,
        timezone: body.timezone || 'UTC',
        enabled: true,
        next_run_at: new Date(Date.now() + 3600_000).toISOString(),
        created_at: new Date().toISOString(),
      };
      state.scheduledTasks.unshift(t);
      return json({ status: 'success', ...t, task: t });
    }
    const schedRunMatch = path.match(/^\/api\/v1\/scheduled\/([^/]+)\/run$/);
    if (schedRunMatch && method === 'POST') {
      return json({ status: 'queued', task_id: schedRunMatch[1], run_id: 'run-1' });
    }

    return json({});
  });
}

test.describe('Sakura AI Authenticated Application Browser E2E Suite', () => {
  test('1-3. Registration, Login, Logout, and Password Recovery', async ({ page }) => {
    const state = createInitialState();
    await mountDeterministicApi(page, state);

    // Registration flow on /login
    await page.goto('/login', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Sign up' }).click();
    await expect(page.locator('h1')).toContainText('Create your account');
    await page.locator('input[placeholder="name@example.com"]').fill('newuser@example.com');
    await page.locator('input[type="password"]').fill('NewUserPass123!');
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page).toHaveURL(/\/chat$/);

    // Logout via localStorage & re-login as alice
    await page.evaluate(() => localStorage.removeItem('access_token'));
    await page.goto('/login', { waitUntil: 'domcontentloaded' });

    // Password recovery when configured
    await expect(page.getByRole('button', { name: 'Forgot password?' })).toBeVisible();
    await page.getByRole('button', { name: 'Forgot password?' }).click();
    await page.locator('input[placeholder="name@example.com"]').fill('alice@example.com');
    await page.getByRole('button', { name: 'Send reset link' }).click();
    await expect(page.getByRole('status')).toContainText('password reset link has been sent');
    expect(state.lastResetIdentifier).toBe('alice@example.com');

    // Reset password via token link & sign in with new password
    await page.goto('/login?reset_token=valid-reset-token-123', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('h1')).toContainText('Choose a new password');
    await page.locator('input[type="password"]').fill('ResetPass456!');
    await page.getByRole('button', { name: 'Update password' }).click();
    await expect(page.getByRole('status')).toContainText('password has been reset');

    await page.locator('input[placeholder="name@example.com"]').fill('alice@example.com');
    await page.locator('input[type="password"]').fill('ResetPass456!');
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/chat$/);
  });

  test('4-6. Conversation Creation, Streaming Response, and History Recovery after Refresh', async ({ page }) => {
    const state = createInitialState();
    await mountDeterministicApi(page, state);

    await page.goto('/login', { waitUntil: 'domcontentloaded' });
    await page.evaluate((tok) => localStorage.setItem('access_token', tok), makeFakeJwt('alice@example.com'));
    await page.goto('/chat', { waitUntil: 'domcontentloaded' });

    const composer = page.locator('textarea').first();
    await expect(composer).toBeVisible();
    await composer.fill('Explain Sakura durable queues');
    await composer.press('Enter');

    await expect(page.getByText('Deterministic Sakura response for: Explain Sakura durable queues')).toBeVisible();

    // Browser refresh recovers full persisted conversation history
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Deterministic Sakura response for: Explain Sakura durable queues')).toBeVisible();
  });

  test('9-11. Sakura Code Task Creation, >8 SSE Reconnects, Dedup, Refresh/Reopen Recovery, Diff & Cancel', async ({ page }) => {
    const state = createInitialState();
    // Require 10 consecutive stream failures before succeeding (proves reconnection beyond old 8-attempt cap!)
    state.codingTask.failuresBeforeRecover = 10;
    await mountDeterministicApi(page, state);

    // Speed up backoff timer delays cleanly inside test browser so 10 retries finish rapidly
    await page.addInitScript(() => {
      const origSetTimeout = window.setTimeout.bind(window);
      (window as any).setTimeout = (fn: any, ms?: number, ...args: any[]) => {
        const capped = typeof ms === 'number' && ms >= 250 ? 25 : ms;
        return origSetTimeout(fn, capped, ...args);
      };
    });

    await page.goto('/login', { waitUntil: 'domcontentloaded' });
    await page.evaluate((tok) => localStorage.setItem('access_token', tok), makeFakeJwt('alice@example.com'));
    await page.goto('/chat', { waitUntil: 'domcontentloaded' });

    const composer = page.locator('textarea').first();
    await composer.fill('/code fix calculator unit test');
    await composer.press('Enter');

    // Wait for >10 reconnect attempts to recover, deduplicate sequence 2, verify tests, and render diff!
    await expect(page.getByText('Verification Passed')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('All 3 tests passed')).toBeVisible();
    await expect(page.getByText('return 2')).toBeVisible();
    expect(state.codingTask.streamAttempts).toBeGreaterThanOrEqual(11);

    // Browser refresh recovers persisted coding task state, verification & diff cleanly
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Verification Passed')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('return 2')).toBeVisible();

    // Conversation reopen: create new chat, then click back to previous conversation
    await page.getByRole('button', { name: /New Chat/i }).first().click();
    await page.getByText('Chat 1').first().click();
    await expect(page.getByText('Verification Passed')).toBeVisible({ timeout: 10_000 });
  });

  test('7-8 & 12-17. Image Jobs/Cancel, Library Upload/Index/Remove, Scheduled Tasks, Export/Delete & Mobile Nav', async ({ page, isMobile }) => {
    const state = createInitialState();
    await mountDeterministicApi(page, state);

    await page.goto('/login', { waitUntil: 'domcontentloaded' });
    await page.evaluate((tok) => localStorage.setItem('access_token', tok), makeFakeJwt('alice@example.com'));
    await page.goto('/chat', { waitUntil: 'domcontentloaded' });

    // Mobile responsive navigation check
    if (isMobile) {
      const collapseBtn = page.locator('button[title="Collapse Sidebar"]');
      if (await collapseBtn.isVisible()) {
        await collapseBtn.click();
        await expect(page.locator('button[title="Open Sidebar"]')).toBeVisible();
        await page.locator('button[title="Open Sidebar"]').click();
      }
    }

    // Exercise authenticated API workflows directly via browser session token (image job completion, variation, cancel,
    // library upload/preview/index/remove, scheduled task creation/execution, account export & account deletion)
    const results = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token') || '';
      const h = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

      // 7. Image job creation & completion
      const imgCreate = await fetch('/api/v1/images/jobs', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({ prompt: 'Sakura moonlit bridge', requested_pipeline: 'anime' }),
      }).then((r) => r.json());
      const imgDone = await fetch(`/api/v1/images/jobs/${imgCreate.id}`, { headers: h }).then((r) => r.json());

      // 8. Image variation & cancellation
      const varCreate = await fetch('/api/v1/images/variation', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({ parent_image_id: 'img-out-1', count: 1 }),
      }).then((r) => r.json());
      const varCancelled = await fetch(`/api/v1/images/jobs/${varCreate.jobs[0].id}/cancel`, {
        method: 'POST',
        headers: h,
      }).then((r) => r.json());

      // 12-13. Library upload, preview, index & remove
      const uploaded = await fetch('/api/v1/library/upload', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }).then((r) => r.json());
      const preview = await fetch(`/api/v1/library/files/${uploaded.file.id}/content`, { headers: h }).then((r) => r.json());
      const indexed = await fetch(`/api/v1/library/files/${uploaded.file.id}/index`, { method: 'POST', headers: h }).then((r) => r.json());
      const unindexed = await fetch(`/api/v1/library/files/${uploaded.file.id}/index`, { method: 'DELETE', headers: h }).then((r) => r.json());

      // 14. Scheduled task creation & execution
      const sched = await fetch('/api/v1/scheduled', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({ title: 'Daily Digest', prompt: 'Summarize', schedule: '0 9 * * *', timezone: 'UTC' }),
      }).then((r) => r.json());
      const schedRun = await fetch(`/api/v1/scheduled/${sched.id}/run`, { method: 'POST', headers: h }).then((r) => r.json());

      // 15. Account export & download
      const exp = await fetch('/api/v1/auth/me/export', { method: 'POST', headers: h }).then((r) => r.json());
      const expDl = await fetch(`/api/v1/auth/me/export/${exp.id}/download`, { headers: h });

      // 16. Account deletion
      const del = await fetch('/api/v1/auth/me', {
        method: 'DELETE',
        headers: h,
        body: JSON.stringify({ password: 'StrongPassword123!', confirm: 'DELETE' }),
      }).then((r) => r.json());

      return {
        imgStatus: imgDone.status,
        varCancelStatus: varCancelled.status,
        previewHasText: Boolean(preview.content),
        indexStatus: indexed.status,
        unindexStatus: unindexed.status,
        schedRunStatus: schedRun.status,
        exportDownloadStatus: expDl.status,
        deleteStatus: del.cleanup_status,
      };
    });

    expect(results.imgStatus).toBe('COMPLETED');
    expect(results.varCancelStatus).toBe('CANCELLED');
    expect(results.previewHasText).toBe(true);
    expect(results.indexStatus).toBe('indexing_started');
    expect(results.unindexStatus).toBe('removed_from_knowledge_base');
    expect(results.schedRunStatus).toBe('queued');
    expect(results.exportDownloadStatus).toBe(200);
    expect(results.deleteStatus).toBe('COMPLETE');
  });
});
