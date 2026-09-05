import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * Automated WCAG 2.1 AA gate: every route below renders against mocked APIs
 * (same pattern as webui-shell.spec.ts) and must produce zero axe-core
 * violations for the A/AA rule tags. Fixes to flagged issues belong in the
 * source, not in this file — the curated tag set is the contract.
 */

// D10 (2026-09-04): the row count is derived from the registry instead of a
// hardcoded number — the dialog is a pure projection of registry.ts, so any
// registry edit is automatically covered here (the count assertion only guards
// against the projection losing rows, which is all it can meaningfully check).
import { mockGuestWorkspaceApis } from './fixtures/lanApiMocks';
import { SHORTCUTS } from '../src/shortcuts/registry';

const ROUTES = [
  '/',
  '/login',
  '/browse',
  '/gallery',
  '/gallery/collection',
  '/gallery/favorites',
  '/detail?path=asset.png',
];

/** Wait for the React shell, then one bounded task-turn for lazy effects. */
async function settleApp(page: Page) {
  await page.waitForFunction(() => (document.querySelector('#root')?.childElementCount ?? 0) > 0);
  // Mocked APIs resolve in microtasks; give effects one extra turn to commit
  // route-level lazy content before the scan.
  await page.waitForTimeout(300);
}

async function expectCleanScan(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(
    results.violations.map(v => ({
      id: v.id, impact: v.impact, help: v.help,
      nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })),
    })),
    `axe violations on ${label}`,
  ).toEqual([]);
}

for (const route of ROUTES) {
  for (const theme of ['dark', 'light'] as const) {
    test(`axe scan is clean: ${route} (${theme})`, async ({ page }) => {
      await mockGuestWorkspaceApis(page, { authEnabled: route === '/login' });
      await page.addInitScript(value => localStorage.setItem('am_theme', value), theme);
      await page.goto(route);
      await settleApp(page);
      await expectCleanScan(page, `${route} (${theme})`);
    });
  }
}

// Interaction states the initial-render scans cannot see. Keep this list
// deliberately short: every entry needs an interaction step and must be
// deterministic in the mocked-app environment.
test('axe scan is clean: tuning panel open (dark)', async ({ page }) => {
  await mockGuestWorkspaceApis(page);
  await page.addInitScript(value => localStorage.setItem('am_theme', value), 'dark');
  await page.goto('/');
  await settleApp(page);
  await page.getByRole('button', { name: 'Background tuning' }).click();
  await expect(page.getByRole('dialog', { name: 'Background tuning' })).toBeVisible();
  await expectCleanScan(page, 'tuning panel open (dark)');
});

test('axe scan is clean: language menu open (dark)', async ({ page }) => {
  await mockGuestWorkspaceApis(page);
  await page.addInitScript(value => localStorage.setItem('am_theme', value), 'dark');
  await page.goto('/browse');
  await settleApp(page);
  await page.getByRole('button', { name: 'Language' }).click();
  await expect(page.getByRole('menu')).toBeVisible();
  await expectCleanScan(page, 'language menu open (dark)');
});

test('axe scan is clean: command palette open (dark)', async ({ page }) => {
  await mockGuestWorkspaceApis(page);
  await page.addInitScript(value => localStorage.setItem('am_theme', value), 'dark');
  await page.goto('/gallery');
  await settleApp(page);
  await page.keyboard.press('Control+K');
  await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible();
  await expectCleanScan(page, 'command palette open (dark)');
});

// Shortcut cheat sheet (?): a Modal-surface dialog rendered from the
// shortcuts registry — the second interactive Modal state the gate covers.
test('axe scan is clean: shortcuts overlay open (dark)', async ({ page }) => {
  await mockGuestWorkspaceApis(page);
  await page.addInitScript(value => localStorage.setItem('am_theme', value), 'dark');
  await page.goto('/browse');
  await settleApp(page);
  await page.keyboard.press('?');
  const dialog = page.getByRole('dialog', { name: 'Keyboard shortcuts' });
  await expect(dialog).toBeVisible();
  // The dialog is a projection of webui/src/shortcuts/registry.ts: every
  // entry renders as a row (key labels + localized description).
  await expect(dialog.getByTestId('shortcuts-row')).toHaveCount(SHORTCUTS.length);
  await expectCleanScan(page, 'shortcuts overlay open (dark)');
  // ? toggles: pressing it again closes the overlay.
  await page.keyboard.press('?');
  await expect(dialog).toBeHidden();
});

// Modal open state: ShareDialog is the cheapest Modal.tsx surface to reach
// with the guest mocks (browse list → context menu → Share). Route-level
// scans cannot see a dialog, which is exactly how the transparent modal
// scrim (undefined --color-overlay token) previously slipped through.
test('axe scan is clean: share dialog open (dark)', async ({ page }) => {
  await mockGuestWorkspaceApis(page);
  // One file row so the context menu has a target; list view keeps the row
  // layout deterministic across viewport sizes. (Route installed after the
  // shared fixture set, so this later route wins over its empty files.)
  await page.route('**/api/files**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      current_path: 'assets',
      items: [{
        name: 'asset.png', path: 'assets/asset.png', type: 'file', size: 1024,
        size_fmt: '1 KB', modified: 0, extension: '.png', category: 'image', is_project: false,
      }],
    }),
  }));
  await page.addInitScript(value => localStorage.setItem('am_view', value), 'list');
  await page.addInitScript(value => localStorage.setItem('am_theme', value), 'dark');
  await page.goto('/browse');
  await settleApp(page);
  await page.getByText('asset.png').first().click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Share' }).click();
  await expect(page.getByRole('dialog', { name: 'Create Share Link' })).toBeVisible();
  await expectCleanScan(page, 'share dialog open (dark)');

  // Regression guard for the transparent-scrim bug: the Modal overlay element
  // (the dialog's fixed parent) must paint an actual background color.
  const overlayBackground = await page.evaluate(() => {
    const overlay = document.querySelector('[role="dialog"]')?.parentElement;
    return overlay ? getComputedStyle(overlay).backgroundColor : null;
  });
  expect(overlayBackground, 'modal overlay element not found').toBeTruthy();
  expect(
    overlayBackground === 'transparent' || overlayBackground === 'rgba(0, 0, 0, 0)',
    `modal overlay background is transparent: ${overlayBackground}`,
  ).toBe(false);
});
