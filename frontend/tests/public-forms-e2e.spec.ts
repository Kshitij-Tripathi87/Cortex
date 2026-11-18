/**
 * Cortex Frontend — public forms E2E spec
 *
 * The demo request form used to show "Your request was received" with a
 * reference number invented in the browser and saved nothing, and the contact
 * pages listed placeholder email addresses. These tests pin the replacement:
 *
 *   - a request is sent to POST /api/v1/public/contact-requests and the
 *     reference shown is the one the server returned;
 *   - when the request cannot be saved the page says so and keeps the form;
 *   - no public page offers an email address; they link to the form.
 *
 * Needs a live backend (the same one the other specs use) for the two
 * "is really saved" tests; the rest intercept the API in the browser.
 */

import { test, expect, type Page, type Request } from '@playwright/test';

const BASE_URL = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';
const SAVE_ROUTE = '**/api/v1/public/contact-requests';
const REFERENCE = /^REQ-[2-9A-HJKMNP-Z]{8}$/;

function isSave(request: Request): boolean {
  return request.method() === 'POST' && request.url().endsWith('/api/v1/public/contact-requests');
}

async function fillDemoStepOne(page: Page): Promise<void> {
  await page.locator('input[name="fullName"]').fill('Asha Rao');
  await page.locator('input[name="workEmail"]').fill('asha.rao@example.com');
  await page.locator('input[name="company"]').fill('Meridian Pumps');
  await page.locator('input[name="jobTitle"]').fill('Head of Supply Chain');
  await page.locator('select[name="primaryRole"]').selectOption('operations');
  await page.locator('input[name="country"]').fill('India');
  await page.locator('select[name="companySize"]').selectOption('501-2000');
  await page.getByRole('button', { name: 'Continue to Context' }).click();
}

async function fillDemoStepTwo(page: Page): Promise<void> {
  await page.getByText('Supplier Disruption', { exact: true }).click();
  await page.getByText('Spreadsheets', { exact: true }).click();
  await page
    .locator('textarea[name="decisionDescription"]')
    .fill('We need to evaluate rerouting options when a port is congested.');
  await page.locator('input[name="desiredOutcome"]').fill('Fewer stock-outs');
  await page.locator('select[name="timeline"]').selectOption('short');
  await page.locator('input[name="consent"]').check();
}

async function fillContactForm(page: Page, message: string): Promise<void> {
  await page.getByLabel('Your name').fill('Dev Mehta');
  await page.getByLabel('Email address').fill('dev.mehta@example.com');
  await page.getByLabel('Company (optional)').fill('Bharat Castings');
  await page.getByLabel('Message', { exact: true }).fill(message);
  await page.getByRole('checkbox').check();
}

