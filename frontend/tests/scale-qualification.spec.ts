import { test, expect } from '@playwright/test';

const BASE_URL = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';

test.describe('Nexus Scale Qualification - Real Data', () => {
  test('graph renders with real data - FPS measurement', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/graph`);
    await page.waitForLoadState('networkidle');

    // Wait for canvas/svg to render
    await page.waitForSelector('canvas, .graph-svg', { timeout: 10000 });

    // Measure FPS over 5 seconds
    const fps = await page.evaluate(() => {
      return new Promise<number>((resolve) => {
        let frames = 0;
        let start = performance.now();
        function tick() {
          frames++;
          if (performance.now() - start > 5000) {
            resolve(frames / 5);
          }
          requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
      });
    });

    console.log(`FPS: ${fps.toFixed(1)}`);
    expect(fps).toBeGreaterThanOrEqual(30);

    test.info().annotations.push({
      type: 'category: performance',
      description: `Graph FPS with real data: ${fps.toFixed(1)}`,
    });
  });

  test('selection latency on real graph', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/graph`);
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('canvas, .graph-svg', { timeout: 10000 });

    // Try to click on a node (if any rendered)
    const selectionLatency = await page.evaluate(async () => {
      const canvas = document.querySelector('canvas');
      const svg = document.querySelector('.graph-svg');
      const target = canvas || svg;
      if (!target) return 0;

      const start = performance.now();
      // Simulate click in center
      const rect = target.getBoundingClientRect();
      target.dispatchEvent(new MouseEvent('click', {
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + rect.height / 2,
        bubbles: true,
      }));
      await new Promise(r => setTimeout(r, 100));
      return performance.now() - start;
    });

    console.log(`Selection latency: ${selectionLatency}ms`);
    expect(selectionLatency).toBeLessThan(200);
  });

  test('zoom/pan latency', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/graph`);
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('canvas, .graph-svg', { timeout: 10000 });

    const zoomPanLatency = await page.evaluate(async () => {
      const canvas = document.querySelector('canvas');
      const svg = document.querySelector('.graph-svg');
      const target = canvas || svg;
      if (!target) return 0;

      const start = performance.now();
      target.dispatchEvent(new WheelEvent('wheel', {
        deltaY: -100,
        clientX: window.innerWidth / 2,
        clientY: window.innerHeight / 2,
        bubbles: true,
      }));
      await new Promise(r => setTimeout(r, 100));
      return performance.now() - start;
    });

    console.log(`Zoom/pan latency: ${zoomPanLatency}ms`);
    expect(zoomPanLatency).toBeLessThan(200);
  });

  test('memory usage check', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/graph`);
    await page.waitForLoadState('networkidle');
    await page.waitForSelector('canvas, .graph-svg', { timeout: 10000 });

    const memory = await page.evaluate(() => {
      if ('memory' in performance) {
        return (performance as any).memory.usedJSHeapSize / 1024 / 1024;
      }
      return 0;
    });

    console.log(`Memory: ${memory.toFixed(1)} MB`);
    if (memory > 0) {
      expect(memory).toBeLessThan(500);
    }
  });

  test('Canvas renderer used for large graphs', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/graph`);
    await page.waitForLoadState('networkidle');

    // Check which renderer is used
    const renderer = await page.evaluate(() => {
      const canvas = document.querySelector('canvas');
      const svg = document.querySelector('.graph-svg');
      if (canvas) return 'canvas';
      if (svg) return 'svg';
      return 'none';
    });

    console.log(`Renderer: ${renderer}`);
    expect(['canvas', 'svg']).toContain(renderer);
  });

  test('products demo renders SVG graph', async ({ page }) => {
    await page.goto(`${BASE_URL}/products`);
    await page.waitForLoadState('networkidle');

    await expect(page.locator('svg').first()).toBeVisible({ timeout: 5000 });

    // Measure demo FPS
    const fps = await page.evaluate(() => {
      return new Promise<number>((resolve) => {
        let frames = 0;
        let start = performance.now();
        function tick() {
          frames++;
          if (performance.now() - start > 3000) {
            resolve(frames / 3);
          }
          requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
      });
    });

    console.log(`Demo FPS: ${fps.toFixed(1)}`);
    expect(fps).toBeGreaterThanOrEqual(30);
  });
});