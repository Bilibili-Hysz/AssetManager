// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import StorefrontBuyerOrdersPage from './StorefrontBuyerOrdersPage';

const { listBuyerOrders, recoverOrderReceipt, shopApi } = vi.hoisted(() => {
  const listBuyerOrders = vi.fn();
  const recoverOrderReceipt = vi.fn();
  return { listBuyerOrders, recoverOrderReceipt, shopApi: { listBuyerOrders, recoverOrderReceipt } };
});

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api: {} }) }));
vi.mock('../api/shop', () => ({ createShopApi: () => shopApi }));
vi.mock('../components/storefront/StorefrontShell', () => ({ StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, ...args: Array<string | number>) => {
      const labels: Record<string, string> = {
        'commerce.store': 'Storefront', 'commerce.back_to_store': 'Back to store', 'commerce.buyer_orders': 'Order history',
        'commerce.buyer_orders_description': 'Review purchases', 'commerce.buyer_orders_filter': 'Filter by status',
        'commerce.buyer_orders_all': 'All orders', 'commerce.buyer_orders_empty': 'No purchases yet',
        'commerce.buyer_orders_empty_description': 'Orders appear here', 'commerce.buyer_orders_load_failed': 'Could not load order history',
        'commerce.buyer_orders_loading': 'Loading order history...', 'commerce.buyer_orders_total': `${args[0] ?? 0} orders`,
        'commerce.buyer_orders_view': 'View order', 'commerce.order_date': 'Date', 'commerce.order_title': 'Order',
        'commerce.order_amount': 'Amount', 'commerce.order_status': 'Status', 'commerce.quantity': 'Quantity',
        'commerce.continue_shopping': 'Continue shopping', 'commerce.status_pending': 'Pending',
        'commerce.status_confirmed': 'Confirmed', 'commerce.status_fulfilled': 'Delivered', 'commerce.status_revoked': 'Revoked',
        'commerce.buyer_orders_recover': 'Restore access', 'commerce.buyer_orders_recovered': 'Access restored', 'commerce.buyer_orders_recover_failed': 'Could not restore access.',
      };
      return labels[key] ?? key;
    },
  }),
}));

const fulfilledOrder = {
  id: 42, item_id: 7, item_title: 'Example asset', amount_cents: 1250, currency: 'USD', status: 'fulfilled' as const,
  delivery_available: true, quantity: 2, created_at: 1_754_000_000, updated_at: 1_754_000_000,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/storefront/orders']}>
      <StorefrontBuyerOrdersPage />
    </MemoryRouter>,
  );
}

describe('StorefrontBuyerOrdersPage', () => {
  beforeEach(() => {
    listBuyerOrders.mockReset();
    recoverOrderReceipt.mockReset().mockResolvedValue({ ok: true, order_id: 42 });
  });

  afterEach(() => {
    cleanup();
  });

  it('renders buyer-safe order fields and links to checkout details', async () => {
    listBuyerOrders.mockResolvedValue({ orders: [fulfilledOrder], total: 1, next_cursor: null });
    renderPage();

    expect(await screen.findByText('Example asset')).toBeDefined();
    expect(screen.getByText('2')).toBeDefined();
    expect(screen.getByText(/12\.50/)).toBeDefined();
    expect(screen.getAllByText('Delivered').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('link', { name: /View order/i }).getAttribute('href')).toBe('/storefront/checkout/42');
    expect(screen.queryByText(/buyer_email|item_path|metadata|delivery_token/i)).toBeNull();
    expect(listBuyerOrders).toHaveBeenCalledWith(undefined, 50, undefined, expect.any(AbortSignal));
  });

  it('can restore a lost receipt cookie from buyer order history', async () => {
    listBuyerOrders.mockResolvedValue({ orders: [fulfilledOrder], total: 1, next_cursor: null });
    renderPage();

    const recover = await screen.findByRole('button', { name: 'Restore access' });
    fireEvent.click(recover);
    await waitFor(() => expect(recoverOrderReceipt).toHaveBeenCalledWith(42));
    expect(await screen.findByText('Access restored')).toBeDefined();
  });

  it('reloads with the selected status filter', async () => {
    listBuyerOrders.mockResolvedValue({ orders: [], total: 0 });
    renderPage();
    await screen.findByText('No purchases yet');

    fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'pending' } });
    await waitFor(() => expect(listBuyerOrders).toHaveBeenLastCalledWith('pending', 50, undefined, expect.any(AbortSignal)));
  });

  it('shows empty and error states', async () => {
    listBuyerOrders.mockResolvedValueOnce({ orders: [], total: 0 });
    renderPage();
    expect(await screen.findByText('No purchases yet')).toBeDefined();

    listBuyerOrders.mockRejectedValueOnce(new Error('offline'));
    fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'confirmed' } });
    expect(await screen.findByText('Could not load order history')).toBeDefined();
  });
});





