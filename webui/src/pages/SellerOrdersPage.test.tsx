// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SellerOrdersPage from './SellerOrdersPage';

const { fulfillOrder, revokeOrder, exportOrdersUrl, refresh, showToast, writeText, orderState } = vi.hoisted(() => ({
  fulfillOrder: vi.fn(),
  revokeOrder: vi.fn(),
  exportOrdersUrl: vi.fn(() => '/api/shop/orders/export'),
  refresh: vi.fn(),
  showToast: vi.fn(),
  writeText: vi.fn(),
  orderState: {
    orders: [{
      id: 'order-7',
      productName: 'Reference asset',
      amount: 12,
      currency: 'USD',
      status: 'paid' as const,
      sourceStatus: 'confirmed' as 'pending' | 'confirmed' | 'fulfilled' | 'revoked',
      createdAt: 'today',
    }],
  },
}));

vi.mock('../hooks/useCommerce', () => ({
  useCommerceOrders: () => ({
    orders: orderState.orders,
    refresh,
  }),
}));
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api: {} }) }));
vi.mock('../api/shop', () => ({
  createShopApi: () => ({ fulfillOrder, revokeOrder, exportOrdersUrl }),
}));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('../components/storefront/StorefrontShell', () => ({ StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => ({
      'seller.portal': 'Seller Studio', 'seller.activity': 'Activity', 'seller.orders_title': 'Orders',
      'seller.orders_subtitle': 'Review orders', 'seller.export_orders': 'Export', 'seller.filter_all': 'All',
      'seller.status_paid': 'Fulfill', 'seller.status_refunded': 'Refund', 'seller.order': 'Order',
      'seller.product': 'Product', 'seller.amount': 'Amount', 'seller.status': 'Status', 'seller.date': 'Date',
      'seller.actions': 'Actions', 'seller.delivery_link': 'Delivery link',
      'seller.delivery_link_ready': 'Delivery link ready', 'seller.recover_delivery': 'Recover delivery', 'seller.no_orders': 'No orders',
      'commerce.search': 'Search',
      'commerce.product_not_found_description': 'Not found',
    }[key] ?? key),
  }),
}));

describe('SellerOrdersPage delivery handoff', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    orderState.orders[0]!.status = 'paid';
    orderState.orders[0]!.sourceStatus = 'confirmed';
    fulfillOrder.mockReset().mockResolvedValue({ order: {}, delivery_token: 'secret', delivery_url: '/api/shop/delivery/secret' });
    revokeOrder.mockReset();
    refresh.mockReset().mockResolvedValue(undefined);
    showToast.mockReset();
    writeText.mockReset().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
  });

  it('copies and exposes the seller-only delivery URL after fulfillment', async () => {
    render(<SellerOrdersPage />);
    const fulfillButton = document.querySelector<HTMLButtonElement>('.seller-row-action-success');
    expect(fulfillButton).not.toBeNull();
    fireEvent.click(fulfillButton!);

    await waitFor(() => expect(fulfillOrder).toHaveBeenCalledWith('order-7'));
    const link = await screen.findByRole('link', { name: 'Delivery link' });
    const expectedUrl = new URL('/api/shop/delivery/secret', window.location.origin).toString();
    expect(link.getAttribute('href')).toBe(expectedUrl);
    expect(writeText).toHaveBeenCalledWith(expectedUrl);
    expect(showToast).toHaveBeenCalledWith('Delivery link ready', 'success');
  });

  it('does not render a non-functional more-actions control', () => {
    render(<SellerOrdersPage />);

    expect(screen.queryByRole('button', { name: 'More actions' })).toBeNull();
  });

  it('does not offer revoke for fulfilled orders because the backend treats them as terminal', () => {
    orderState.orders[0]!.sourceStatus = 'fulfilled';
    render(<SellerOrdersPage />);

    expect(document.querySelector('.seller-row-action-danger')).toBeNull();
    expect(screen.getByRole('button', { name: 'Recover delivery' })).toBeDefined();
  });
});
