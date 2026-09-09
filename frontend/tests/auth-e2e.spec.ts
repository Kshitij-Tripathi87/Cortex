/**
 * B2 auth acceptance (Playwright, runs against the real stack in CI e2e).
 *
 * Proves the B2 gate end-to-end: fresh signup → server-created org/workspace/
 * trial → onboarding → protected /app with a live canonical Nexus call →
 * reload persistence → logout → login → guards → expiry invalidation.
 *
 * Only UI-error MAPPING uses route interception (429 test); every auth state
 * transition exercises the real backend.
 */

import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

const BACKEND = process.env.BACKEND_URL || 'http://localhost:8000';

function uniqueEmail(tag: string): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `b2-${tag}-${Date.now()}-${rand}@example.com`;
}

interface SignupResult {
  email: string;
  password: string;
  accessToken: string;
  workspaceId: string;
  userId: string;
}

async function signupViaApi(
  request: APIRequestContext,
  tag: string,
  org = 'B2 E2E Org',
): Promise<SignupResult> {
  const email = uniqueEmail(tag);
  const password = 'E2esecures1';
  const resp = await request.post(`${BACKEND}/api/v1/auth/signup`, {
    data: { organization_name: org, email, password, full_name: 'B2 Tester' },
  });
  expect(resp.status()).toBe(201);
  const body = await resp.json();
  return {
    email,
    password,
    accessToken: body.access_token as string,
    workspaceId: body.workspace_id as string,
    userId: body.user_id as string,
  };
}

async function loginViaApi(
  request: APIRequestContext,
  email: string,
  password: string,
): Promise<SignupResult> {
  const resp = await request.post(`${BACKEND}/api/v1/auth/login`, {
    data: { email, password },
  });
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  return {
    email,
    password,
    accessToken: body.access_token as string,
    workspaceId: body.workspace_id as string,
    userId: body.user_id as string,
  };
}

async function setSession(page: Page, accessToken: string): Promise<void> {
  await page.goto('/auth/login');
  await page.evaluate((token) => {
    window.localStorage.setItem('cortex:access_token', token);
  }, accessToken);
}

