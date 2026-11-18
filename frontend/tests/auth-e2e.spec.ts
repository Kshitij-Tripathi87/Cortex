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

async function setSession(page: Page, accessToken: string, userId?: string): Promise<void> {
  await page.goto('/auth/login');
  await page.evaluate(
    ({ token, user }) => {
      window.localStorage.setItem('cortex:access_token', token);
      // /app sits behind the onboarding ack gate; tests that bypass the
      // onboarding UI (covered end-to-end by the gate test) ack it directly.
      if (user) {
        window.localStorage.setItem(`cortex:onboarding_ack:${user}`, '1');
      }
    },
    { token: accessToken, user: userId ?? null },
  );
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
    await expect(page.getByTestId('onboarding-trial')).toHaveText(
      /^Trial · 7 days left, ends \d{1,2} [A-Z][a-z]{2} \d{4}$/,
    );
    await expect(page.getByTestId('onboarding-plan-paused')).toHaveCount(0);
    await page.getByTestId('onboarding-continue').click();

    // Protected app with a live canonical Nexus call.
    await expect(page).toHaveURL(/\/app$/);
    await expect(page.getByTestId('app-user-email')).toHaveText(email);
    await expect(page.getByTestId('nexus-status-ok')).toBeVisible({ timeout: 10_000 });
    // A whole sentence about the real workspace (it used to print
    // "Connected. decisions in this workspace." with the number missing).
    await expect(page.getByTestId('nexus-status-ok')).toHaveText(
      'Connected. No decisions recorded in this workspace yet.',
    );

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
    await page.goto('/onboarding');
    await expect(page).toHaveURL(/\/auth\/login\?next=%2Fonboarding/);
  });

  test('retired /workspace addresses land on the working cockpit', async ({ page }) => {
    // The old demo area is gone. Any of its addresses must end on the real
    // cockpit, never on a "page not found" and never on a demo screen.
    for (const retired of ['/workspace', '/workspace/cockpit', '/workspace/graph', '/workspace/data']) {
      await page.goto(retired);
      await expect(page).toHaveURL(/\/nexus\/cockpit$/);
    }
    // Signed out, the cockpit asks for sign-in and comes back to itself afterwards.
    const signIn = page.getByRole('link', { name: 'Sign in', exact: true });
    await expect(signIn).toBeVisible();
    await expect(signIn).toHaveAttribute('href', '/auth/login?next=%2Fnexus%2Fcockpit');
  });

  test('"Open Nexus workspace" opens the working cockpit', async ({ page, request }) => {
    const { accessToken, userId } = await signupViaApi(request, 'frontdoor');
    await setSession(page, accessToken, userId);
    await page.goto('/app');
    const open = page.getByTestId('open-workspace-link');
    await expect(open).toHaveAttribute('href', '/nexus/cockpit');
    await open.click();
    await expect(page).toHaveURL(/\/nexus\/cockpit$/);
    // The working cockpit: a plain-text heading (no markup characters leak
    // into it) and none of the invented alerts the old demo screen showed.
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toBeVisible();
    await expect(heading).not.toContainText('<');
    await expect(page.getByText('BLOCKING')).toHaveCount(0);
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
    const { accessToken, userId } = await signupViaApi(request, 'corrupt');
    await setSession(page, accessToken, userId);
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
    await setSession(page, alice.accessToken, alice.userId);
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
    const outcomes: string[] = [];
    for (const candidate of [email, uniqueEmail('ghost')]) {
      await page.goto('/auth/forgot-password');
      await page.getByLabel('Work email').fill(candidate);
      const [answer] = await Promise.all([
        page.waitForResponse('**/api/v1/auth/reset/request'),
        page.getByTestId('forgot-submit').click(),
      ]);
      const done = page.getByTestId('forgot-done');
      await expect(done).toContainText('If an account exists');
      outcomes.push((await done.innerText()).trim());
      // The test backend hands the token back in the response; the page must
      // never show it (whoever reads the screen could reset the password).
      const token = ((await answer.json()) as { reset_token: string | null }).reset_token;
      if (token) expect(await page.content()).not.toContain(token);
    }
    expect(outcomes[0]).toBe(outcomes[1]);
  });

  test('forgot-password promises no email: a person sends the link', async ({ page, request }) => {
    const { email } = await signupViaApi(request, 'honest');
    await page.goto('/auth/forgot-password');
    // Before asking: how it works, in so many words.
    await expect(page.getByTestId('forgot-page')).toContainText(
      'A member of the Cortex team sends the reset link.',
    );
    await expect(page.getByTestId('forgot-how')).toContainText(
      'Cortex does not send automatic emails yet',
    );
    await expect(page.getByTestId('forgot-how')).toContainText('It is not instant.');

    await page.getByLabel('Work email').fill(email);
    await page.getByTestId('forgot-submit').click();

    const done = page.getByTestId('forgot-done');
    await expect(done).toContainText('Your request is recorded.');
    await expect(done).toContainText('a member of the Cortex team will send a single-use reset link');
    await expect(done).toContainText('Nothing was emailed automatically');
    // The old page said a link was "on its way" and that it "expires in 30 minutes".
    await expect(done).not.toContainText('on its way');
    await expect(done).not.toContainText('30 minutes');
    // A way out for someone who hears nothing.
    await done.getByRole('link', { name: 'Heard nothing? Write to us' }).click();
    await expect(page).toHaveURL(/\/contact\?topic=general#write$/);
  });

  test('forgot-password says so when the request was not recorded', async ({ page }) => {
    const cases: Array<[number, string]> = [
      [500, 'Your request could not be recorded. Nothing was sent.'],
      [429, 'Too many reset requests from your network for now, so this one was not recorded.'],
    ];
    for (const [status, message] of cases) {
      await page.route('**/api/v1/auth/reset/request', (route) =>
        route.fulfill({
          status,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'refused' }),
        }),
      );
      await page.goto('/auth/forgot-password');
      await page.getByLabel('Work email').fill('someone@example.com');
      await page.getByTestId('forgot-submit').click();

      await expect(page.getByTestId('forgot-error')).toContainText(message);
      // Nobody on the team will see this request: the page must not say "recorded".
      await expect(page.getByTestId('forgot-done')).toHaveCount(0);
      // The form is still there, with what was typed, to try again.
      await expect(page.getByLabel('Work email')).toHaveValue('someone@example.com');
      await expect(page.getByTestId('forgot-submit')).toBeEnabled();
      await page.unroute('**/api/v1/auth/reset/request');
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

    // The link worked once. Opened again it says so, changes nothing, and
    // points to where a new one is requested.
    await page.goto(`/auth/reset-password?token=${token}`);
    await page.getByLabel('New password', { exact: true }).fill('An0therpassword');
    await page.getByLabel('Confirm new password').fill('An0therpassword');
    await page.getByTestId('reset-submit').click();
    const refused = page.getByTestId('reset-error');
    await expect(refused).toContainText('This reset link is no longer valid');
    await expect(refused).toContainText('Your password was not changed.');
    await loginViaApi(request, email, 'R3setbyplaywright');
    await page.getByTestId('reset-request-new').click();
    await expect(page).toHaveURL(/\/auth\/forgot-password$/);
  });

  test('a reset link that was never valid is refused the same way', async ({ page }) => {
    await page.goto(`/auth/reset-password?token=${'n0t-a-real-token'.repeat(3)}`);
    await expect(page.getByTestId('reset-page')).toContainText(
      'A reset link works once and for a limited time.',
    );
    await page.getByLabel('New password', { exact: true }).fill('R3setbyplaywright');
    await page.getByLabel('Confirm new password').fill('R3setbyplaywright');
    await page.getByTestId('reset-submit').click();
    await expect(page.getByTestId('reset-error')).toContainText('This reset link is no longer valid');
    await expect(page.getByTestId('reset-request-new')).toHaveAttribute(
      'href',
      '/auth/forgot-password',
    );
  });

  test('change-password rotates the credential from /app', async ({ page, request }) => {
    const { email, password } = await signupViaApi(request, 'chpw');
    const login = await loginViaApi(request, email, password);
    await setSession(page, login.accessToken, login.userId);
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

test.describe('Plan and trial', () => {
  // Days are printed in the visitor's time zone; pin one for the expected text.
  test.use({ timezoneId: 'UTC' });

  async function realMe(request: APIRequestContext, accessToken: string) {
    const resp = await request.get(`${BACKEND}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    expect(resp.status()).toBe(200);
    return (await resp.json()) as {
      organization: { plan: string; trial_ends_at: string | null; subscription_active: boolean };
    };
  }

  test('a new account sees its running trial and no pause notice', async ({ page, request }) => {
    const user = await signupViaApi(request, 'trial');
    // The real API states the verdict the site relies on.
    const me = await realMe(request, user.accessToken);
    expect(me.organization.plan).toBe('trial');
    expect(me.organization.subscription_active).toBe(true);

    await setSession(page, user.accessToken, user.userId);
    await page.goto('/app');
    await expect(page.getByTestId('app-plan')).toHaveText(
      /· Trial · 7 days left, ends \d{1,2} [A-Z][a-z]{2} \d{4}$/,
    );
    await expect(page.getByTestId('app-plan-paused')).toHaveCount(0);

    await page.goto('/nexus/cockpit');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByTestId('nexus-plan-paused')).toHaveCount(0);
  });

  test('after the trial the site says what ended, what is paused and where to write', async ({
    page,
    request,
  }) => {
    const user = await signupViaApi(request, 'ended');
    // A browser cannot end a trial. The account's real answer is served with
    // the two fields the server changes when the end date passes.
    const me = await realMe(request, user.accessToken);
    me.organization.trial_ends_at = '2026-11-10T12:00:00Z';
    me.organization.subscription_active = false;
    await page.route('**/api/v1/auth/me', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(me) }),
    );

    await setSession(page, user.accessToken, user.userId);
    await page.goto('/app');
    // No more "trial · ends <a day in the past>".
    await expect(page.getByTestId('app-plan')).toHaveText('· Trial ended · on 10 Nov 2026');
    const notice = page.getByTestId('app-plan-paused');
    await expect(notice).toContainText('Your trial ended on 10 Nov 2026.');
    await expect(notice).toContainText('You can still sign in and see your data.');
    await expect(notice).toContainText('Creating, running and approving tasks is paused.');

    // A returning user on a new device passes the setup page again (the
    // "seen it" mark is kept per browser): it must not say "0 days left".
    await page.evaluate(
      (user) => window.localStorage.removeItem(`cortex:onboarding_ack:${user}`),
      user.userId,
    );
    await page.goto('/onboarding');
    await expect(page.getByTestId('onboarding-trial')).toHaveText('Trial ended · on 10 Nov 2026');
    await expect(page.getByTestId('onboarding-plan-paused')).toContainText(
      'Your trial ended on 10 Nov 2026.',
    );

    // The same notice heads every page of the workspace ...
    await page.goto('/nexus/cockpit');
    await expect(page.getByTestId('nexus-plan-paused')).toContainText(
      'Your trial ended on 10 Nov 2026.',
    );
    // ... and leads to the form, with the right topic chosen.
    await page.getByTestId('nexus-plan-paused-contact').click();
    await expect(page).toHaveURL(/\/contact\?topic=sales#write$/);
    await expect(page.getByLabel('Topic')).toHaveValue('sales');
  });
});
