import { test, expect } from '@playwright/test';

const BASE_URL = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';
const DESKTOP_VIEWPORT = { width: 1440, height: 900 };
const TABLET_VIEWPORT = { width: 768, height: 1024 };
const MOBILE_VIEWPORT = { width: 375, height: 667 };

const WORKSPACE_PAGES = [
  '/products',
  '/workspace/cockpit',
  '/workspace/graph',
  '/workspace/data',
  '/workspace/signals',
  '/workspace/risk',
  '/workspace/agents',
  '/workspace/scenarios',
  '/workspace/decisions',
  '/workspace/evidence',
];

test.describe('Nexus Visual Regression', () => {

  WORKSPACE_PAGES.forEach((pagePath) => {
    test(`${pagePath} @ desktop`, async ({ page }, testInfo) => {
      await page.goto(pagePath, { waitUntil: 'networkidle' });
      await page.setViewportSize(DESKTOP_VIEWPORT);
      await expect(page).toHaveScreenshot(
        `${pagePath.replace('/', '-')}-desktop.png`,
        { fullPage: true }
      );
    });

    test(`${pagePath} @ tablet`, async ({ page }) => {
      await page.goto(pagePath, { waitUntil: 'networkidle' });
      await page.setViewportSize(TABLET_VIEWPORT);
      await expect(page).toHaveScreenshot(
        `${pagePath.replace('/', '-')}-tablet.png`,
        { fullPage: true }
      );
    });

    test(`${pagePath} @ mobile`, async ({ page }) => {
      await page.goto(pagePath, { waitUntil: 'networkidle' });
      await page.setViewportSize(MOBILE_VIEWPORT);
      await expect(page).toHaveScreenshot(
        `${pagePath.replace('/', '-')}-mobile.png`,
        { fullPage: true }
      );
    });
  });
});