test.describe('Demo request form', () => {
  test('a request is saved and the reference shown is the one the server stored', async ({ page }) => {
    await page.goto(`${BASE_URL}/demo`);
    await fillDemoStepOne(page);
    await fillDemoStepTwo(page);

    const saving = page.waitForResponse((response) => isSave(response.request()));
    await page.getByRole('button', { name: 'Submit Request' }).click();
    const response = await saving;

    expect(response.status()).toBe(201);
    const sent = response.request().postDataJSON();
    expect(sent).toMatchObject({
      topic: 'demo',
      full_name: 'Asha Rao',
      email: 'asha.rao@example.com',
      company: 'Meridian Pumps',
      message: 'We need to evaluate rerouting options when a port is congested.',
      consent: true,
      details: {
        job_title: 'Head of Supply Chain',
        primary_role: 'operations',
        country: 'India',
        company_size: '501-2000',
        challenges: ['Supplier Disruption'],
        current_systems: ['Spreadsheets'],
        desired_outcome: 'Fewer stock-outs',
        timeline: 'short',
      },
    });
    const stored = (await response.json()) as { reference: string };
    expect(stored.reference).toMatch(REFERENCE);

    await expect(page.getByTestId('demo-receipt')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Your request was received' })).toBeVisible();
    await expect(page.getByTestId('demo-reference')).toHaveText(stored.reference);
  });

  test('when saving fails the page says so, shows no reference and keeps the form', async ({ page }) => {
    await page.route(SAVE_ROUTE, (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"boom"}' }),
    );
    await page.goto(`${BASE_URL}/demo`);
    await fillDemoStepOne(page);
    await fillDemoStepTwo(page);

    await page.getByRole('button', { name: 'Submit Request' }).click();

    const error = page.getByTestId('demo-error');
    await expect(error).toBeVisible();
    await expect(error).toContainText('Your request was not saved.');
    await expect(error).not.toContainText('boom');
    await expect(page.getByTestId('demo-receipt')).toHaveCount(0);
    await expect(page.getByText('REFERENCE ID')).toHaveCount(0);
    // Nothing typed is lost, and the visitor can try again.
    await expect(page.locator('textarea[name="decisionDescription"]')).toHaveValue(
      'We need to evaluate rerouting options when a port is congested.',
    );
    await expect(page.getByRole('button', { name: 'Submit Request' })).toBeEnabled();
  });

  test('a server that is unreachable is reported, not papered over', async ({ page }) => {
    await page.route(SAVE_ROUTE, (route) => route.abort('connectionrefused'));
    await page.goto(`${BASE_URL}/demo`);
    await fillDemoStepOne(page);
    await fillDemoStepTwo(page);

    await page.getByRole('button', { name: 'Submit Request' }).click();

    await expect(page.getByTestId('demo-error')).toContainText('could not reach the server');
    await expect(page.getByTestId('demo-receipt')).toHaveCount(0);
  });

  test('nothing is sent until the required answers are given', async ({ page }) => {
    let saves = 0;
    page.on('request', (request) => {
      if (isSave(request)) saves += 1;
    });
    await page.goto(`${BASE_URL}/demo`);

    // Spaces alone are not an answer.
    await page.locator('input[name="fullName"]').fill('   ');
    await page.getByRole('button', { name: 'Continue to Context' }).click();
    await expect(page.getByRole('heading', { name: 'Applicant Information' })).toBeVisible();

    await fillDemoStepOne(page);
    await page.getByRole('button', { name: 'Submit Request' }).click();
    await expect(page.getByText('You must agree to proceed')).toBeVisible();
    expect(saves).toBe(0);
  });

  test('the privacy link leads to the privacy policy', async ({ page }) => {
    await page.goto(`${BASE_URL}/demo`);
    await expect(page.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute(
      'href',
      '/legal/privacy',
    );
  });
});

test.describe('Contact form', () => {
  test('a message is saved and the reference shown is the one the server stored', async ({ page }) => {
    await page.goto(`${BASE_URL}/contact?topic=security`);

    await expect(page.getByLabel('Topic')).toHaveValue('security');
    await expect(page.getByTestId('contact-topic-hint')).toContainText('steps to reproduce');
    await fillContactForm(page, 'The demo page reflects input without escaping it.');

    const saving = page.waitForResponse((response) => isSave(response.request()));
    await page.getByRole('button', { name: 'Send message' }).click();
    const response = await saving;

    expect(response.status()).toBe(201);
    expect(response.request().postDataJSON()).toMatchObject({
      topic: 'security',
      full_name: 'Dev Mehta',
      email: 'dev.mehta@example.com',
      company: 'Bharat Castings',
      message: 'The demo page reflects input without escaping it.',
      consent: true,
    });
    const stored = (await response.json()) as { reference: string };
    expect(stored.reference).toMatch(REFERENCE);
    await expect(page.getByTestId('contact-receipt')).toBeVisible();
    await expect(page.getByTestId('contact-reference')).toHaveText(stored.reference);
    await expect(page.getByTestId('contact-form')).toHaveCount(0);
  });

  test('each card opens the form with its topic chosen', async ({ page }) => {
    await page.goto(`${BASE_URL}/contact`);
    await expect(page.getByLabel('Topic')).toHaveValue('general');

    await page.getByRole('link', { name: 'Report a security issue' }).click();
    await expect(page).toHaveURL(/\/contact\?topic=security#write$/);
    await expect(page.getByLabel('Topic')).toHaveValue('security');

    await page.getByRole('link', { name: 'Write to sales' }).click();
    await expect(page.getByLabel('Topic')).toHaveValue('sales');

    await page.getByRole('link', { name: 'Write to engineering' }).click();
    await expect(page.getByLabel('Topic')).toHaveValue('engineering');
    await expect(page.getByRole('heading', { name: 'Write to us' })).toBeInViewport();
  });

  test('an unknown topic in the address falls back to the general topic', async ({ page }) => {
    await page.goto(`${BASE_URL}/contact?topic=%3Cscript%3E`);
    await expect(page.getByLabel('Topic')).toHaveValue('general');
    // The demo request has its own form; it is not offered here.
    await page.goto(`${BASE_URL}/contact?topic=demo`);
    await expect(page.getByLabel('Topic')).toHaveValue('general');
  });

  test('an incomplete form names what is missing and sends nothing', async ({ page }) => {
    let saves = 0;
    page.on('request', (request) => {
      if (isSave(request)) saves += 1;
    });
    await page.goto(`${BASE_URL}/contact`);

    await page.getByRole('button', { name: 'Send message' }).click();

    await expect(page.getByText('Enter your name.')).toBeVisible();
    await expect(page.getByText('Enter your email address.')).toBeVisible();
    await expect(page.getByText('Write your message.')).toBeVisible();
    await expect(page.getByText('Tick the box so we may store and answer your message.')).toBeVisible();
    await expect(page.getByLabel('Your name')).toHaveAttribute('aria-invalid', 'true');

    await page.getByLabel('Your name').fill('Dev Mehta');
    await page.getByLabel('Email address').fill('not-an-email');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByText('Enter a valid email address.')).toBeVisible();
    await expect(page.getByText('Enter your name.')).toHaveCount(0);
    expect(saves).toBe(0);
  });

  test('a failed save is reported and the message is kept', async ({ page }) => {
    await page.route(SAVE_ROUTE, (route) =>
      route.fulfill({
        status: 429,
        contentType: 'application/json',
        headers: { 'Retry-After': '3600' },
        body: '{"detail":"Rate limit exceeded"}',
      }),
    );
    await page.goto(`${BASE_URL}/contact`);
    await fillContactForm(page, 'Please call me back about a pilot.');

    await page.getByRole('button', { name: 'Send message' }).click();

    const error = page.getByTestId('contact-error');
    await expect(error).toContainText('Your request was not saved.');
    await expect(error).toContainText('try again in an hour');
    await expect(page.getByTestId('contact-receipt')).toHaveCount(0);
    await expect(page.getByLabel('Message', { exact: true })).toHaveValue('Please call me back about a pilot.');
  });

  test('a reply without a reference is not shown as a success', async ({ page }) => {
    await page.route(SAVE_ROUTE, (route) =>
      route.fulfill({ status: 201, contentType: 'application/json', body: '{}' }),
    );
    await page.goto(`${BASE_URL}/contact`);
    await fillContactForm(page, 'Hello.');

    await page.getByRole('button', { name: 'Send message' }).click();

    await expect(page.getByTestId('contact-error')).toContainText('Your request was not saved.');
    await expect(page.getByTestId('contact-receipt')).toHaveCount(0);
  });
});

test.describe('No placeholder addresses', () => {
  const pages = [
    '/contact',
    '/demo',
    '/legal',
    '/legal/privacy',
    '/legal/terms',
    '/security',
    '/security/report-vulnerability',
    '/company',
    '/',
  ];

  for (const path of pages) {
    test(`${path} offers no email address`, async ({ page }) => {
      await page.goto(`${BASE_URL}${path}`);
      await expect(page.locator('a[href^="mailto:"]')).toHaveCount(0);
      const text = await page.locator('body').innerText();
      expect(text).not.toMatch(/[\w.+-]+@[\w-]+\.(?:example\.com|test)\b/i);
      expect(text).not.toMatch(/@cortex\./i);
    });
  }

  test('security, legal and privacy pages lead to the form with the right topic', async ({ page }) => {
    await page.goto(`${BASE_URL}/security/report-vulnerability`);
    await expect(page.getByRole('link', { name: 'Report a security issue' })).toHaveAttribute(
      'href',
      '/contact?topic=security#write',
    );

    await page.goto(`${BASE_URL}/legal`);
    await expect(page.getByRole('link', { name: /Report a Vulnerability/ })).toHaveAttribute(
      'href',
      '/contact?topic=security#write',
    );

    await page.goto(`${BASE_URL}/legal/privacy`);
    const privacyLink = page.getByRole('link', { name: 'contact form' });
    await expect(privacyLink).toHaveAttribute('href', '/contact?topic=privacy#write');
    await privacyLink.click();
    await expect(page.getByLabel('Topic')).toHaveValue('privacy');
  });
});
