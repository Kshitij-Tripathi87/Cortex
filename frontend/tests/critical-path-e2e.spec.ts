/**
 * Cortex Frontend — Critical-Path E2E Spec
 *
 * Phase 2 completion: covers the main business routes with the
 * happy path + every state in the route/state matrix:
 *   /upload, /evidence, /nexus/cockpit, /nexus/operations
 * plus the retired routes that now redirect: /conflicts, /readiness, /nexus,
 * /audit
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

const PHONE = { width: 390, height: 844 };

/** The page must not be wider than the screen (nothing to scroll sideways). */
async function expectNoSidewaysScroll(page: Page, what: string): Promise<void> {
  const widths = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth,
    screen: document.documentElement.clientWidth,
  }));
  expect(widths.page, `${what} is ${widths.page}px wide on a ${widths.screen}px screen`).toBeLessThanOrEqual(
    widths.screen,
  );
}

/**
 * Make every letter take more room, as a wider font would.
 *
 * Fonts differ between machines. /nexus/operations fitted a 390px screen
 * exactly on one machine and was 416px wide on another, because one long
 * word that could not wrap was a little wider there. A layout that only fits
 * with one font is not a layout that fits, so the phone tests measure each
 * page twice: as rendered, and with the text made wider than any font here.
 */
async function widenText(page: Page): Promise<void> {
  await page.addStyleTag({ content: '* { letter-spacing: 0.1em !important; }' });
}

