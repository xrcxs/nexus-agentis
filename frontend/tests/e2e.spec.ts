import { test, expect } from '@playwright/test';

test('full happy path: launch research run -> pause at human gate -> verify ledger -> approve -> view report', async ({
  page,
}) => {
  await page.goto('/');
  await expect(page.getByText('NEXUS // AGENTIS')).toBeVisible();

  const questionInput = page.getByTestId('question-input');
  await questionInput.fill(
    'How do speculative decoding algorithms accelerate autoregressive LLM inference while preserving exact output distribution?',
  );

  await page.getByTestId('launch-run-btn').click();

  // Wait for run to reach human_gate interrupt
  const humanGate = page.getByTestId('human-gate-panel');
  await expect(humanGate).toBeVisible({ timeout: 30_000 });

  // Verify ledger chain integrity
  await page.getByTestId('verify-ledger-btn').click();
  await expect(page.getByTestId('ledger-verify-banner')).toContainText(
    'CHAIN INTEGRITY VERIFIED',
  );

  // Approve run at human gate
  await page.getByTestId('approve-run-btn').click();

  // Verify finalized Markdown report appears
  const reportViewer = page.getByTestId('report-viewer');
  await expect(reportViewer).toBeVisible({ timeout: 20_000 });
  await expect(reportViewer).toContainText('# NEXUS//AGENTIS Verified Research Report');
});
