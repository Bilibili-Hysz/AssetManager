// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { StorefrontProduct } from './types';

vi.mock('../../hooks/useI18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

import { ProductCard } from './ProductCard';

const product: StorefrontProduct = {
  id: '7', slug: 'packs/hero.zip', name: 'Hero Pack', description: 'A hero pack',
  imageUrl: '/api/thumbnails/packs/hero.png', gallery: [], category: 'Packs', tags: [],
  price: 12.5, currency: 'CNY', downloads: 34, featured: true, status: 'active',
};

describe('ProductCard', () => {
  afterEach(() => cleanup());

  it('renders name, price, category, and downloads', () => {
    render(<MemoryRouter><ProductCard product={product} /></MemoryRouter>);
    expect(screen.getByText('Hero Pack')).toBeDefined();
    expect(screen.getByText('Packs')).toBeDefined();
    // formatMoney uses Intl currency formatting (e.g. ¥12.50 for CNY).
    expect(screen.getByText(/12\.50/)).toBeDefined();
    expect(screen.getByText('34')).toBeDefined();
    expect(screen.getByText('commerce.featured')).toBeDefined();
  });

  it('renders a free badge for zero-price products', () => {
    render(<MemoryRouter><ProductCard product={{ ...product, price: 0 }} /></MemoryRouter>);
    expect(screen.getByText('commerce.free')).toBeDefined();
  });

  it('previews when a handler is provided instead of navigating', () => {
    const onPreview = vi.fn();
    render(<MemoryRouter><ProductCard product={product} onPreview={onPreview} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'commerce.preview Hero Pack' }));
    expect(onPreview).toHaveBeenCalledWith(product);
  });

  it('shows seller lifecycle actions for archived products', () => {
    const onRestore = vi.fn();
    const archived = { ...product, status: 'archived' as const };
    render(
      <MemoryRouter>
        <ProductCard product={archived} sellerMode onRestore={onRestore} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: /seller.restore_product/ }));
    expect(onRestore).toHaveBeenCalledWith(archived);
  });

  it('fires archive and remove actions from seller mode', () => {
    const onArchive = vi.fn();
    const onRemove = vi.fn();
    render(
      <MemoryRouter>
        <ProductCard product={product} sellerMode onArchive={onArchive} onRemove={onRemove} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: /seller.archive_product/ }));
    expect(onArchive).toHaveBeenCalledWith(product);
    // The remove button is a separate lifecycle action (labelled action.delete).
    expect(screen.getByRole('button', { name: /action.delete/ })).toBeDefined();
  });

  it('removes a product from seller mode', () => {
    const onRemove = vi.fn();
    render(
      <MemoryRouter>
        <ProductCard product={product} sellerMode onRemove={onRemove} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: /action.delete/ }));
    expect(onRemove).toHaveBeenCalledWith(product);
  });
});
