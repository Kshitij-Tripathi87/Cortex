/**
 * Decision-1 — Decision Room frontend E2E (P0: Decision Room frontend).
 *
 * Proves the page is a READ-ONLY projection of the durable runtime:
 *   operator   → sees the pending decision + the approve action
 *   viewer     → sees the decision but cannot approve (read-only note)
 *   operator   → approves → UI reflects execution/outcome (re-derived
 *                from a fresh projection read, never client-side state)
 *   backend 5xx→ surfaces an error state, never a blank page
 *
 * Backend responses are intercepted (context.route) so this spec runs
 * without a live stack; the real-PostgreSQL Golden Path E2E is the
 * separate launch gate.
 */

import { test, expect, type Page } from '@playwright/test';

const BASE_URL = process.env.NEXT_PUBLIC_BASE_URL || 'http://localhost:3000';
const TASK_ID = 't-golden-001';
const WORKSPACE_ID = 'ws-golden-001';

function meResponse(role: string) {
  return {
    user: {
      id: 'u-operator-1',
      email: `${role}@example.com`,
      full_name: 'E2E Tester',
      role,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      last_login_at: null,
    },
    workspace: { id: WORKSPACE_ID, name: 'Golden WS', slug: 'golden-ws' },
    organization: null,
  };
}

function envelope(data: unknown) {
  return { request_id: 'req-e2e', correlation_id: null, timestamp: '2026-09-20T00:00:00Z', data };
}

function awaitingView() {
  return {
    task: {
      task_id: TASK_ID,
      trace_id: 'tr-golden-001',
      status: 'AWAITING_APPROVAL',
      objective: 'Assess inventory exposure and adjust stock for SKU comp_042.',
      world_state_version: 1,
      budget: 100,
      deadline: null,
      requires_approval: true,
    },
    pending_decision: {
      awaited_since: '2026-09-20T00:00:00+00:00',
      reason: 'Task plan requires consequential governance.',
      approval_required_for: ['world.inventory.adjust'],
      consequential_proposals: [],
      evidence_refs: ['world-state:wh-prod-main:v1:inventory.warehouse.comp_042.wh_001'],
    },
    recommendation: {
      statement: 'Adjust stock for SKU comp_042 after the supply disruption.',
      evidence_refs: ['world-state:wh-prod-main:v1:inventory.warehouse.comp_042.wh_001'],
      confidence: 0.9,
      source: 'proposal',
    },
    plan: {
      task_id: TASK_ID,
      objective: 'Assess inventory exposure and adjust stock for SKU comp_042.',
      steps: [
        {
          step_id: 'world.inventory.read',
          title: 'Read authoritative inventory levels',
          agent_role: 'INVENTORY',
          dependencies: [],
          required_capabilities: ['world.inventory.read'],
          expected_outputs: [],
        },
      ],
      assumptions: [],
    },
    runs: [],
    steps: [],
    invocations: [
      {
        invocation_id: 'inv-1',
        step_id: 'world.inventory.read',
        capability_id: 'world.inventory.read',
        capability_version: '1.0.0',
        status: 'SUCCESS',
        side_effect: 'READ',
        world_state_version: 1,
        arguments_sha256: 'a'.repeat(64),
        evidence_refs: ['world-state:wh-prod-main:v1:inventory.warehouse.comp_042.wh_001'],
        error: null,
        authorization: { allowed: true, policy_id: 'p-workspace-scope', reason: 'Allowed' },
      },
    ],
    evidence: [
      { ref: 'world-state:wh-prod-main:v1:inventory.warehouse.comp_042.wh_001', source_invocation_id: 'inv-1', payload_digest: null },
    ],
    proposals: [
      {
        agent_id: 'synthesis-1',
        agent_role: 'Nexus Supervisor',
        statement: 'Adjust stock for SKU comp_042 after the supply disruption.',
        actions: [{ capability_id: 'world.inventory.adjust', quantity_change: -150 }],
        evidence_refs: ['world-state:wh-prod-main:v1:inventory.warehouse.comp_042.wh_001'],
        confidence: 0.9,
        assumptions: [],
      },
    ],
    policy_results: [
      {
        capability_id: 'world.inventory.read',
        capability_version: '1.0.0',
        status: 'SUCCESS',
        error: null,
        allowed: true,
        policy_id: 'p-workspace-scope',
        reason: 'Allowed',
      },
    ],
    approvals: [
      { decision: 'REQUESTED', approver_id: null, reason: 'Task plan requires consequential governance.', decided_at: '2026-09-20T00:00:00+00:00' },
    ],
    execution: null,
    outcome: null,
    consequential_capabilities: [],
  };
}

function completedView() {
  const view = awaitingView();
  return {
    ...view,
    task: { ...view.task, status: 'COMPLETED', world_state_version: 2 },
    pending_decision: null,
    approvals: [
      ...view.approvals,
      { decision: 'APPROVED', approver_id: 'u-operator-1', reason: 'reviewed', decided_at: '2026-09-20T00:01:00+00:00' },
    ],
    invocations: [
      ...view.invocations,
      {
        invocation_id: 'inv-2',
        step_id: 'world.inventory.adjust',
        capability_id: 'world.inventory.adjust',
        capability_version: '1.0.0',
        status: 'SUCCESS',
        side_effect: 'WRITE_CONSEQUENTIAL',
        world_state_version: 2,
        arguments_sha256: 'b'.repeat(64),
        evidence_refs: ['world-state:wh-prod-main:v2:inventory.warehouse.comp_042.wh_001'],
        error: null,
        authorization: { allowed: true, policy_id: 'p-workspace-scope', reason: 'Allowed' },
      },
    ],
    execution: {
      execution_id: 'exec-1',
      status: 'SUCCEEDED',
      attempts: 1,
      idempotency_key: `execute:${TASK_ID}`,
      failure_reason: null,
    },
    outcome: {
      status: 'COMPLETED',
      recommendation: null,
      result_payload: { executed_via: `execute:${TASK_ID}`, attempts: 1, failure_reason: null },
      completed_at: '2026-09-20T00:02:00+00:00',
    },
  };
}

