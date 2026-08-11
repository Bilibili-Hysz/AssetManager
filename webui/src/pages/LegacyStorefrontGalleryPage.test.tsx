// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LegacyStorefrontGalleryPage from './LegacyStorefrontGalleryPage';

const { search } = vi.hoisted(() => ({ search: vi.fn() }));
const api = {};
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../api/metadata', () => ({ createMetadataApi: () => ({ search }) }));
vi.mock('../components/storefront/StorefrontShell', () => ({ StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

const result = { name: 'Reference project', path: 'folder/Reference project', type: 'dir', extension: '', category: 'project', thumbnail_url: '/thumb.jpg' };

describe('LegacyStorefrontGalleryPage', () => {
  beforeEach(() => {
    search.mockReset();
    search.mockResolvedValue({ results: [result], count: 1 });
  });
  afterEach(() => cleanup());

  it('uses metadata tag search and renders library assets without a commerce redirect', async () => {
    render(<MemoryRouter initialEntries={['/store/gallery/featured']}><Routes><Route path="/store/gallery/:tag" element={<LegacyStorefrontGalleryPage />} /></Routes></MemoryRouter>);
    await waitFor(() => expect(search).toHaveBeenCalledWith('', 'featured', undefined, expect.any(AbortSignal)));
    expect((await screen.findByRole('link', { name: 'Reference project' })).getAttribute('href')).toBe('/store/folder/Reference%20project');
    expect(screen.getByText('Browse the visual side of your asset library.')).toBeDefined();
  });
});


