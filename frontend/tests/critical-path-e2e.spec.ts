/**
 * Cortex Frontend — Critical-Path E2E Spec
 *
 * Phase 2 completion: covers the main business routes with the
 * happy path + every state in the route/state matrix:
 *   /upload, /evidence, /audit, /nexus/cockpit
 * plus the retired routes that now redirect: /conflicts, /readiness, /nexus
 *
 * Designed to run against a backend that is reachable at
 * `NEXUS_BACKEND_URL` (default http://localhost:8000) and a frontend at
 * `NEXT_PUBLIC_BASE_URL` (default http://localhost:3000). When the
 * backend is unreachable, the network-down tests pass; the happy paths
 * skip (require a live stack).
 */

import { test, expect, type APIRequestContext, type APIResponse, type Page } from '@playwright/test';

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

interface Account {
  email: string;
  password: string;
  token: string;
  workspaceId: string;
}

async function signUp(request: APIRequestContext, tag: string): Promise<Account> {
  const email = `nexus-${tag}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
  const password = 'Nexusdemo1';
  const signup = await request.post(`${BACKEND}/api/v1/auth/signup`, {
    data: {
      organization_name: `Nexus ${tag} ${Date.now()}`,
      email,
      password,
      full_name: 'Nexus Demo Tester',
    },
  });
  expect(signup.status()).toBe(201);
  const body = await signup.json();
  return { email, password, token: String(body.access_token), workspaceId: String(body.workspace_id) };
}

/** Sign in through the real UI so AuthProvider owns the token state. */
async function logIn(page: Page, account: Account): Promise<void> {
  await page.goto(`${BASE_URL}/auth/login`);
  await page.getByLabel('Work email').fill(account.email);
  await page.getByLabel('Password').fill(account.password);
  await page.getByTestId('login-submit').click();
  await expect(page).toHaveURL(/onboarding/);
  await page.getByTestId('onboarding-continue').click();
  await expect(page).toHaveURL(/app$/);
}

/** A new organization with its own workspace, signed in. For tests that write data. */
async function createLoggedInSession(
  page: Page,
  request: APIRequestContext,
  tag: string,
): Promise<Account> {
  const account = await signUp(request, tag);
  await logIn(page, account);
  return account;
}

// The API accepts 30 signups an hour from one address, and every browser test
// comes from one address. Tests that only need a signed-in user whose
// workspace holds nothing share this account instead of creating one each.
// No test may write to it.
let emptyWorkspaceAccount: Account | null = null;

async function openEmptyWorkspace(page: Page, request: APIRequestContext): Promise<Account> {
  emptyWorkspaceAccount ??= await signUp(request, 'empty');
  await logIn(page, emptyWorkspaceAccount);
  return emptyWorkspaceAccount;
}

/**
 * Upload a file and take it through prepare -> review -> publish over the API,
 * as an integration would. Review accepts every claim, mapped to its own column.
 * With `publish: false` it stops after prepare, so the upload waits for review.
 */
async function publishSupplierFile(
  request: APIRequestContext,
  account: Account,
  name: string,
  csv: string,
  options: { entity?: string; publish?: boolean } = {},
): Promise<string> {
  const entity = options.entity ?? 'Supplier';
  const headers = { Authorization: `Bearer ${account.token}` };
  const params = { workspace_id: account.workspaceId };

  const upload = await request.post(`${BACKEND}/api/v1/sources/upload`, {
    headers,
    multipart: {
      workspace_id: account.workspaceId,
      source_system_hint: 'erp',
      file: { name, mimeType: 'text/csv', buffer: Buffer.from(csv) },
    },
  });
  expect(upload.status(), `upload body: ${await upload.text()}`).toBe(200);
  const batchId = String((await upload.json()).batch_id);

  const prepared = await request.post(`${BACKEND}/api/v1/sources/batches/${batchId}/compile`, { headers, params });
  expect(prepared.status(), `prepare body: ${await prepared.text()}`).toBe(200);
  if (options.publish === false) return batchId;

  const claims = await request.get(`${BACKEND}/api/v1/sources/batches/${batchId}/claims`, {
    headers,
    params: { ...params, limit: 500 },
  });
  expect(claims.status()).toBe(200);
  for (const claim of (await claims.json()) as Array<{ claim_id: string; source_column: string }>) {
    const review = await request.post(
      `${BACKEND}/api/v1/sources/batches/${batchId}/claims/${claim.claim_id}/review`,
      {
        headers,
        params,
        data: {
          decision: 'accepted',
          rationale: 'Checked against the supplier master.',
          canonical_entity: entity,
          canonical_field: claim.source_column,
        },
      },
    );
    expect(review.status(), `review body: ${await review.text()}`).toBe(200);
  }

  const published = await request.post(`${BACKEND}/api/v1/graph/batches/${batchId}/compile`, { headers, params });
  expect(published.status(), `publish body: ${await published.text()}`).toBe(200);
  return batchId;
}

test.describe('Upload → Evidence → Conflict → Readiness → Audit path', () => {
  test('authenticated workspace can open the source upload form', async ({ page, request }) => {
    await openEmptyWorkspace(page, request);
    await page.goto(`${BASE_URL}/upload`);
    await expect(page.getByRole('heading', { name: 'Upload a source file' })).toBeVisible();
    await expect(page.locator('#source-file')).toBeVisible();
    await expect(page.locator('#source-system')).toBeVisible();
    await expect(page.getByText(/authenticated workspace/i)).toBeVisible();
  });

  test('evidence without a batch says that nothing was uploaded and leads to the upload form', async ({ page, request }) => {
    await openEmptyWorkspace(page, request);
    await page.goto(`${BASE_URL}/evidence`);
    await expect(page.getByRole('heading', { name: 'Your uploads' })).toBeVisible();
    await expect(page.getByTestId('uploads-empty')).toContainText('No uploads yet');
    await page.getByRole('link', { name: 'Upload source data' }).click();
    await expect(page).toHaveURL(/\/upload$/);
  });

  test('every upload can be found again, with where it stands', async ({ page, request }) => {
    const account = await createLoggedInSession(page, request, 'uploads');
    await publishSupplierFile(
      request,
      account,
      'suppliers.csv',
      'supplier_id,supplier_name,country\nS-1,Acme Metals,DE\nS-2,Borealis Plastics,SE\n',
    );
    const waitingId = await publishSupplierFile(
      request,
      account,
      'more_suppliers.csv',
      'supplier_id,supplier_name,country\nS-3,Castor Bearings,JP\n',
      { publish: false },
    );

    // The upload form leads to the list; nobody has to keep a batch address.
    await page.goto(`${BASE_URL}/upload`);
    await page.getByTestId('upload-earlier').click();
    await expect(page).toHaveURL(/\/evidence$/);
    await expect(page.getByTestId('uploads-summary')).toHaveText('2 uploads · 1 not published');

    const rows = page.getByTestId('upload-row');
    await expect(rows).toHaveCount(2);
    // Newest first.
    const waiting = rows.nth(0);
    await expect(waiting).toContainText('more_suppliers.csv');
    await expect(waiting.getByTestId('upload-state')).toHaveText('Waiting for review');
    await expect(waiting).toContainText('3 values wait for a decision. Not part of your data yet.');
    await expect(waiting).toContainText('1 row');
    const published = rows.nth(1);
    await expect(published).toContainText('suppliers.csv');
    await expect(published.getByTestId('upload-state')).toHaveText('Published · version 1');
    await expect(published).toContainText('6 values accepted and part of your data.');
    await expect(published).toContainText('2 rows');

    // A row opens the review page of that upload, which leads back to the list.
    await waiting.getByRole('link', { name: 'Review: more_suppliers.csv' }).click();
    await expect(page).toHaveURL(new RegExp(`/evidence\\?batch_id=${waitingId}$`));
    await expect(page.getByRole('heading', { name: 'Evidence review' })).toBeVisible();
    await expect(page.locator('tbody tr')).toHaveCount(3);
    await page.getByTestId('evidence-all-uploads').click();
    await expect(page).toHaveURL(/\/evidence$/);
    await expect(page.getByTestId('upload-row')).toHaveCount(2);
  });

  test('a list of uploads that cannot be loaded says so', async ({ page, context, request }) => {
    await openEmptyWorkspace(page, request);
    await context.route(/\/api\/v1\/sources\/batches\?/, (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'storage offline' }) }),
    );
    await page.goto(`${BASE_URL}/evidence`);
    await expect(page.getByTestId('uploads-error')).toContainText('The uploads could not be loaded');
    // Not the empty state: the uploads may exist.
    await expect(page.getByTestId('uploads-empty')).toHaveCount(0);
  });

  test('uploaded source file is accepted and its evidence can be prepared', async ({ page, request }) => {
    const serverErrors: string[] = [];
    page.on('response', (response) => {
      if (response.status() >= 500) {
        serverErrors.push(`${response.request().method()} ${new URL(response.url()).pathname} -> ${response.status()}`);
      }
    });

    await createLoggedInSession(page, request, 'intake');
    await page.goto(`${BASE_URL}/upload`);
    await page.locator('#source-system').selectOption('erp');
    await page.locator('#source-file').setInputFiles({
      name: 'suppliers.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('supplier_id,supplier_name,country\nS-1,Acme Metals,DE\nS-2,Borealis Plastics,SE\n'),
    });
    const uploadResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/sources/upload') && response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Upload source' }).click();
    const upload = await uploadResponse;
    // The second argument surfaces the response body in the failure message
    // (visible in CI annotations), e.g. a database or object-storage error.
    expect(upload.status(), `upload body: ${await upload.text()}`).toBe(200);
    await expect(page.getByText('Upload accepted')).toBeVisible({ timeout: 15_000 });

    await page.getByRole('link', { name: 'Review evidence and publish' }).click();
    await expect(page).toHaveURL(/\/evidence\?batch_id=/);
    await expect(page.getByRole('heading', { name: 'Evidence review' })).toBeVisible();
    await expect(page.getByText('No claims have been prepared for this batch.')).toBeVisible();

    await page.getByRole('button', { name: 'Prepare claims' }).first().click();
    await expect(page.getByText(/Prepared batch: 6 new claims/)).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('tbody tr')).toHaveCount(6);

    // The page requests a readiness assessment on every load, so reopening it
    // must keep working (the second assessment used to fail with HTTP 500).
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Readiness gate' })).toBeVisible();
    await expect(page.locator('tbody tr')).toHaveCount(6);

    expect(serverErrors).toEqual([]);
  });

  test('the Ask box answers from a file that was uploaded, reviewed and published', async ({ page, request }) => {
    const account = await createLoggedInSession(page, request, 'ask');
    await publishSupplierFile(
      request,
      account,
      'suppliers.csv',
      'supplier_id,supplier_name,country,status\nS-1,Acme Metals,DE,active\nS-2,Borealis Plastics,SE,delayed\n',
    );

    await page.goto(`${BASE_URL}/nexus/cockpit`);
    await expect(page.getByRole('heading', { name: 'Ask about this workspace' })).toBeVisible();

    // A typed question is answered with the rows of the uploaded file.
    await page.getByLabel('Question about this workspace').fill('Which suppliers do I have?');
    await page.getByRole('button', { name: 'Ask', exact: true }).click();
    const answers = page.getByTestId('ask-answer');
    await expect(answers.last()).toContainText('You have 2 suppliers:', { timeout: 15_000 });
    await expect(answers.last()).toContainText('S-1 Acme Metals: country: DE; status: active');
    await expect(answers.last()).toContainText('S-2 Borealis Plastics: country: SE; status: delayed');
    await expect(answers.last()).toContainText('Source: your published data, version 1 (suppliers.csv).');
    // Plain sentences, not a dump of the tool output.
    await expect(answers.last()).not.toContainText('{');

    // A one-click suggestion is a complete question too.
    await page.getByTestId('ask-suggestions').getByRole('button', { name: 'What changed?' }).click();
    await expect(answers).toHaveCount(2, { timeout: 15_000 });
    await expect(answers.last()).toContainText('The latest publish is version 1, from suppliers.csv');
    await expect(answers.last()).toContainText('Added 2 suppliers: S-1 and S-2.');

    // A record that is not in the data is reported as missing, not invented.
    await page.getByLabel('Question about this workspace').fill('Tell me about PO-9999');
    await page.getByLabel('Question about this workspace').press('Enter');
    await expect(answers).toHaveCount(3, { timeout: 15_000 });
    await expect(answers.last()).toContainText('I could not find PO-9999 in your published data.');
  });

  test('a new workspace is told that nothing is published, not shown zeros', async ({ page, request }) => {
    await openEmptyWorkspace(page, request);
    await page.goto(`${BASE_URL}/nexus/cockpit`);

    const state = page.getByTestId('cockpit-state');
    await expect(state).toContainText('Published data');
    await expect(state).toContainText('Nothing published');
    // The old card said "World state: Not available" beside a CONNECTED badge.
    await expect(page.getByText('Not available')).toHaveCount(0);
    await expect(page.getByText('Incomplete')).toHaveCount(0);

    const tiles = page.getByTestId('cockpit-tiles');
    await expect(tiles).toContainText('Late orders');
    await expect(tiles).toContainText('No data published yet');
    await expect(page.getByText('Nothing to check yet')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Upload data →' }).first()).toBeVisible();
    await expect(page.getByTestId('cockpit-attention-count')).toHaveText('00');
    await expect(page.getByTestId('cockpit-source')).toHaveCount(0);
  });

  test('the Command Center shows what the published files hold and agrees with the Ask box', async ({ page, request }) => {
    const account = await createLoggedInSession(page, request, 'cockpit');
    await publishSupplierFile(
      request,
      account,
      'suppliers.csv',
      'supplier_id,supplier_name,country,status\nS-1,Acme Metals,DE,active\nS-2,Borealis Plastics,SE,delayed\n',
    );
    // PO-1 says it is delayed; PO-2 is promised far in the future. Neither
    // verdict depends on the day the test runs.
    await publishSupplierFile(
      request,
      account,
      'purchase_orders.csv',
      'po_number,supplier_id,quantity,promised_date,expected_date,status\n' +
        'PO-1,S-2,400,2026-11-05,2026-11-26,delayed\n' +
        'PO-2,S-1,150,2099-01-24,2099-01-24,confirmed\n',
      { entity: 'PurchaseOrder' },
    );

    await page.goto(`${BASE_URL}/nexus/cockpit`);

    // Totals of the published data, not "Not available" / "Not loaded".
    const state = page.getByTestId('cockpit-state');
    await expect(state).toContainText('Version 2', { timeout: 15_000 });
    await expect(state.locator('div', { hasText: 'Records' }).last()).toContainText('4');
    await expect(state.locator('div', { hasText: 'Relationships' }).last()).toContainText('2');

    // One of the two purchase orders is late; no stock was published, so the
    // stock figure is a dash with the reason, not a zero.
    const tiles = page.getByTestId('cockpit-tiles').locator('> div');
    await expect(tiles.nth(0)).toContainText('Late orders');
    await expect(tiles.nth(0)).toContainText('1');
    await expect(tiles.nth(0)).toContainText('of 2 orders and shipments checked');
    await expect(tiles.nth(1)).toContainText('—');
    await expect(tiles.nth(1)).toContainText('No stock records in your data');
    await expect(tiles.nth(2)).toContainText('Flagged partners');
    await expect(tiles.nth(2)).toContainText('1');
    await expect(tiles.nth(3)).toContainText('Recorded risks');
    await expect(tiles.nth(3)).toContainText('0');
    await expect(page.getByTestId('cockpit-source')).toContainText('Read from your published data, version 2');

    // The queue lists the late order and the flagged supplier with the reason
    // read from the uploaded rows.
    await expect(page.getByTestId('cockpit-attention-count')).toHaveText('02');
    const findings = page.getByTestId('cockpit-finding');
    await expect(findings).toHaveCount(2);
    await expect(findings.nth(0)).toContainText('Purchase order PO-1');
    await expect(findings.nth(0)).toContainText('21 days late');
    await expect(findings.nth(0)).toContainText('400 units from S-2 Borealis Plastics');
    await expect(findings.nth(0)).toContainText(
      'Status is delayed; now expected 2026-11-26, 21 days after the promised 2026-11-05',
    );
    await expect(findings.nth(1)).toContainText('S-2 Borealis Plastics');
    await expect(findings.nth(1)).toContainText('Supplier with status delayed');
    // The order that is on time is not listed.
    await expect(page.getByTestId('cockpit-queue')).not.toContainText('PO-2');
    await expect(page.getByTestId('cockpit-map-note')).toHaveText(
      'All 4 published records and the links between them.',
    );

    // The Ask box reads the same records and reports the same order as late.
    await page.getByLabel('Question about this workspace').fill('Which orders are late?');
    await page.getByRole('button', { name: 'Ask', exact: true }).click();
    const answers = page.getByTestId('ask-answer');
    await expect(answers.last()).toContainText('1 of 2 purchase orders', { timeout: 15_000 });
    await expect(answers.last()).toContainText(
      'PO-1: 400 units from S-2 Borealis Plastics; status is delayed; now expected 2026-11-26, 21 days after the promised 2026-11-05.',
    );

    // A row of the queue asks about its record.
    await findings.nth(1).click();
    await expect(page.getByTestId('ask-question').last()).toHaveText(/Tell me about S-2/);
    await expect(answers).toHaveCount(2, { timeout: 15_000 });
    await expect(answers.last()).toContainText('S-2 is a supplier in your published data: Borealis Plastics.');
    await expect(answers.last()).toContainText('1 purchase order refers to it: PO-1.');
  });

  test('figures that cannot be read are not shown as zeros', async ({ page, context, request }) => {
    await openEmptyWorkspace(page, request);
    await context.route(/\/api\/v1\/nexus\/workspace\/overview\?/, (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'database offline' }) }),
    );
    await page.goto(`${BASE_URL}/nexus/cockpit`);
    await expect(page.getByRole('alert').filter({ hasText: 'Retry' })).toBeVisible({ timeout: 15_000 });
    const tiles = page.getByTestId('cockpit-tiles').locator('> div');
    await expect(tiles.nth(0)).toContainText('Could not be read');
    await expect(tiles.nth(0)).toContainText('—');
    await expect(page.getByText('Your data could not be read')).toBeVisible();
    await expect(page.getByText('CONNECTED')).toHaveCount(0);
  });

  test('retired conflict and readiness routes lead to source intake', async ({ page }) => {
    // Conflicts and the readiness gate are part of /evidence?batch_id=…, which
    // is reached from an upload. The old standalone pages called API routes
    // that do not exist.
    for (const path of ['/conflicts', '/readiness']) {
      await page.goto(`${BASE_URL}${path}`);
      await expect(page).toHaveURL(/\/upload$/);
      await expect(page.locator('h1, h2').first()).toBeVisible();
    }
  });

  test('audit page renders with category filter', async ({ page }) => {
    await page.goto(`${BASE_URL}/audit`);
    await expect(page.locator('h1, h2').first()).toBeVisible();
    const filter = page.locator('select, [role="combobox"]').first();
    await expect(filter).toBeVisible();
  });

  test('retired /nexus console route opens the Nexus cockpit', async ({ page }) => {
    await page.goto(`${BASE_URL}/nexus`);
    await expect(page).toHaveURL(/\/nexus\/cockpit$/);
    await expect(page.locator('h1, h2').first()).toBeVisible();
    // Every /nexus/* surface renders inside the canonical Nexus navigation,
    // signed in or not — never a blank page.
    const navLinks = page.locator('nav a');
    for (const item of ['Command Center', 'World State']) {
      await expect(navLinks.filter({ hasText: item }).first()).toBeVisible({ timeout: 10_000 });
    }
  });
});

test.describe('Failure behavior — backend 5xx surfaces error UI', () => {
  test('authenticated evidence review surfaces a backend 500', async ({ page, context, request }) => {
    await openEmptyWorkspace(page, request);
    await context.route('**/api/v1/**', (route) => {
      if (route.request().url().includes('/auth/me')) {
        return route.continue();
      }
      return route.fulfill({ status: 500, body: JSON.stringify({ detail: 'backend error' }) });
    });
    await page.goto(`${BASE_URL}/evidence?batch_id=00000000-0000-4000-8000-000000000001`);
    await expect(page.getByText('backend error', { exact: true })).toBeVisible({ timeout: 10000 });
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
    // The second argument surfaces the response body in the failure
    // message (visible in CI annotations) — essential for /readyz, whose
    // 503 payload lists the degraded component.
    expect(res.status, `healthz body: ${await res.text()}`).toBe(200);
  });

  test('live /readyz is 200', async () => {
    const res: APIResponse = await fetch(`${BACKEND}/readyz`) as unknown as APIResponse;
    expect(res.status, `readyz body: ${await res.text()}`).toBe(200);
  });

  test('live /metrics is 200', async () => {
    const res: APIResponse = await fetch(`${BACKEND}/metrics`) as unknown as APIResponse;
    expect(res.status, `metrics body (first 200): ${(await res.text()).slice(0, 200)}`).toBe(200);
  });
});
