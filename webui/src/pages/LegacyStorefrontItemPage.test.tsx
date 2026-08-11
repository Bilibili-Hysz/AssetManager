// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LegacyStorefrontItemPage from './LegacyStorefrontItemPage';

const { getProjectDetail, list, createOrder } = vi.hoisted(() => ({ getProjectDetail: vi.fn(), list: vi.fn(), createOrder: vi.fn() }));
const api = {};
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../api/metadata', () => ({ createMetadataApi: () => ({ getProjectDetail }) }));
vi.mock('../api/shop', () => ({ createShopApi: () => ({ list, createOrder }) }));
vi.mock('../components/storefront/StorefrontShell', () => ({ StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('../components/viewer/ImageViewer', () => ({ ImageViewer: () => null }));

const detail = { name: 'Reference project', path: 'folder/Reference project', tags: ['featured'], notes: 'Useful notes', urls: ['https://example.com'], total_size: 10, total_size_fmt: '10 B', file_count: 1, files: [], images: [{ name: 'cover', url: '/cover.jpg', thumb_url: '/cover-thumb.jpg' }], thumbnail_url: '/thumb.jpg', modified: 0, download_url: '/api/download/project' };

describe('LegacyStorefrontItemPage', () => {
  beforeEach(() => {
    getProjectDetail.mockReset().mockResolvedValue(detail);
    list.mockReset().mockResolvedValue({ items: [{ id: 7, path: detail.path, title: 'Buy this', description: '', price_cents: 1200, currency: 'USD', cover_path: '', enabled: true, metadata: {}, status: 'active', created_at: 0, updated_at: 0 }] });
    createOrder.mockReset().mockResolvedValue({ order: { id: 42 } });
  });
  afterEach(() => cleanup());

  it('resolves the exact library path and only offers the matching active shop item', async () => {
    render(<MemoryRouter initialEntries={['/store/folder/Reference%20project']}><Routes><Route path="/store/*" element={<LegacyStorefrontItemPage />} /><Route path="/storefront/checkout/:orderId" element={<div />} /></Routes></MemoryRouter>);
    await waitFor(() => expect(getProjectDetail).toHaveBeenCalledWith(detail.path, expect.any(AbortSignal)));
    expect(await screen.findByRole('heading', { name: 'Reference project' })).toBeDefined();
    expect(screen.getByRole('link', { name: 'View Details' })).toBeDefined();
    expect(screen.getByRole('button', { name: /Buy now/ })).toBeDefined();
    expect(screen.queryByText(/token/i)).toBeNull();
  });

  it('does not show an order action when the active shop path is not exact', async () => {
    list.mockResolvedValueOnce({ items: [{ path: 'folder/Reference project/child', enabled: true, status: 'active', id: 8, title: 'Wrong path', price_cents: 1, currency: 'USD', description: '', cover_path: '', metadata: {}, created_at: 0, updated_at: 0 }] });
    render(<MemoryRouter initialEntries={['/store/folder/Reference%20project']}><Routes><Route path="/store/*" element={<LegacyStorefrontItemPage />} /><Route path="/storefront/checkout/:orderId" element={<div />} /></Routes></MemoryRouter>);
    await screen.findByRole('heading', { name: 'Reference project' });
    expect(screen.queryByRole('button', { name: /Buy now/ })).toBeNull();
    expect(screen.getByRole('link', { name: /Download/ })).toBeDefined();
  });

  it('starts an order through the shop API instead of exposing delivery data', async () => {
    render(<MemoryRouter initialEntries={['/store/folder/Reference%20project']}><Routes><Route path="/store/*" element={<LegacyStorefrontItemPage />} /><Route path="/storefront/checkout/:orderId" element={<div />} /></Routes></MemoryRouter>);
    const button = await screen.findByRole('button', { name: /Buy now/ });
    fireEvent.click(button);
    await waitFor(() => expect(createOrder).toHaveBeenCalledWith(7));
    expect(screen.queryByText(/delivery|token/i)).toBeNull();
  });
});




