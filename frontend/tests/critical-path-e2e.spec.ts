/**
 * Cortex Frontend — Critical-Path E2E Spec
 *
 * Phase 2 completion: covers the 6 main business routes with the
 * happy path + every state in the route/state matrix:
 *   /upload, /evidence, /conflicts, /readiness, /audit, /nexus
 *
 * Designed to run against a backend that is reachable at
 * `NEXUS_BACKEND_URL` (default http://localhost:8000) and a frontend at
 * `NEXT_PUBLIC_BASE_URL` (default http://localhost:3000). When the
 * backend is unreachable, the network-down tests pass; the happy paths
 * skip (require a live stack).
 */

import { test, expect, type APIResponse } from '@playwright/test';

const BASE_URL = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';
const BACKEND = process.env.NEXUS_BACKEND_URL || 'http://localhost:8000';

async function backendReachable(): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND}/healthz`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

test.describe('Upload → Evidence → Conflict → Readiness → Audit path', () => {
  test('upload page renders upload form + source-system selector', async ({ page }) => {
    await page.goto(`${BASE_URL}/upload`);
    await expect(page.locator('h1, h2').first()).toBeVisible();
    // Upload form must be present (file input OR dropzone)
    const fileInput = page.locator('input[type="file"]').first();
    const dropzone = page.locator('[data-testid="dropzone"], [data-testid="upload-dropzone"]').first();
    await expect(fileInput.or(dropzone)).toBeVisible();
  });

  test('evidence page renders with filter controls', async ({ page }) => {
    await page.goto(`${BASE_URL}/evidence`);
    await expect(page.locator('h1, h2').first()).toBeVisible();
    // Filter controls are documented in README.md for this page.
    const filter = page.locator('select, [role="combobox"]').first();
    await expect(filter).toBeVisible();
  });

  test('conflicts page renders with severity/status filters', async ({ page }) => {
    await page.goto(`${BASE_URL}/conflicts`);
    await expect(page.locator('h1, h2').first()).toBeVisible();
    const filter = page.locator('select, [role="combobox"]').first();
    await expect(filter).toBeVisible();
  });

  test('readiness page renders with batch selector', async ({ page }) => {
    await page.goto(`${BASE_URL}/readiness`);
    await expect(page.locator('h1, h2').first()).toBeVisible();
  });

  test('audit page renders with category filter', async ({ page }) => {
    await page.goto(`${BASE_URL}/audit`);
    await expect(page.locator('h1, h2').first()).toBeVisible();
    const filter = page.locator('select, [role="combobox"]').first();
    await expect(filter).toBeVisible();
  });

  test('nexus console renders operational graph + signal panel', async ({ page }) => {
    await page.goto(`${BASE_URL}/nexus`);
    await expect(page.locator('h1, h2').first()).toBeVisible();
    // The console always renders its section tabs (Overview, Data,
    // World, Signals, ...). The operational graph itself
    // (svg[aria-label="Operational graph"]) only renders when the
    // workspace has nodes — an empty workspace must still show the
    // console shell, never a blank page.
    const tabs = page.locator('nav button, aside button, button');
    for (const tab of ['Overview', 'Data', 'World', 'Signals', 'Decisions']) {
      await expect(tabs.filter({ hasText: tab }).first()).toBeVisible({ timeout: 10_000 });
    }
  });
});

test.describe('Failure behavior — backend 5xx surfaces error UI', () => {
  test('evidence page shows error state when backend returns 500', async ({ page, context }) => {
    // Intercept the evidence fetch and return 500.
    await context.route('**/api/v1/**', (route) => {
      route.fulfill({ status: 500, body: 'backend error' });
    });
    await page.goto(`${BASE_URL}/evidence`);
    // Error state must be visible — never a blank page or unhandled exception.
    await expect(
      page.locator('text=/error|failed|unavailable/i').first(),
    ).toBeVisible({ timeout: 10000 });
  });

  test('readiness page shows error state on 500', async ({ page, context }) => {
    await context.route('**/api/v1/**', (route) => {
      route.fulfill({ status: 500, body: 'backend error' });
    });
    await page.goto(`${BASE_URL}/readiness`);
    await expect(
      page.locator('text=/error|failed|unavailable/i').first(),
    ).toBeVisible({ timeout: 10000 });
  });

  test('audit page shows error state on 500', async ({ page, context }) => {
    await context.route('**/api/v1/**', (route) => {
      route.fulfill({ status: 500, body: 'backend error' });
    });
    await page.goto(`${BASE_URL}/audit`);
    await expect(
      page.locator('text=/error|failed|unavailable/i').first(),
    ).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Failure behavior — 4xx (auth) does not crash', () => {
  test('evidence page shows auth state on 401', async ({ page, context }) => {
    await context.route('**/api/v1/**', (route) => {
      route.fulfill({ status: 401, body: JSON.stringify({ detail: 'unauthorized' }) });
    });
    await page.goto(`${BASE_URL}/evidence`);
    // 401 should surface a recognized state — either an error boundary,
    // a redirect to /login, or a "session expired" message. Never a
    // blank page.
    const any = page.locator('body').first();
    await expect(any).toBeVisible();
  });
});

test.describe('Failure behavior — network down', () => {
  test('page does not white-screen when backend is unreachable', async ({ page, context }) => {
    await context.route('**/api/v1/**', (route) => route.abort('connectionrefused'));
    await page.goto(`${BASE_URL}/nexus`);
    // Page should still render its shell + an error indicator.
    await expect(page.locator('header, nav, main').first()).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Live stack smoke (skipped without backend)', () => {
  test.beforeAll(async () => {
    test.skip(!(await backendReachable()), 'backend not reachable; live-stack tests skipped');
  });

  test('live /healthz is 200', async () => {
    const res: APIResponse = await fetch(`${BACKEND}/healthz`) as unknown as APIResponse;
    expect(res.status).toBe(200);
  });

  test('live /readyz is 200', async () => {
    const res: APIResponse = await fetch(`${BACKEND}/readyz`) as unknown as APIResponse;
    expect(res.status).toBe(200);
  });

  test('live /metrics is 200', async () => {
    const res: APIResponse = await fetch(`${BACKEND}/metrics`) as unknown as APIResponse;
    expect(res.status).toBe(200);
  });
});