test.describe('B2 auth gate', () => {
  test('fresh signup → onboarding → app → reload → logout → login', async ({ page }) => {
    const email = uniqueEmail('gate');
    const org = `Gate Org ${Date.now()}`;

    await page.goto('/auth/signup');
    await page.getByLabel('Your name').fill('Gate Tester');
    await page.getByLabel('Work email').fill(email);
    await page.getByLabel('Password', { exact: true }).fill('Gatesecure1');
    await page.getByLabel('Confirm password').fill('Gatesecure1');
    await page.getByLabel('Organization name').fill(org);
    await page.getByTestId('signup-submit').click();

    // Server-created org/workspace/trial, verified on the onboarding boundary.
    await expect(page).toHaveURL(/\/onboarding/);
    await expect(page.getByTestId('onboarding-org')).toHaveText(org);
    await expect(page.getByTestId('onboarding-workspace')).toHaveText(org);
    await expect(page.getByTestId('onboarding-email')).toHaveText(email);
    await expect(page.getByTestId('onboarding-trial')).toContainText(/day(s)? left \(trial\)/);
    await page.getByTestId('onboarding-continue').click();

    // Protected app with a live canonical Nexus call.
    await expect(page).toHaveURL(/\/app$/);
    await expect(page.getByTestId('app-user-email')).toHaveText(email);
    await expect(page.getByTestId('nexus-status-ok')).toBeVisible({ timeout: 10_000 });

    // Reload persistence: still authenticated.
    await page.reload();
    await expect(page.getByTestId('app-user-email')).toHaveText(email);
    await expect(page.getByTestId('nexus-status-ok')).toBeVisible({ timeout: 10_000 });

    // Logout → protected routes inaccessible.
    await page.getByTestId('logout-button').click();
    await expect(page).toHaveURL(/\/auth\/login/);
    await page.goto('/app');
    await expect(page).toHaveURL(/\/auth\/login\?next=%2Fapp/);

    // Login returns to the app (onboarding already acked).
    await page.getByLabel('Work email').fill(email);
    await page.getByLabel('Password').fill('Gatesecure1');
    await page.getByTestId('login-submit').click();
    await expect(page).toHaveURL(/\/app$/);
    await expect(page.getByTestId('app-user-email')).toHaveText(email);
  });

  test('anonymous → protected route bounces with validated next', async ({ page }) => {
    await page.goto('/app');
    await expect(page).toHaveURL(/\/auth\/login\?next=%2Fapp/);
    await page.goto('/workspace/cockpit');
    await expect(page).toHaveURL(/\/auth\/login\?next=%2Fworkspace%2Fcockpit/);
  });

  test('external next URLs are rejected', async ({ page, request }) => {
    const { email, password } = await signupViaApi(request, 'extnext');
    await page.goto('/auth/login?next=https://evil.example.com/phish');
    await page.getByLabel('Work email').fill(email);
    await page.getByLabel('Password').fill(password);
    await page.getByTestId('login-submit').click();
    // Fresh user → onboarding (no ack yet); never the external URL.
    await expect(page).toHaveURL(/\/onboarding/);
    expect(page.url()).toMatch(/^http:\/\/localhost:3000\//);
  });

  test('authenticated → /auth/login redirects into the app', async ({ page, request }) => {
    const { accessToken } = await signupViaApi(request, 'authed');
    await setSession(page, accessToken);
    // Ack onboarding via the UI once so the redirect target is deterministic.
    await page.goto('/onboarding');
    await page.getByTestId('onboarding-continue').click();
    await expect(page).toHaveURL(/\/app$/);
    await page.goto('/auth/login');
    await expect(page).toHaveURL(/\/app$/);
  });

  test('login failure is generic and preserves the email', async ({ page, request }) => {
    const { email } = await signupViaApi(request, 'badlogin');
    await page.goto('/auth/login');
    await page.getByLabel('Work email').fill(email);
    await page.getByLabel('Password').fill('Wrongpass1');
    await page.getByTestId('login-submit').click();
    await expect(page.getByTestId('login-error')).toHaveText('Invalid email or password.');
    await expect(page.getByLabel('Work email')).toHaveValue(email);
  });

  test('duplicate signup is a controlled error', async ({ page, request }) => {
    const { email } = await signupViaApi(request, 'dupe');
    await page.goto('/auth/signup');
    await page.getByLabel('Your name').fill('Dupe Tester');
    await page.getByLabel('Work email').fill(email);
    await page.getByLabel('Password', { exact: true }).fill('Dupesecure1');
    await page.getByLabel('Confirm password').fill('Dupesecure1');
    await page.getByLabel('Organization name').fill('Dupe Org');
    await page.getByTestId('signup-submit').click();
    await expect(page.getByTestId('signup-error')).toContainText('already exists');
  });

  test('corrupted token → 401 invalidates the session', async ({ page, request }) => {
    const { accessToken } = await signupViaApi(request, 'corrupt');
    await setSession(page, accessToken);
    await page.goto('/app');
    await expect(page.getByTestId('app-user-email')).toBeVisible();
    // Simulate expiry/revocation: the next /auth/me answers 401.
    await page.evaluate(() => {
      window.localStorage.setItem('cortex:access_token', 'forged-or-expired-token');
    });
    await page.reload();
    await expect(page).toHaveURL(/\/auth\/login/);
    // Stale workspace data is never rendered after invalidation.
    await expect(page.getByTestId('app-page')).toHaveCount(0);
  });

  test('403 from the API keeps the session alive', async ({ page, request }) => {
    const alice = await signupViaApi(request, 'alice403');
    const bob = await signupViaApi(request, 'bob403');
    await setSession(page, alice.accessToken);
    await page.goto('/app');
    await expect(page.getByTestId('app-user-email')).toHaveText(alice.email);
    // Cross-workspace canonical call from the page context.
    const status = await page.evaluate(
      async ({ backend, token, foreignWs }) => {
        const resp = await fetch(
          `${backend}/api/v1/nexus/decisions?workspace_id=${foreignWs}&limit=1`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        return resp.status;
      },
      { backend: BACKEND, token: alice.accessToken, foreignWs: bob.workspaceId },
    );
    expect(status).toBe(403);
    // Still authenticated: no bounce, identity intact.
    await expect(page.getByTestId('app-user-email')).toHaveText(alice.email);
    await expect(page).toHaveURL(/\/app$/);
  });

  test('rate-limited login renders the rate-limit UI', async ({ page }) => {
    await page.route('**/api/v1/auth/login', (route) =>
      route.fulfill({
        status: 429,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Rate limit exceeded' }),
      }),
    );
    await page.goto('/auth/login');
    await page.getByLabel('Work email').fill('ratelimit@example.com');
    await page.getByLabel('Password').fill('RateLimited1');
    await page.getByTestId('login-submit').click();
    await expect(page.getByTestId('login-error')).toContainText('Too many attempts');
  });

  test('forgot-password is uniform for known and unknown emails', async ({ page, request }) => {
    const { email } = await signupViaApi(request, 'forgot');
    for (const candidate of [email, uniqueEmail('ghost')]) {
      await page.goto('/auth/forgot-password');
      await page.getByLabel('Work email').fill(candidate);
      await page.getByTestId('forgot-submit').click();
      await expect(page.getByTestId('forgot-done')).toContainText('If an account exists');
    }
  });

  test('reset-password redeems a token and the new password logs in', async ({
    page,
    request,
  }) => {
    const { email } = await signupViaApi(request, 'reset');
    // The e2e backend runs in test env, so the token is disclosed in-band.
    const reqResp = await request.post(`${BACKEND}/api/v1/auth/reset/request`, {
      data: { email },
    });
    expect(reqResp.status()).toBe(200);
    const token = ((await reqResp.json()) as { reset_token: string }).reset_token;
    expect(token).toBeTruthy();

    await page.goto(`/auth/reset-password?token=${token}`);
    await page.getByLabel('New password', { exact: true }).fill('R3setbyplaywright');
    await page.getByLabel('Confirm new password').fill('R3setbyplaywright');
    await page.getByTestId('reset-submit').click();
    await expect(page).toHaveURL(/\/auth\/login\?reset=1/);
    await expect(page.getByTestId('login-reset-notice')).toBeVisible();

    await loginViaApi(request, email, 'R3setbyplaywright');
  });

  test('change-password rotates the credential from /app', async ({ page, request }) => {
    const { email, password } = await signupViaApi(request, 'chpw');
    await setSession(page, (await loginViaApi(request, email, password)).accessToken);
    await page.goto('/app');
    await expect(page.getByTestId('change-password-card')).toBeVisible();
    await page.getByLabel('Current password').fill(password);
    await page.getByLabel('New password', { exact: true }).fill('R0tatedbypwtest');
    await page.getByLabel('Confirm new password').fill('R0tatedbypwtest');
    await page.getByTestId('change-password-submit').click();
    await expect(page.getByTestId('change-password-notice')).toContainText('Password changed.');
    // Old password dead, new password works.
    const oldLogin = await request.post(`${BACKEND}/api/v1/auth/login`, {
      data: { email, password },
    });
    expect(oldLogin.status()).toBe(401);
    await loginViaApi(request, email, 'R0tatedbypwtest');
  });
});
