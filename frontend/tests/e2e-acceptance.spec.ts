import { test, expect } from '@playwright/test';

const BASE_URL = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';
const NEXUS_BACKEND_URL = process.env.NEXUS_BACKEND_URL || 'http://localhost:8000';

test.describe('Nexus Frontend ↔ Backend E2E', () => {
  test('cockpit page loads and renders', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/cockpit`);
    await page.waitForLoadState('networkidle');

    // Verify page loads with header
    await expect(page.locator('h1')).toContainText('No active incidents');

    // Verify SVG graph renders (in empty state)
    await expect(page.locator('.graph-svg').first()).toBeVisible({ timeout: 5000 });

    test.info().annotations.push({
      type: 'category: frontend',
      description: 'Cockpit page renders in offline state',
    });
  });
  });

  test('graph page loads and renders with SVG', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/graph`);
    await page.waitForLoadState('networkidle');

    // Verify page header
    await expect(page.locator('h1')).toContainText('OPERATIONAL GRAPH TOPOLOGY');

    // Verify SVG graph renders
    await expect(page.locator('.graph-svg').first()).toBeVisible({ timeout: 5000 });

    // Verify mode toggle buttons (6 overlay modes)
    const modes = ['WORLD', 'RISK', 'DEPENDENCY', 'INCIDENT', 'SCENARIO', 'EVIDENCE'];
    for (const mode of modes) {
      await expect(page.locator(`button:has-text("${mode}")`)).toBeVisible();
    }

    // Verify search input
    await expect(page.locator('input[placeholder*="Search"]')).toBeVisible();

    test.info().annotations.push({
      type: 'category: frontend',
      description: 'Graph page renders with SVG renderer and 6 overlay modes',
    });
  });

  test('agents page loads and renders', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/agents`);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('h1')).toContainText('Agent Operations Center');

    test.info().annotations.push({
      type: 'category: frontend',
      description: 'Agents page renders',
    });
  });

  test('decisions page loads and renders', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/decisions`);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('h1')).toContainText('Governed Decision Cards');

    test.info().annotations.push({
      type: 'category: frontend',
      description: 'Decisions page renders',
    });
  });

  test('products demo page renders with controlled demo', async ({ page }) => {
    await page.goto(`${BASE_URL}/products`);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('h1')).toContainText('Products');
    await expect(page.locator('h2')).toContainText('Nexus Operational Disruption Graph');
    await expect(page.locator('svg').first()).toBeVisible({ timeout: 5000 }); // SVG demo graph

    test.info().annotations.push({
      type: 'category: frontend',
      description: 'Products demo page renders controlled demo',
    });
  });

  test('all workspace pages accessible', async ({ page }) => {
    const pages = [
      { path: '/workspace/cockpit', heading: 'No active incidents' },
      { path: '/workspace/graph', heading: 'OPERATIONAL GRAPH TOPOLOGY' },
      { path: '/workspace/data', heading: 'Enterprise Data Substrate' },
      { path: '/workspace/signals', heading: 'Active Operational Signals' },
      { path: '/workspace/risk', heading: 'Operational Risk' },
      { path: '/workspace/agents', heading: 'Agent Operations Center' },
      { path: '/workspace/scenarios', heading: 'Digital Twin Scenario' },
      { path: '/workspace/decisions', heading: 'Governed Decision Cards' },
      { path: '/workspace/evidence', heading: 'Decision Evidence Graph' },
      { path: '/workspace/world', heading: 'World State Timeline' },
      { path: '/workspace/analysis', heading: 'Operational Analysis' },
    ];

    for (const p of pages) {
      await page.goto(`${BASE_URL}${p.path}`);
      await page.waitForLoadState('networkidle');
      await expect(page.locator('h1')).toContainText(p.heading);
    }

    test.info().annotations.push({
      type: 'category: frontend',
      description: 'All 11 workspace pages load and render headings',
    });
  });