/** The page fits the screen as rendered and with wider text. */
async function expectFitsTheScreen(page: Page, what: string): Promise<void> {
  await expectNoSidewaysScroll(page, what);
  await widenText(page);
  await expectNoSidewaysScroll(page, `${what} with wider text`);
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
//
// The five specs the E2E job runs together make 26 signups (8 here, 16 in
// auth-e2e, 2 in realtime-e2e). A new test that needs its own workspace costs
// one more; past 30 the API answers 429 and unrelated tests fail.
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

/**
 * Record a decision over the API, as an integration would, and take it to the
 * point where a person has to approve it. Returns its identifier.
 */
async function recordDecisionAwaitingApproval(request: APIRequestContext, account: Account): Promise<string> {
  const headers = { Authorization: `Bearer ${account.token}` };
  const created = await request.post(`${BACKEND}/api/v1/nexus/decisions`, {
    headers,
    data: {
      workspace_id: account.workspaceId,
      situation: 'Cast iron housings from S-101 are three weeks late.',
      options: [
        { option_id: 'opt-a', label: 'Expedite PO-5001 by air', expected_cost: 18400 },
        { option_id: 'opt-b', label: 'Move 250 units to Acme Metals', expected_cost: 9200, lead_time_days: 12 },
      ],
      recommended_option_id: 'opt-b',
      world_state_version: 0,
    },
  });
  expect(created.status(), `decision body: ${await created.text()}`).toBe(201);
  const decisionId = String((await created.json()).data.decision.decision_id);
  for (const phase of ['simulated', 'policy_checked', 'awaiting_approval']) {
    const advanced = await request.post(`${BACKEND}/api/v1/nexus/decisions/${decisionId}/advance`, {
      headers,
      params: { workspace_id: account.workspaceId },
      data: { target_phase: phase, reason: 'Recorded by the browser test.' },
    });
    expect(advanced.status(), `advance to ${phase}: ${await advanced.text()}`).toBe(200);
  }
  return decisionId;
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
    await expect(page.getByTestId('claims-table').locator('tbody tr')).toHaveCount(3);
    await page.getByTestId('evidence-all-uploads').click();
    await expect(page).toHaveURL(/\/evidence$/);
    await expect(page.getByTestId('upload-row')).toHaveCount(2);

    // On a phone the review table scrolls inside its own box; the page keeps the width of the screen.
    await page.setViewportSize(PHONE);
    await page.goto(`${BASE_URL}/evidence?batch_id=${waitingId}`);
    await expect(page.getByTestId('claims-table').locator('tbody tr')).toHaveCount(3);
    await expectFitsTheScreen(page, 'the review page');
    await page.goto(`${BASE_URL}/evidence`);
    await expect(page.getByTestId('upload-row')).toHaveCount(2);
    await expectFitsTheScreen(page, 'the list of uploads');
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

  test('a file is uploaded, reviewed by column and published without leaving the site', async ({ page, request }) => {
    const serverErrors: string[] = [];
    page.on('response', (response) => {
      if (response.status() >= 500) {
        serverErrors.push(`${response.request().method()} ${new URL(response.url()).pathname} -> ${response.status()}`);
      }
    });

    const account = await createLoggedInSession(page, request, 'intake');
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
    const cells = page.getByTestId('claims-table').locator('tbody tr');
    await expect(cells).toHaveCount(6);

    // The page requests a readiness assessment on every load, so reopening it
    // must keep working (the second assessment used to fail with HTTP 500).
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Readiness gate' })).toBeVisible();
    await expect(cells).toHaveCount(6);

    const headline = page.getByTestId('column-review-headline');
    const standing = page.getByTestId('column-review-standing');
    const reason = page.getByTestId('column-review-reason');
    const acceptAll = page.getByTestId('column-review-accept-all');
    const notice = page.getByRole('status');
    const publish = page.getByRole('button', { name: 'Publish to World State' });

    await test.step('the file is reviewed by column, not cell by cell', async () => {
      // The page says what the rows are; nobody types "Supplier" into a dialog.
      await expect(headline).toHaveText(
        'Each row of suppliers.csv is a supplier, recognised from the column supplier_id.',
      );
      const columns = page.getByTestId('column-review-row');
      await expect(columns).toHaveCount(3);
      await expect(columns.nth(0)).toContainText('supplier_id');
      await expect(columns.nth(0)).toContainText('S-1, S-2');
      await expect(columns.nth(0)).toContainText('identifies each supplier');
      await expect(columns.nth(1)).toContainText('Acme Metals, Borealis Plastics');
      await expect(standing).toHaveText('6 values wait for a decision.');
      await expect(publish).toBeDisabled();

      // A decision is recorded with its reason, so it needs one.
      await acceptAll.click();
      await expect(page.getByTestId('column-review-error')).toHaveText('Give the reason for the decision first.');
      await expect(standing).toHaveText('6 values wait for a decision.');
      await reason.fill('Checked against the supplier master.');

      // One column is left out; everything else is accepted in one decision.
      await page.getByRole('button', { name: 'Reject the column country' }).click();
      await expect(notice).toHaveText(
        '2 values in the column country of suppliers.csv rejected, recorded with your reason.',
      );
      await expect(acceptAll).toHaveText('Accept all 4 waiting values');
      await acceptAll.click();
      await expect(notice).toHaveText('4 values in 2 columns of suppliers.csv accepted, recorded with your reason.');
      await expect(standing).toHaveText('Every value is decided: 4 values accepted, 2 values rejected.');
    });

    await test.step('and published', async () => {
      await publish.click();
      await expect(page.getByText('Published snapshot')).toBeVisible({ timeout: 15_000 });
      await page.getByRole('link', { name: 'Inspect World State' }).click();
      await expect(page).toHaveURL(/\/nexus\/world/);
      await expect(page.getByText('Acme Metals').first()).toBeVisible();
      await expect(page.getByText('Borealis Plastics').first()).toBeVisible();
    });

    await test.step('a file whose column names say nothing is told what its rows are', async () => {
      const batchId = await publishSupplierFile(
        request,
        account,
        'lieferanten.csv',
        'Lieferant Nr,Firma,Land\nL-1,Nordwind Metall,DE\nL-2,Sundsvall Plast,SE\n',
        { publish: false },
      );
      await page.goto(`${BASE_URL}/evidence?batch_id=${batchId}`);
      await expect(headline).toContainText('The column names of lieferanten.csv do not say what each row is.');
      await reason.fill('Supplier list from the Hamburg office.');
      await acceptAll.click();
      await expect(page.getByTestId('column-review-error')).toHaveText('Choose what each row of this file is.');

      await page.getByTestId('column-review-kind').selectOption('Supplier');
      await acceptAll.click();
      await expect(page.getByTestId('column-review-error')).toHaveText(
        'Choose the column that identifies each supplier.',
      );
      await page.getByTestId('column-review-key').selectOption('Lieferant Nr');
      await page.getByLabel('Field name for Firma').fill('supplier_name');
      await acceptAll.click();
      await expect(notice).toHaveText('6 values in 3 columns of lieferanten.csv accepted, recorded with your reason.');
      await expect(headline).toHaveText(
        'Each row of lieferanten.csv is a supplier, identified by the column Lieferant Nr.',
      );

      await publish.click();
      await expect(page.getByText('Published snapshot')).toBeVisible({ timeout: 15_000 });
      await page.goto(`${BASE_URL}/nexus/world`);
      await expect(page.getByText('Nordwind Metall').first()).toBeVisible();
      await expect(page.getByText('Acme Metals').first()).toBeVisible();
    });

    await test.step('a file of several hundred rows is read a page at a time and published', async () => {
      // 400 suppliers of three values each: 1,200 values. The page used to
      // draw a table row for every value of a file, and publishing linked
      // every record to every value (here 480,000 links).
      const rows = Array.from({ length: 400 }, (_, index) => {
        const number = index + 1;
        return `B-${number},Bulk Supplier ${number},${number % 2 ? 'DE' : 'SE'}`;
      });
      const batchId = await publishSupplierFile(
        request,
        account,
        'bulk_suppliers.csv',
        `supplier_id,supplier_name,country\n${rows.join('\n')}\n`,
        { publish: false },
      );
      await page.goto(`${BASE_URL}/evidence?batch_id=${batchId}`);

      // The counts are of the whole file; the table draws one page of it.
      const counts = page.getByTestId('evidence-count');
      const showing = page.getByTestId('claims-showing');
      await expect(counts.filter({ hasText: 'Claims' })).toContainText('1,200');
      await expect(counts.filter({ hasText: 'Pending' })).toContainText('1,200');
      await expect(showing).toHaveText('Showing 100 of 1,200 values, in file order.');
      await expect(cells).toHaveCount(100);
      await expect(cells.first()).toContainText('B-1');
      await page.getByTestId('claims-more').click();
      await expect(showing).toHaveText('Showing 200 of 1,200 values, in file order.');
      await expect(cells).toHaveCount(200);

      // A particular row or value is found without paging to it.
      await page.getByTestId('claims-filter-row').fill('377');
      await expect(showing).toHaveText('All 3 values that match are shown.');
      await expect(cells).toHaveCount(3);
      await expect(cells.nth(1)).toContainText('Bulk Supplier 377');
      await page.getByTestId('claims-filter-row').fill('');
      await page.getByTestId('claims-filter-column').selectOption('supplier_name');
      await page.getByTestId('claims-filter-value').fill('supplier 39');
      // Bulk Supplier 39 and 390 to 399.
      await expect(showing).toHaveText('All 11 values that match are shown.');
      await page.getByTestId('claims-filter-row').fill('row');
      await expect(page.getByTestId('claims-filter-problem')).toHaveText(
        'A row is a whole number from 1, as in the file.',
      );
      await page.getByTestId('claims-filter-clear').click();
      await expect(showing).toHaveText('Showing 100 of 1,200 values, in file order.');

      // While a search is on its way, the line under the table does not go on
      // describing the list before it ("100 of 1,200" was not what was asked).
      let release: () => void = () => {};
      const held = new Promise<void>((resolve) => { release = resolve; });
      const searchFor = (text: string) => (url: URL) =>
        url.pathname.endsWith('/claims') && url.searchParams.get('value') === text;
      await page.route(searchFor('B-399'), async (route) => {
        await held;
        await route.continue();
      });
      await page.getByTestId('claims-filter-value').fill('B-399');
      await expect(showing).toHaveText('Searching…');
      await expect(page.getByTestId('claims-more')).toHaveCount(0);
      release();
      await expect(showing).toHaveText('The 1 value that matches is shown.');
      await expect(cells).toHaveCount(1);
      await page.unroute(searchFor('B-399'));
      await page.getByTestId('claims-filter-clear').click();
      await expect(showing).toHaveText('Showing 100 of 1,200 values, in file order.');

      // A read of the values that fails says so and shows no values as if
      // they were the answer; the counts and the columns stay, and Retry works.
      const rowSeven = (url: URL) =>
        url.pathname.endsWith('/claims') && url.searchParams.get('row_number') === '7';
      await page.route(rowSeven, (route) => route.abort('failed'));
      await page.getByTestId('claims-filter-row').fill('7');
      await expect(page.getByTestId('claims-error')).toContainText(
        'The values could not be loaded: Network request failed',
      );
      await expect(showing).toHaveText('The values are not shown: they could not be loaded.');
      await expect(cells).toHaveCount(0);
      await expect(counts.filter({ hasText: 'Claims' })).toContainText('1,200');
      await expect(page.getByTestId('column-review-row')).toHaveCount(3);
      await page.unroute(rowSeven);
      await page.getByTestId('claims-error').getByRole('button', { name: 'Retry' }).click();
      await expect(showing).toHaveText('All 3 values that match are shown.');
      await expect(page.getByTestId('claims-error')).toHaveCount(0);
      await page.getByTestId('claims-filter-clear').click();
      await expect(showing).toHaveText('Showing 100 of 1,200 values, in file order.');

      // One decision for the whole file; the table then shows what was decided.
      await reason.fill('Supplier list for the Hamburg plant.');
      await acceptAll.click();
      await expect(notice).toHaveText(
        '1,200 values in 3 columns of bulk_suppliers.csv accepted, recorded with your reason.',
      );
      await expect(counts.filter({ hasText: 'Accepted' })).toContainText('1,200');
      await page.getByTestId('claims-filter-state').selectOption('pending_review');
      await expect(showing).toHaveText('No value matches.');
      await expect(cells).toHaveCount(0);

      await publish.click();
      const snapshot = page.getByText('Published snapshot').locator('..');
      await expect(snapshot).toBeVisible({ timeout: 15_000 });
      // 400 records, each linked to its own three cells.
      await expect(snapshot.getByText('Nodes').locator('..')).toContainText('400');
      await expect(snapshot.getByText('Provenance links').locator('..')).toContainText('1,200');
    });

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

  test('the retired /audit address opens the audit log on the Operations page', async ({ page, request }) => {
    // /audit was a second audit page that sent no sign-in and offered
    // category and date filters the API never had.
    await openEmptyWorkspace(page, request);
    await page.goto(`${BASE_URL}/audit`);
    await expect(page).toHaveURL(/\/nexus\/operations#audit$/);
    await expect(page.getByTestId('operations-audit-count')).toBeVisible();
  });

  test('the audit log can be read beyond its first hundred events', async ({ page, request }) => {
    // Each accepted value is one audit event: 40 rows of 3 columns give more
    // than a hundred. The panel used to stop at the newest hundred.
    const account = await createLoggedInSession(page, request, 'audit');
    const rows = Array.from({ length: 40 }, (_, n) => `S-${300 + n},Supplier ${300 + n},IN`).join('\n');
    await publishSupplierFile(request, account, 'many_suppliers.csv', `supplier_id,supplier_name,country\n${rows}\n`);
    const all = await request.get(`${BACKEND}/api/v1/audit`, {
      headers: { Authorization: `Bearer ${account.token}` },
      params: { workspace_id: account.workspaceId, limit: 200 },
    });
    expect(all.status()).toBe(200);
    const total = ((await all.json()) as unknown[]).length;
    expect(total).toBeGreaterThan(100);
    expect(total).toBeLessThan(200);

    await page.goto(`${BASE_URL}/nexus/operations`);
    const count = page.getByTestId('operations-audit-count');
    // Not the total yet, and the page says so.
    await expect(count).toHaveText('Latest 100 events');
    await expect(page.locator('#audit tbody tr')).toHaveCount(100);

    await page.getByTestId('operations-audit-older').click();
    await expect(count).toHaveText(`${total} events`);
    await expect(page.locator('#audit tbody tr')).toHaveCount(total);
    // Everything is shown: there is nothing older to ask for.
    await expect(page.getByTestId('operations-audit-older')).toHaveCount(0);
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

test.describe('Decision Room', () => {
  test('a decision is described in words before it is approved, and after', async ({ page, request }) => {
    const account = await createLoggedInSession(page, request, 'decision');
    const decisionId = await recordDecisionAwaitingApproval(request, account);

    await page.goto(`${BASE_URL}/nexus/decision-room`);
    // The list says what the decision is about; its identifier is the small print.
    await expect(page.getByTestId('decision-list-title')).toHaveText(
      'Cast iron housings from S-101 are three weeks late.',
    );
    // The recommended action is named, not shown as "opt-b".
    const recommended = page.getByTestId('decision-recommended');
    await expect(recommended).toHaveText('Move 250 units to Acme Metals');
    await expect(page.getByText('Option opt-b', { exact: true })).toBeVisible();
    await expect(page.getByText(decisionId).first()).toBeVisible();

    const options = page.getByTestId('decision-option');
    await expect(options).toHaveCount(2);
    await expect(options.nth(0)).toContainText('Expedite PO-5001 by air');
    await expect(options.nth(0)).toContainText('expected cost: 18,400');
    await expect(options.nth(0)).not.toContainText('RECOMMENDED');
    await expect(options.nth(1)).toContainText('Move 250 units to Acme Metals');
    await expect(options.nth(1)).toContainText('RECOMMENDED');
    await expect(options.nth(1)).toContainText('expected cost: 9,200 · lead time days: 12');
    // Nothing is printed as a raw record.
    const listed = page.getByTestId('decision-options');
    await expect(listed).not.toContainText('{');
    await expect(listed).not.toContainText('option_id');

    // Approving keeps the same description on screen.
    await page.getByRole('button', { name: 'Approve proposal' }).click();
    await expect(page.getByRole('status')).toContainText('Decision approved.');
    await expect(recommended).toHaveText('Move 250 units to Acme Metals');
    await expect(options).toHaveCount(2);
    await expect(page.getByRole('button', { name: 'Execute approved action' })).toBeVisible();
  });
});

test.describe('Phone layout', () => {
  test.use({ viewport: PHONE });

  const SECTIONS = ['Command Center', 'World State', 'Intelligence', 'Scenario Studio', 'Decision Room', 'Operations'];
  // Something each page shows once it has loaded, so the width is measured on the real page.
  const PAGES: Array<[string, (page: Page) => Promise<void>]> = [
    ['/nexus/cockpit', async (page) => { await expect(page.getByTestId('cockpit-tiles')).toBeVisible(); }],
    ['/nexus/world', async (page) => { await expect(page.getByText('World State').last()).toBeVisible(); }],
    ['/nexus/impact', async (page) => { await expect(page.getByTestId('impact-empty')).toBeVisible(); }],
    ['/nexus/scenarios', async (page) => { await expect(page.getByText('Scenario Studio').last()).toBeVisible(); }],
    ['/nexus/decision-room', async (page) => { await expect(page.getByTestId('decisions-empty')).toBeVisible(); }],
    ['/nexus/operations', async (page) => { await expect(page.getByTestId('operations-audit-count')).toBeVisible(); }],
  ];

  test('every Nexus page fits the screen, with the navigation above it', async ({ page, request }) => {
    await openEmptyWorkspace(page, request);
    for (const [path, loaded] of PAGES) {
      await page.goto(`${BASE_URL}${path}`);
      await loaded(page);

      const nav = page.getByTestId('nexus-nav-narrow');
      await expect(nav).toBeVisible();
      await expect(page.getByTestId('nexus-nav-wide')).toBeHidden();
      // All six sections are on the screen: none sits behind a sideways scroll.
      for (const name of SECTIONS) {
        await expect(nav.getByRole('link', { name, exact: true })).toBeInViewport();
      }

      // The page starts below the navigation and spans the screen. (As one
      // row, the navigation sat beside the page and pushed it off screen.)
      const navBox = await nav.boundingBox();
      const pageBox = await page.getByTestId('nexus-page').boundingBox();
      expect(navBox && pageBox, `${path}: navigation and page are laid out`).toBeTruthy();
      expect(pageBox!.y, `${path}: page starts below the navigation`).toBeGreaterThanOrEqual(
        navBox!.y + navBox!.height - 1,
      );
      expect(pageBox!.x, `${path}: page starts at the left edge`).toBe(0);
      expect(pageBox!.width, `${path}: page spans the screen`).toBe(PHONE.width);

      await expectFitsTheScreen(page, path);
    }
  });

  test('pages that show data fit the screen too', async ({ page, request }) => {
    // Tables, long identifiers and status keys only appear once there is data.
    const account = await createLoggedInSession(page, request, 'phone');
    await publishSupplierFile(
      request,
      account,
      'suppliers.csv',
      'supplier_id,supplier_name,country,status\n' +
        'S-100,Acme Metals GmbH,DE,active\n' +
        'S-101,Bharat Castings Private Limited,IN,delayed\n',
    );
    const waiting = await publishSupplierFile(
      request,
      account,
      'more_suppliers.csv',
      'supplier_id,supplier_name,country\nS-200,Castor Bearings,JP\n',
      { publish: false },
    );
    // A file name and a column name are single words with nowhere to wrap,
    // and the review page puts both into sentences.
    const longNames = await publishSupplierFile(
      request,
      account,
      'lieferanten_stammdaten_export_werk_hamburg_2026_11_14.csv',
      'Lieferantennummer_laut_Stammdatenblatt,Firmenbezeichnung_vollstaendig\nL-1,Nordwind Metall\n',
      { publish: false },
    );
    await recordDecisionAwaitingApproval(request, account);

    const pages: Array<[string, (page: Page) => Promise<void>]> = [
      ['/nexus/cockpit', async (p) => { await expect(p.getByTestId('cockpit-tiles')).toBeVisible(); }],
      ['/nexus/world', async (p) => { await expect(p.getByText('Acme Metals GmbH').first()).toBeVisible(); }],
      ['/nexus/world?view=quality', async (p) => { await expect(p.getByText('Per-type completeness')).toBeVisible(); }],
      ['/nexus/world?view=provenance', async (p) => { await expect(p.getByText('Acme Metals GmbH').first()).toBeVisible(); }],
      ['/nexus/operations', async (p) => {
        // The audit table and both health panels have loaded.
        await expect(p.getByTestId('operations-audit-count')).not.toHaveText('0 events');
        await expect(p.getByTestId('operations-models')).toBeVisible();
      }],
      ['/evidence', async (p) => { await expect(p.getByTestId('upload-row')).toHaveCount(3); }],
      [`/evidence?batch_id=${waiting}`, async (p) => {
        await expect(p.getByText('Castor Bearings').first()).toBeVisible();
        await expect(p.getByTestId('column-review-row')).toHaveCount(3);
      }],
      [`/evidence?batch_id=${longNames}`, async (p) => {
        await expect(p.getByTestId('column-review-headline')).toContainText('do not say what each row is');
        await expect(p.getByTestId('column-review-key')).toBeVisible();
        await expect(p.getByTestId('column-review-row')).toHaveCount(2);
      }],
      ['/nexus/decision-room', async (p) => { await expect(p.getByTestId('decision-option')).toHaveCount(2); }],
      ['/app', async (p) => { await expect(p.getByTestId('app-user-email')).toHaveText(account.email); }],
    ];
    for (const [path, loaded] of pages) {
      await page.goto(`${BASE_URL}${path}`);
      await loaded(page);
      await expectFitsTheScreen(page, path);
    }
  });

  test('the sidebar returns on a wide screen', async ({ page, request }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await openEmptyWorkspace(page, request);
    await page.goto(`${BASE_URL}/nexus/cockpit`);
    await expect(page.getByTestId('nexus-nav-wide')).toBeVisible();
    await expect(page.getByTestId('nexus-nav-narrow')).toBeHidden();
    const navBox = await page.getByTestId('nexus-nav-wide').boundingBox();
    const pageBox = await page.getByTestId('nexus-page').boundingBox();
    // Sidebar on the left, page beside it.
    expect(pageBox!.x).toBeGreaterThanOrEqual(navBox!.x + navBox!.width - 1);
    await expectFitsTheScreen(page, '/nexus/cockpit');
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

  test('the Operations page says which feeds failed on a 500', async ({ page, context, request }) => {
    await openEmptyWorkspace(page, request);
    await context.route('**/api/v1/**', (route) => {
      if (route.request().url().includes('/auth/me')) {
        return route.continue();
      }
      return route.fulfill({ status: 500, body: JSON.stringify({ detail: 'backend error' }) });
    });
    await page.goto(`${BASE_URL}/nexus/operations`);
    await expect(page.getByRole('status').filter({ hasText: '3 of 3 operational feeds unavailable' })).toBeVisible({
      timeout: 10000,
    });
    // A feed that did not answer is reported as not loaded. "No audit events
    // recorded yet" would be a statement about the log, and nobody read it.
    await expect(page.getByTestId('operations-audit-failed')).toHaveText(
      'The audit log could not be loaded. Use Refresh to try again.',
    );
    await expect(page.getByTestId('operations-audit-count')).toHaveText('Not loaded');
    await expect(page.getByText('No audit events recorded yet.')).toHaveCount(0);
    await expect(page.getByText('Model health could not be loaded. Use Refresh to try again.')).toBeVisible();
    await expect(page.getByText('Relay health could not be loaded. Use Refresh to try again.')).toBeVisible();
    await expect(page.getByText('No trained model is deployed in this workspace.')).toHaveCount(0);
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
