import { test, expect } from '@playwright/test';

import { mockGuestWorkspaceApis } from './fixtures/lanApiMocks';

test.describe('migrated WebUI shell', () => {
  test('opens and closes the command palette from the Gallery shell', async ({ page }) => {
    await mockGuestWorkspaceApis(page);
    await page.goto('/gallery');

    await expect(page.getByRole('banner')).toBeVisible();
    await page.keyboard.press('Control+K');
    await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible();
    await expect(page.getByRole('combobox')).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: 'Command palette' })).toHaveCount(0);
  });

  test('keeps the migrated Gallery shell within a mobile viewport', async ({ page }) => {
    await mockGuestWorkspaceApis(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/gallery');
    await expect(page.getByRole('banner')).toBeVisible();

    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 5);
  });
});