async function seedSession(page: Page, role: string): Promise<void> {
  // The token is opaque to the frontend: identity comes from GET /auth/me
  // (intercepted here), never from client-side claims.
  await page.addInitScript(() => {
    window.localStorage.setItem('cortex:access_token', 'e2e-session-token');
  });
  await page.context().route('**/api/v1/auth/me', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(meResponse(role)) })
  );
}

test.describe('Decision Room — read-only projection', () => {
  test.beforeEach(async ({ context }) => {
    // Catch-all registered FIRST so the specific routes below win.
    await context.route('**/api/v1/**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
    );
  });

  test('operator sees the pending decision and the approve action', async ({ page }) => {
    await seedSession(page, 'operator');
    await page.context().route(`**/api/v1/nexus/tasks/${TASK_ID}/decision-room**`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(envelope({ decision_room: awaitingView() })),
      })
    );

    await page.goto(`${BASE_URL}/workspace/agents/decision-room?task_id=${TASK_ID}`);

    const task = page.getByTestId('decision-room-task');
    await expect(task).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('task-status-badge')).toHaveText('AWAITING_APPROVAL');
    await expect(task).toContainText('Assess inventory exposure and adjust stock for SKU comp_042.');

    const pending = page.getByTestId('decision-room-pending');
    await expect(pending).toBeVisible();
    await expect(pending).toContainText('world.inventory.adjust');
    // Only the operator/admin sees the server-enforced action.
    await expect(page.getByTestId('decision-approve')).toBeVisible();
    await expect(page.getByTestId('decision-reject')).toBeVisible();

    // Projection renders the durable plan, invocations, evidence.
    await expect(page.getByTestId('decision-room-plan')).toBeVisible();
    await expect(page.getByTestId('decision-room-invocations')).toContainText('world.inventory.read');
    await expect(page.getByTestId('decision-room-evidence')).toContainText(
      'world-state:wh-prod-main:v1:inventory.warehouse.comp_042.wh_001'
    );
  });

  test('viewer sees the decision but cannot approve', async ({ page }) => {
    await seedSession(page, 'viewer');
    await page.context().route(`**/api/v1/nexus/tasks/${TASK_ID}/decision-room**`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(envelope({ decision_room: awaitingView() })),
      })
    );

    await page.goto(`${BASE_URL}/workspace/agents/decision-room?task_id=${TASK_ID}`);

    await expect(page.getByTestId('decision-room-pending')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('decision-approve')).toHaveCount(0);
    await expect(page.getByTestId('decision-reject')).toHaveCount(0);
    await expect(page.getByTestId('decision-room-pending')).toContainText(
      'Read-only: your role can review this decision, but approval is an operator action.'
    );
  });

  test('operator approves and the UI reflects execution/outcome', async ({ page }) => {
    await seedSession(page, 'operator');

    // First projection read: awaiting approval. After the server-enforced
    // approval, the page refetches and the durable projection shows the
    // governed write, execution, and outcome — the UI never invents state.
    let reads = 0;
    await page.context().route(`**/api/v1/nexus/tasks/${TASK_ID}/decision-room**`, (route) => {
      reads += 1;
      const body = reads === 1 ? awaitingView() : completedView();
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(envelope({ decision_room: body })),
      });
    });
    await page.context().route(`**/api/v1/nexus/tasks/${TASK_ID}/approvals`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(envelope({ task_id: TASK_ID, status: 'APPROVED', approved: true })),
      })
    );

    await page.goto(`${BASE_URL}/workspace/agents/decision-room?task_id=${TASK_ID}`);
    await expect(page.getByTestId('decision-approve')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('decision-approve').click();

    // UI state is re-derived from the fresh projection read.
    await expect(page.getByTestId('decision-room-outcome')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('decision-room-outcome')).toContainText('COMPLETED');
    await expect(page.getByTestId('decision-room-execution')).toBeVisible();
    await expect(page.getByTestId('decision-room-execution')).toContainText('SUCCEEDED');
    await expect(page.getByTestId('task-status-badge')).toHaveText('COMPLETED');
    // The approval trail pins the approver identity from the durable record.
    await expect(page.getByTestId('decision-room-approvals')).toContainText('u-operator-1');
  });

  test('backend 5xx surfaces an error state, never a blank page', async ({ page }) => {
    await seedSession(page, 'operator');
    await page.context().route(`**/api/v1/nexus/tasks/${TASK_ID}/decision-room**`, (route) =>
      route.fulfill({ status: 500, body: 'backend error' })
    );

    await page.goto(`${BASE_URL}/workspace/agents/decision-room?task_id=${TASK_ID}`);
    await expect(page.getByTestId('decision-room-error')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('main, header, body').first()).toBeVisible();
  });

  test('no task selected shows honest guidance, no fixture data', async ({ page }) => {
    await seedSession(page, 'operator');
    await page.goto(`${BASE_URL}/workspace/agents/decision-room`);
    await expect(page.getByText('No task selected.')).toBeVisible({ timeout: 10_000 });
    // The old hardcoded deliberation fixtures must not render.
    await expect(page.getByText('CTDE Protocol')).toHaveCount(0);
  });
});
