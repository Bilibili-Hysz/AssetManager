import { test, expect, type Page } from '@playwright/test';

async function mockPublicGalleryApis(page: Page) {
  await page.route('**/api/info', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      version: 'test',
      share_name: 'Test Library',
      library_root: '/library',
      auth_enabled: false,
      auth_mode: 'none',
      theme_color: '#6366f1',
      welcome_msg: '',
      footer_text: '',
      library_stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' },
      principal: {
        kind: 'guest',
        authenticated: false,
        role: 'guest',
        display_name: 'Guest',
        capabilities: {
          browse: true,
          preview: true,
          download: true,
          upload: false,
          manage_links: false,
          manage_users: false,
          settings: false,
          realtime: false,
        },
      },
    }),
  }));
  await page.route('**/api/gallery/home', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      featured: null,
      collections: [],
      projects: [],
      recent: [],
      stats: { collections: 0, projects: 0, artworks: 0, total_size_fmt: '0 B' },
    }),
  }));
  await page.route('**/api/favorites', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ favorites: [] }),
  }));
}

test.describe('migrated WebUI shell', () => {
  test('opens and closes the command palette from the Gallery shell', async ({ page }) => {
    await mockPublicGalleryApis(page);
    await page.goto('/gallery');

    await expect(page.getByRole('banner')).toBeVisible();
    await page.keyboard.press('Control+K');
    await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible();
    await expect(page.getByRole('combobox')).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: 'Command palette' })).toHaveCount(0);
  });

  test('keeps the migrated Gallery shell within a mobile viewport', async ({ page }) => {
    await mockPublicGalleryApis(page);
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
