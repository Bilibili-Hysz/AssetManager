// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, act } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StorefrontCheckoutGroupPage from './StorefrontCheckoutGroupPage';

const api = {};
const { getCheckoutGroup, downloadOrderDelivery } = vi.hoisted(() => ({
  getCheckoutGroup: vi.fn(),
  downloadOrderDelivery: vi.fn(),
}));

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../api/shop', () => ({ createShopApi: () => ({ getCheckoutGroup, downloadOrderDelivery }) }));
vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => ({
      'commerce.store': 'Storefront',
      'commerce.back_to_store': 'Back to store',
      'commerce.secure_checkout': 'Secure checkout',
      'commerce.checkout_group_title': 'Checkout group',
      'commerce.checkout_group_description': 'Your order status',
      'commerce.continue_shopping': 'Continue shopping',
      'commerce.checkout_group': 'Checkout group',
      'commerce.checkout_group_items': 'Items',
      'commerce.checkout_group_total': 'Total',
      'commerce.quantity': 'Quantity',
      'commerce.order_details': 'Details',
      'commerce.delivery': 'Download',
      'commerce.delivery_pending': 'Pending delivery',
      'commerce.status_pending': 'Pending',
      'commerce.status_confirmed': 'Confirmed',
      'commerce.status_fulfilled': 'Fulfilled',
      'commerce.status_revoked': 'Revoked',
      'commerce.checkout_group_load_failed': 'Could not load checkout',
      'commerce.checkout_group_missing': 'Checkout unavailable',
      'browse.loading': 'Loading',
      'seller.product': 'Product',
      'seller.amount': 'Amount',
      'seller.status': 'Status',
      'seller.actions': 'Actions',
      'gallery.retry': 'Refresh',
    }[key] ?? key),
  }),
}));

const pendingGroup = {
  checkout_group_id: 'group-1',
  orders: [{ id: 22, item_id: 7, item_title: 'Queued asset', amount_cents: 1200, currency: 'USD', status: 'pending' as const, delivery_available: false, quantity: 1, created_at: 1, updated_at: 1 }],
  idempotent: false,
  status: 'active' as const,
  created_at: 1,
  cart: { id: 1, owner_type: 'anonymous' as const, status: 'converted' as const, version: 1, expires_at: null, created_at: 1, updated_at: 1, items: [] },
};
const confirmedGroup = { ...pendingGroup, orders: [{ ...pendingGroup.orders[0], status: 'confirmed' as const }] };
const fulfilledGroup = { ...pendingGroup, orders: [{ ...pendingGroup.orders[0], status: 'fulfilled' as const, delivery_available: true }] };

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/storefront/checkout-group?group=group-1']}>
      <Routes><Route path="/storefront/checkout-group" element={<StorefrontCheckoutGroupPage />} /></Routes>
    </MemoryRouter>,
  );
}

describe('StorefrontCheckoutGroupPage polling', () => {
  beforeEach(() => {
    getCheckoutGroup.mockReset();
    downloadOrderDelivery.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('updates order statuses with backoff and stops after all orders are fulfilled', async () => {
    getCheckoutGroup
      .mockResolvedValueOnce(pendingGroup)
      .mockResolvedValueOnce(confirmedGroup)
      .mockResolvedValueOnce(fulfilledGroup);

    vi.useFakeTimers();
    renderPage();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText('Queued asset')).toBeDefined();

    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(getCheckoutGroup).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Confirmed')).toBeDefined();

    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(getCheckoutGroup).toHaveBeenCalledTimes(3);
    expect(screen.getByText('Fulfilled')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Download' })).toBeDefined();

    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(getCheckoutGroup).toHaveBeenCalledTimes(3);
  });

  it('clears the polling timer on unmount and keeps known content after refresh failure', async () => {
    getCheckoutGroup.mockResolvedValueOnce(pendingGroup).mockRejectedValueOnce(new Error('temporary failure'));

    const view = renderPage();
    expect(await screen.findByText('Queued asset')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText('Queued asset')).toBeDefined();

    vi.useFakeTimers();
    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(getCheckoutGroup).toHaveBeenCalledTimes(2);
  });
});
