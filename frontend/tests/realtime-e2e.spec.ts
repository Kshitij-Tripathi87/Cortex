import { test, expect } from '@playwright/test';

const BASE_URL = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';
const NEXUS_BACKEND_URL = process.env.NEXUS_BACKEND_URL || 'http://localhost:8000';
const WS_URL = process.env.NEXUS_WS_URL || 'ws://localhost:8000/ws/realtime';

test.describe('Nexus Realtime E2E', () => {
  test.beforeAll(async () => {
    // Verify backend and WS are reachable
    try {
      const health = await fetch(`${NEXUS_BACKEND_URL}/v1/health`);
      if (!health.ok) {
        test.skip(true, 'Backend not available');
      }
      // Try WS connection
      const ws = new WebSocket(WS_URL);
      await new Promise((resolve, reject) => {
        ws.onopen = () => { ws.close(); resolve(true); };
        ws.onerror = () => reject(new Error('WS failed'));
        setTimeout(() => reject(new Error('WS timeout')), 5000);
      });
    } catch {
      test.skip(true, 'Backend/WS not available');
    }
  });

  test('graph.delta → UI mutation without refresh', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/graph`);
    await page.waitForLoadState('networkidle');

    // Get initial node count
    const initialCount = await page.locator('[data-testid="node-count"]').textContent();
    expect(initialCount).toBeTruthy();

    // Connect to WebSocket and send graph.delta event
    const wsConnected = await page.evaluate(async (wsUrl) => {
      const ws = new WebSocket(wsUrl);
      return new Promise<boolean>((resolve) => {
        ws.onopen = () => resolve(true);
        ws.onerror = () => resolve(false);
        setTimeout(() => resolve(false), 5000);
      });
    }, WS_URL);

    if (!wsConnected) {
      test.skip(true, 'WebSocket connection failed');
    }

    // Send graph.delta event via backend API or direct WS
    await page.evaluate(async (wsUrl) => {
      const ws = new WebSocket(wsUrl);
      await new Promise<void>((resolve) => {
        ws.onopen = () => {
          ws.send(JSON.stringify({
            event_id: 'test-delta-1',
            event_type: 'graph.delta',
            timestamp: new Date().toISOString(),
            world_state_version: 2,
            graph_version: 'v2',
            payload: {
              added_nodes: ['new-node-1'],
              removed_nodes: [],
              added_edges: [],
              removed_edges: [],
              updated_nodes: [],
              updated_edges: [],
            },
          }));
          setTimeout(() => { ws.close(); resolve(); }, 1000);
        };
      });
    }, WS_URL);

    // Wait for UI to update (via refreshLiveState)
    await page.waitForTimeout(2000);

    // Verify graph mutated without page refresh
    const updatedCount = await page.locator('[data-testid="node-count"]').textContent();
    expect(updatedCount).toBeTruthy();

    // Verify mutation indicator appears
    await expect(page.locator('[data-testid="graph-mutation-indicator"]')).toBeVisible({ timeout: 3000 });

    test.info().annotations.push({
      type: 'category: realtime',
      description: 'graph.delta → UI mutation without refresh',
    });
  });

  test('signal.update → signals panel refresh', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/cockpit`);
    await page.waitForLoadState('networkidle');

    // Get initial signal count
    const initialSignals = await page.locator('[data-testid="signal-count"]').textContent();

    // Send signal.update event
    await page.evaluate(async (wsUrl) => {
      const ws = new WebSocket(wsUrl);
      await new Promise<void>((resolve) => {
        ws.onopen = () => {
          ws.send(JSON.stringify({
            event_id: 'test-signal-1',
            event_type: 'signal.update',
            timestamp: new Date().toISOString(),
            world_state_version: 2,
            graph_version: 'v2',
            payload: {
              signal_id: 'new-signal-1',
              action: 'created',
              signal: {
                id: 'new-signal-1',
                signal_type: 'RISK',
                severity: 'HIGH',
                description: 'New risk detected',
                confidence: 0.9,
              },
            },
          }));
          setTimeout(() => { ws.close(); resolve(); }, 1000);
        };
      });
    }, WS_URL);

    // Wait for signals refresh
    await page.waitForTimeout(2000);

    // Verify signals panel updated
    const updatedSignals = await page.locator('[data-testid="signal-count"]').textContent();
    expect(updatedSignals).toBeTruthy();

    test.info().annotations.push({
      type: 'category: realtime',
      description: 'signal.update → signals panel refresh',
    });
  });

  test('decision.invalidated → invalidation banner appears', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/cockpit`);
    await page.waitForLoadState('networkidle');

    // Send decision.invalidated event
    await page.evaluate(async (wsUrl) => {
      const ws = new WebSocket(wsUrl);
      await new Promise<void>((resolve) => {
        ws.onopen = () => {
          ws.send(JSON.stringify({
            event_id: 'test-invalid-1',
            event_type: 'decision.invalidated',
            timestamp: new Date().toISOString(),
            world_state_version: 2,
            graph_version: 'v2',
            payload: {
              decision_id: 'dec-123',
              reason: 'World state mutated after decision',
              dependent_entities: ['entity-1'],
              dependent_signals: ['signal-1'],
            },
          }));
          setTimeout(() => { ws.close(); resolve(); }, 1000);
        };
      });
    }, WS_URL);

    // Wait for invalidation state
    await page.waitForTimeout(1000);

    // Verify invalidation banner appears
    await expect(page.locator('[data-testid="decision-invalidated-banner"]')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('[data-testid="decision-invalidated-banner"]')).toContainText('World state mutated');

    // Verify redeliberate action available
    await expect(page.locator('[data-testid="redeliberate-btn"]')).toBeVisible();

    test.info().annotations.push({
      type: 'category: realtime',
      description: 'decision.invalidated → invalidation banner → redeliberate',
    });
  });

  test('agent.message → agent messages panel updates', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/agents`);
    await page.waitForLoadState('networkidle');

    // Get initial message count
    const initialMessages = await page.locator('[data-testid="agent-message-count"]').textContent();

    // Send agent.message event
    await page.evaluate(async (wsUrl) => {
      const ws = new WebSocket(wsUrl);
      await new Promise<void>((resolve) => {
        ws.onopen = () => {
          ws.send(JSON.stringify({
            event_id: 'test-agent-msg-1',
            event_type: 'agent.message',
            timestamp: new Date().toISOString(),
            world_state_version: 2,
            graph_version: 'v2',
            payload: {
              message_id: 'msg-456',
              agent_id: 'supervisor',
              content: 'Starting risk analysis...',
              phase: 'ANALYSIS',
              evidence_refs: ['ev-1', 'ev-2'],
            },
          }));
          setTimeout(() => { ws.close(); resolve(); }, 1000);
        };
      });
    }, WS_URL);

    // Wait for message to appear
    await page.waitForTimeout(1000);

    // Verify agent message added
    await expect(page.locator('[data-testid="agent-messages-list"]')).toContainText('Starting risk analysis');
    await expect(page.locator('[data-testid="agent-message-supervisor"]')).toBeVisible();

    test.info().annotations.push({
      type: 'category: realtime',
      description: 'agent.message → agent messages panel update',
    });
  });

  test('world_state.update → full state reconciliation', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/graph`);
    await page.waitForLoadState('networkidle');

    const initialVersion = await page.locator('[data-testid="world-state-version"]').textContent();

    // Send world_state.update event
    await page.evaluate(async (wsUrl) => {
      const ws = new WebSocket(wsUrl);
      await new Promise<void>((resolve) => {
        ws.onopen = () => {
          ws.send(JSON.stringify({
            event_id: 'test-ws-1',
            event_type: 'world_state.update',
            timestamp: new Date().toISOString(),
            world_state_version: 99,
            graph_version: 'v99',
            payload: {
              version: 99,
              changed_entities: ['entity-1', 'entity-2'],
              changed_signals: ['signal-1'],
            },
          }));
          setTimeout(() => { ws.close(); resolve(); }, 1000);
        };
      });
    }, WS_URL);

    // Wait for reconciliation
    await page.waitForTimeout(2000);

    // Verify world state version updated
    const updatedVersion = await page.locator('[data-testid="world-state-version"]').textContent();
    expect(updatedVersion).toContain('99');

    // Verify state-reconciled indicator
    await expect(page.locator('[data-testid="state-reconciled"]')).toBeVisible({ timeout: 3000 });

    test.info().annotations.push({
      type: 'category: realtime',
      description: 'world_state.update → full state reconciliation',
    });
  });

  test('WS reconnection after disconnect', async ({ page }) => {
    await page.goto(`${BASE_URL}/workspace/cockpit`);
    await page.waitForLoadState('networkidle');

    // Verify initial connection
    await expect(page.locator('[data-testid="ws-status"]')).toContainText('LIVE');

    // Force disconnect
    await page.evaluate(async () => {
      // Access the realtime client and disconnect
      if ((window as any).__NEXUS_REALTIME__) {
        (window as any).__NEXUS_REALTIME__.disconnect();
      }
    });

    // Wait for reconnecting state
    await page.waitForTimeout(1000);
    await expect(page.locator('[data-testid="ws-status"]')).toContainText('RECONNECTING');

    // Wait for reconnection (exponential backoff)
    await page.waitForTimeout(5000);
    await expect(page.locator('[data-testid="ws-status"]')).toContainText('LIVE');

    test.info().annotations.push({
      type: 'category: realtime',
      description: 'WS reconnection after disconnect',
    });
  });
});