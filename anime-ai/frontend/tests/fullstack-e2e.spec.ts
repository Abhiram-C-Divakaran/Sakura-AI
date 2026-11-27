import { test, expect } from '@playwright/test';

/**
 * Sakura AI — Real Unmocked Full-Stack Browser Integration Suite
 *
 * ZERO page.route() API mocks.
 * Every browser interaction and fetch runs end-to-end against:
 *   Browser (Chromium) -> Next.js frontend -> Real FastAPI backend -> Real DB + Durable Workers
 *   (tasks.worker, media.image_worker, coding.job_worker)
 *
 * External LLM and external Pollinations HTTP calls are replaced strictly by
 * backend guarded test providers (ENVIRONMENT=test + SAKURA_DETERMINISTIC_TEST_PROVIDERS=1).
 */

async function pollUntil<T>(
  fn: () => Promise<T>,
  predicate: (val: T) => boolean,
  timeoutMs = 25_000,
  intervalMs = 400
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let lastVal: T;
  while (true) {
    lastVal = await fn();
    if (predicate(lastVal)) return lastVal;
    if (Date.now() >= deadline) {
      throw new Error(`pollUntil timed out after ${timeoutMs}ms; last value: ${JSON.stringify(lastVal)}`);
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

test.describe('Sakura AI Real Full-Stack Integration Suite (Zero API Mocks)', () => {
  test('Full-stack real auth, chat persistence, workers, quotas, coding SSE, library, scheduled tasks, export & deletion', async ({
    page,
    isMobile,
  }, testInfo) => {
    const suffix = `${testInfo.project.name.replace(/[^a-z0-9]/gi, '')}_${Date.now()}_${Math.floor(Math.random() * 10000)}`;
    const email = `fullstack_${suffix}@example.com`;
    const password = 'StrongFullStackPass123!';

    // 1. User registration and authentication via REAL /login page -> POST /api/v1/auth/register + /auth/token
    await page.goto('/login', { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Sign up' }).click();
    await expect(page.locator('h1')).toContainText('Create your account');
    await page.locator('input[placeholder="name@example.com"]').fill(email);
    await page.locator('input[type="password"]').fill(password);
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page).toHaveURL(/\/chat$/, { timeout: 15_000 });

    const token = await page.evaluate(() => localStorage.getItem('access_token') || '');
    expect(token.length).toBeGreaterThan(20);

    // 2 & 3. Real conversation creation + real chat streaming & persisted assistant response
    const composer = page.locator('textarea').first();
    await expect(composer).toBeVisible();
    const chatPrompt = `Fullstack persistence probe ${suffix}`;
    await composer.fill(chatPrompt);
    await composer.press('Enter');

    await expect(page.getByText(`Sakura integration response: ${chatPrompt}`)).toBeVisible({ timeout: 20_000 });

    // 4. Refresh & persisted conversation history recovery from real DB
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByText(`Sakura integration response: ${chatPrompt}`)).toBeVisible({ timeout: 15_000 });

    // Responsive mobile sidebar sanity check on real app
    if (isMobile) {
      const collapseBtn = page.locator('button[title="Collapse Sidebar"]');
      if (await collapseBtn.isVisible()) {
        await collapseBtn.click();
        await expect(page.locator('button[title="Open Sidebar"]')).toBeVisible();
        await page.locator('button[title="Open Sidebar"]').click();
      }
    }

    // 5 & 6. Real durable ImageGenerationJob -> real ImageJobWorker -> COMPLETED + PNG download
    //        + Batch variation idempotency + real DB Image Quota enforcement (SAKURA_QUOTA_IMAGE_DAILY=3)
    const imgCreateRes = await page.evaluate(async () => {
      const tok = localStorage.getItem('access_token') || '';
      const r = await fetch('/api/v1/images/generate', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: 'Sakura moonlit bridge fullstack test',
          requested_pipeline: 'anime',
          idempotency_key: 'fs-img-1',
        }),
      });
      return { status: r.status, body: await r.json() };
    });
    expect(imgCreateRes.status).toBe(202);
    const imgJobId = imgCreateRes.body.job_id;
    expect(imgJobId).toBeTruthy();

    const completedImgJob = await pollUntil(
      async () =>
        page.evaluate(async (jid) => {
          const tok = localStorage.getItem('access_token') || '';
          const r = await fetch(`/api/v1/images/jobs/${jid}`, {
            headers: { Authorization: `Bearer ${tok}` },
          });
          return r.json();
        }, imgJobId),
      (j) => j.status === 'COMPLETED' || j.status === 'FAILED',
      30_000,
      400
    );
    expect(completedImgJob.status).toBe('COMPLETED');
    expect(completedImgJob.actual_provider).toBe('deterministic_test');
    expect(completedImgJob.output_image_id).toBeTruthy();

    // Verify generated PNG is downloadable from real storage with valid PNG header
    const pngCheck = await page.evaluate(async (outId) => {
      const tok = localStorage.getItem('access_token') || '';
      const r = await fetch(`/api/v1/library/files/${outId}/download`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      const buf = new Uint8Array(await r.arrayBuffer());
      return {
        status: r.status,
        size: buf.length,
        isPng: buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47,
      };
    }, completedImgJob.output_image_id);
    expect(pngCheck.status).toBe(200);
    expect(pngCheck.size).toBeGreaterThanOrEqual(8192);
    expect(pngCheck.isPng).toBe(true);

    // Variation batch idempotency (uses 2 quota slots -> total 3 of 3) + replay (0 extra slots)
    // + missing idempotency key (400) + same-key mismatched count (409) + quota 429 on 4th
    const varBatchRes = await page.evaluate(async (parentId) => {
      const tok = localStorage.getItem('access_token') || '';
      const h = { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' };

      const missingKey = await fetch('/api/v1/images/variation', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({ parent_image_id: parentId, count: 2 }),
      });

      const first = await fetch('/api/v1/images/variation', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({ parent_image_id: parentId, count: 2, idempotency_key: 'fs-var-batch-1' }),
      });
      const firstBody = await first.json();

      const replay = await fetch('/api/v1/images/variation', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({ parent_image_id: parentId, count: 2, idempotency_key: 'fs-var-batch-1' }),
      });
      const replayBody = await replay.json();

      const conflict = await fetch('/api/v1/images/variation', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({ parent_image_id: parentId, count: 3, idempotency_key: 'fs-var-batch-1' }),
      });

      // Quota is configured to 3/day in fullstack integration; next image must return HTTP 429
      const overQuota = await fetch('/api/v1/images/generate', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({ prompt: 'Over quota test image', idempotency_key: 'fs-img-over-quota' }),
      });

      return {
        missingKeyStatus: missingKey.status,
        firstStatus: first.status,
        firstIds: (firstBody.jobs || []).map((j: any) => j.id),
        firstReplay: firstBody.idempotent_replay,
        replayStatus: replay.status,
        replayIds: (replayBody.jobs || []).map((j: any) => j.id),
        replayFlag: replayBody.idempotent_replay,
        conflictStatus: conflict.status,
        overQuotaStatus: overQuota.status,
      };
    }, completedImgJob.output_image_id);

    expect(varBatchRes.missingKeyStatus).toBe(400);
    expect(varBatchRes.firstStatus).toBe(202);
    expect(varBatchRes.firstIds).toHaveLength(2);
    expect(varBatchRes.firstReplay).toBe(false);
    expect(varBatchRes.replayStatus).toBe(202);
    expect(varBatchRes.replayIds).toEqual(varBatchRes.firstIds);
    expect(varBatchRes.replayFlag).toBe(true);
    expect(varBatchRes.conflictStatus).toBe(409);
    expect(varBatchRes.overQuotaStatus).toBe(429);

    // 7 & 8. Real Library upload -> real storage preview -> KB indexing (real DurableTaskWorker) -> KB removal
    const uploadRes = await page.evaluate(async () => {
      const tok = localStorage.getItem('access_token') || '';
      const form = new FormData();
      const blob = new Blob(['# Sakura Fullstack KB Doc\nDurable worker indexing verified.\n'], {
        type: 'text/markdown',
      });
      form.append('file', blob, 'fullstack_notes.md');
      const r = await fetch('/api/v1/library/upload?auto_index=false', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok}` },
        body: form,
      });
      return { status: r.status, body: await r.json() };
    });
    expect(uploadRes.status).toBe(200);
    const fileId = uploadRes.body.file.id;
    expect(fileId).toBeTruthy();

    const previewRes = await page.evaluate(async (fid) => {
      const tok = localStorage.getItem('access_token') || '';
      const r = await fetch(`/api/v1/library/files/${fid}/content`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      return { status: r.status, body: await r.json() };
    }, fileId);
    expect(previewRes.status).toBe(200);
    expect(previewRes.body.content).toContain('Durable worker indexing verified.');

    // Trigger real durable KB indexing & wait for real DurableTaskWorker to complete it
    const indexTrigger = await page.evaluate(async (fid) => {
      const tok = localStorage.getItem('access_token') || '';
      const r = await fetch(`/api/v1/library/files/${fid}/index`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok}` },
      });
      return r.status;
    }, fileId);
    expect(indexTrigger).toBe(200);

    const indexedDoc = await pollUntil(
      async () =>
        page.evaluate(async (fid) => {
          const tok = localStorage.getItem('access_token') || '';
          const r = await fetch(`/api/v1/library/files/${fid}`, {
            headers: { Authorization: `Bearer ${tok}` },
          });
          return r.json();
        }, fileId),
      (d) => d.is_knowledge_base === true || d.indexing_status === 'FAILED',
      30_000,
      400
    );
    expect(indexedDoc.is_knowledge_base).toBe(true);
    expect(indexedDoc.indexing_status).toBe('READY');

    // Remove from KB and verify persisted removal
    const unindexRes = await page.evaluate(async (fid) => {
      const tok = localStorage.getItem('access_token') || '';
      const r = await fetch(`/api/v1/library/files/${fid}/index`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${tok}` },
      });
      return { status: r.status, body: await r.json() };
    }, fileId);
    expect(unindexRes.status).toBe(200);
    expect(unindexRes.body.file.is_knowledge_base).toBe(false);

    // 9. Real Scheduled Task creation & real execution via DurableTaskWorker
    const schedCreate = await page.evaluate(async () => {
      const tok = localStorage.getItem('access_token') || '';
      const h = { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' };
      const r = await fetch('/api/v1/scheduled', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({
          title: 'Fullstack Digest',
          prompt: 'Summarize fullstack verification',
          schedule: '0 9 * * *',
          timezone: 'UTC',
        }),
      });
      const body = await r.json();
      const runR = await fetch(`/api/v1/scheduled/${body.id}/run`, {
        method: 'POST',
        headers: h,
      });
      return { createStatus: r.status, taskId: body.id, runStatus: runR.status };
    });
    expect(schedCreate.createStatus).toBe(200);
    expect(schedCreate.runStatus).toBe(202);

    const schedRuns = await pollUntil(
      async () =>
        page.evaluate(async (tid) => {
          const tok = localStorage.getItem('access_token') || '';
          const r = await fetch(`/api/v1/scheduled/${tid}/runs`, {
            headers: { Authorization: `Bearer ${tok}` },
          });
          return r.json();
        }, schedCreate.taskId),
      (runs: any[]) => Array.isArray(runs) && runs.length > 0 && ['COMPLETED', 'FAILED'].includes(runs[0].status),
      30_000,
      400
    );
    expect(schedRuns[0].status).toBe('COMPLETED');
    expect(schedRuns[0].output).toContain('Sakura integration response');

    // 10. Real Sakura Code workspace creation + durable coding job via /code -> real CodingJobWorker
    //     + persisted CodingTaskEvent replay + browser reload recovery
    const wsCreate = await page.evaluate(async () => {
      const tok = localStorage.getItem('access_token') || '';
      const r = await fetch('/api/v1/coding/workspaces', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'fullstack-repo', branch: 'main', clone_existing: false }),
      });
      return { status: r.status, body: await r.json() };
    });
    expect(wsCreate.status).toBe(200);
    const workspaceId = wsCreate.body.workspace.id;
    expect(workspaceId).toBeTruthy();

    // Enqueue a real durable coding task through the real /coding/workspaces/{id}/tasks endpoint
    // and verify real CodingJobWorker executes tools, persists events, and finishes cleanly.
    const codingTaskCreate = await page.evaluate(async (wsId) => {
      const tok = localStorage.getItem('access_token') || '';
      const r = await fetch(`/api/v1/coding/workspaces/${wsId}/tasks`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: 'Create deterministic check module',
          objective: 'Create sakura_fullstack_check.py and verify it',
          intensity: 'medium',
        }),
      });
      return { status: r.status, body: await r.json() };
    }, workspaceId);
    expect([200, 202]).toContain(codingTaskCreate.status);
    const codingTaskId = codingTaskCreate.body.task_id || codingTaskCreate.body.taskId || codingTaskCreate.body.id;
    expect(codingTaskId).toBeTruthy();

    const codingTaskFinal = await pollUntil(
      async () =>
        page.evaluate(async (tid) => {
          const tok = localStorage.getItem('access_token') || '';
          const r = await fetch(`/api/v1/coding/tasks/${tid}`, {
            headers: { Authorization: `Bearer ${tok}` },
          });
          return r.json();
        }, codingTaskId),
      (t) =>
        ['COMPLETED_VERIFIED', 'COMPLETED_UNVERIFIED', 'FAILED', 'CANCELLED'].includes(
          String(t.status || '').toUpperCase()
        ),
      35_000,
      500
    );
    expect(String(codingTaskFinal.status || '').toUpperCase()).toBe('COMPLETED_VERIFIED');

    const codingEvents = await page.evaluate(async (tid) => {
      const tok = localStorage.getItem('access_token') || '';
      const r = await fetch(`/api/v1/coding/tasks/${tid}/events`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      return r.json();
    }, codingTaskId);
    expect(Array.isArray(codingEvents)).toBe(true);
    expect(codingEvents.length).toBeGreaterThanOrEqual(8);
    const seqs = codingEvents.map((e: any) => e.sequenceNumber);
    expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
    expect(new Set(seqs).size).toBe(seqs.length);
    const combinedOutput = codingEvents.map((e: any) => `${e.stdoutPreview || ''} ${e.message || ''}`).join('\n');
    expect(combinedOutput).toContain('SAKURA_REMOTE_DOCKER_TESTS_PASSED');

    // Also test real /code message persistence & UI panel render in /chat
    await composer.fill('/code create deterministic check module');
    await composer.press('Enter');
    await expect(page.getByText(/Coding Task|fullstack-repo|QUEUED|COMPLETED/i).first()).toBeVisible({
      timeout: 20_000,
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByText('/code create deterministic check module')).toBeVisible({ timeout: 15_000 });

    // 11. Real async Account Export -> real DurableTaskWorker builds ZIP -> valid ZIP download
    const exportStart = await page.evaluate(async () => {
      const tok = localStorage.getItem('access_token') || '';
      const r = await fetch('/api/v1/auth/me/export', {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok}` },
      });
      return { status: r.status, body: await r.json() };
    });
    expect(exportStart.status).toBe(202);
    const exportId = exportStart.body.export_id || exportStart.body.id;

    const exportDone = await pollUntil(
      async () =>
        page.evaluate(async (eid) => {
          const tok = localStorage.getItem('access_token') || '';
          const r = await fetch(`/api/v1/auth/me/export/${eid}`, {
            headers: { Authorization: `Bearer ${tok}` },
          });
          return r.json();
        }, exportId),
      (e) => e.status === 'COMPLETED' || e.status === 'FAILED',
      30_000,
      400
    );
    expect(exportDone.status).toBe('COMPLETED');

    const zipCheck = await page.evaluate(async (eid) => {
      const tok = localStorage.getItem('access_token') || '';
      const r = await fetch(`/api/v1/auth/me/export/${eid}/download`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      const buf = new Uint8Array(await r.arrayBuffer());
      return {
        status: r.status,
        size: buf.length,
        isZip: buf[0] === 0x50 && buf[1] === 0x4b,
      };
    }, exportId);
    expect(zipCheck.status).toBe(200);
    expect(zipCheck.size).toBeGreaterThan(50);
    expect(zipCheck.isZip).toBe(true);

    // 11b. Cross-user authorization boundary + WebSocket ticket issuance + user-scoped document deletion
    const securityChecks = await page.evaluate(
      async ({ targetFileId, targetImgJobId, targetCodingTaskId, runSuffix }) => {
        const tok1 = localStorage.getItem('access_token') || '';
        const h1 = { Authorization: `Bearer ${tok1}`, 'Content-Type': 'application/json' };

        // Issue single-use WS ticket for user 1
        const wsTicketRes = await fetch('/api/v1/auth/ws-ticket', { method: 'POST', headers: h1 });
        const wsTicketBody = await wsTicketRes.json();

        // Register a second isolated user and verify strict 404 boundaries on user 1's resources
        const u2Email = `other_${runSuffix}@example.com`;
        const u2Pass = 'OtherStrongPass123!';
        await fetch('/api/v1/auth/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: u2Email, password: u2Pass }),
        });
        const u2TokRes = await fetch('/api/v1/auth/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ username: u2Email, password: u2Pass }).toString(),
        });
        const u2Tok = (await u2TokRes.json()).access_token;
        const h2 = { Authorization: `Bearer ${u2Tok}` };

        const xFile = await fetch(`/api/v1/library/files/${targetFileId}`, { headers: h2 });
        const xImgJob = await fetch(`/api/v1/images/jobs/${targetImgJobId}`, { headers: h2 });
        const xCoding = await fetch(`/api/v1/coding/tasks/${targetCodingTaskId}`, { headers: h2 });

        // User 1 requests async deletion of their uploaded library file (HTTP 202 DELETING)
        const delFile = await fetch(`/api/v1/library/files/${targetFileId}`, { method: 'DELETE', headers: h1 });
        const delFileBody = await delFile.json();

        return {
          wsTicketStatus: wsTicketRes.status,
          hasTicket: Boolean(wsTicketBody.ticket),
          xFileStatus: xFile.status,
          xImgJobStatus: xImgJob.status,
          xCodingStatus: xCoding.status,
          delFileStatus: delFile.status,
          delFileDeletionStatus: delFileBody.deletion_status,
        };
      },
      {
        targetFileId: fileId,
        targetImgJobId: imgJobId,
        targetCodingTaskId: codingTaskId,
        runSuffix: suffix,
      }
    );

    expect(securityChecks.wsTicketStatus).toBe(200);
    expect(securityChecks.hasTicket).toBe(true);
    expect(securityChecks.xFileStatus).toBe(404);
    expect(securityChecks.xImgJobStatus).toBe(404);
    expect(securityChecks.xCodingStatus).toBe(404);
    expect(securityChecks.delFileStatus).toBe(202);
    expect(securityChecks.delFileDeletionStatus).toBe('DELETING');

    // Verify real DurableTaskWorker processes StorageDeletionOutbox and removes the file (404 afterwards)
    const afterDelStatus = await pollUntil(
      async () =>
        page.evaluate(async (fid) => {
          const tok = localStorage.getItem('access_token') || '';
          const r = await fetch(`/api/v1/library/files/${fid}`, {
            headers: { Authorization: `Bearer ${tok}` },
          });
          return r.status;
        }, fileId),
      (status) => status === 404,
      20_000,
      300
    );
    expect(afterDelStatus).toBe(404);

    // 12. Real Account Deletion -> cleanup status verified & credentials permanently invalidated
    const deleteRes = await page.evaluate(
      async ({ pwd, userEmail }) => {
        const tok = localStorage.getItem('access_token') || '';
        const r = await fetch('/api/v1/auth/me', {
          method: 'DELETE',
          headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: pwd, confirm: 'DELETE' }),
        });
        const delBody = await r.json();

        const loginRetry = await fetch('/api/v1/auth/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ username: userEmail, password: pwd }).toString(),
        });
        return {
          deleteStatus: r.status,
          cleanupStatus: delBody.cleanup_status,
          loginRetryStatus: loginRetry.status,
        };
      },
      { pwd: password, userEmail: email }
    );

    expect(deleteRes.deleteStatus).toBe(200);
    expect(['COMPLETE', 'PENDING_ASYNC_CLEANUP']).toContain(deleteRes.cleanupStatus);
    expect(deleteRes.loginRetryStatus).toBe(400);
  });
});
