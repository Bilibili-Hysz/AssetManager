// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, act, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StorefrontCheckoutPage from './StorefrontCheckoutPage';

const api = {};

const { getOrder, confirmOrder, downloadOrderDelivery, showToast } = vi.hoisted(() => ({
  getOrder: vi.fn(),
  confirmOrder: vi.fn(),
  downloadOrderDelivery: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../api/shop', () => ({ createShopApi: () => ({ getOrder, confirmOrder, downloadOrderDelivery }) }));
vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => ({
      'commerce.store': 'Storefront',
      'commerce.back_to_store': 'Back to store',
      'commerce.secure_checkout': 'Secure checkout',
      'commerce.confirm_purchase': 'Confirm purchase',
      'commerce.product_not_found_description': 'Order unavailable',
      'commerce.purchase_ready': 'Purchase ready',
      'commerce.continue': 'Continue',
      'commerce.instant_access': 'Instant access',
      'browse.loading': 'Loading',
      'seller.order': 'Order',
      'seller.product': 'Product',
      'seller.amount': 'Amount',
      'seller.status': 'Status',
      'action.download': 'Download',
    }[key] ?? key),
  }),
}));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast }) }));

const pendingOrder = {
  id: 22,
  item_id: 7,
  item_path: 'assets/example.zip',
  item_title: 'Example asset',
  amount_cents: 1200,
  currency: 'USD',
  status: 'pending' as const,
  delivery_available: false,
  created_at: 1,
  updated_at: 1,
};

const confirmedOrder = { ...pendingOrder, status: 'confirmed' as const };
const fulfilledOrder = { ...confirmedOrder, status: 'fulfilled' as const, delivery_available: true };

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/storefront/checkout/22']}>
      <Routes>
        <Route path="/storefront/checkout/:orderId" element={<StorefrontCheckoutPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('StorefrontCheckoutPage buyer delivery flow', () => {
  beforeEach(() => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    getOrder.mockReset();
    confirmOrder.mockReset();
    downloadOrderDelivery.mockReset();
    Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:delivery'), configurable: true });
    Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), configurable: true });
    showToast.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('downloads fulfilled delivery through the idempotent buyer API', async () => {
    getOrder.mockResolvedValue({ order: fulfilledOrder });
    downloadOrderDelivery.mockResolvedValue({ blob: new Blob(['zip'], { type: 'application/zip' }), filename: 'example.zip' });

    renderPage();

    const button = await screen.findByRole('button', { name: 'Download' });
    fireEvent.click(button);

    await waitFor(() => expect(downloadOrderDelivery).toHaveBeenCalledTimes(1));
    expect(downloadOrderDelivery).toHaveBeenCalledWith(22, expect.stringMatching(/^buyer-delivery-22-/));
    expect(screen.queryByText(/token|metadata|buyer_email/i)).toBeNull();
  });

  it('uses a fresh request key when a buyer retries after a network failure', async () => {
    getOrder.mockResolvedValue({ order: fulfilledOrder });
    downloadOrderDelivery
      .mockRejectedValueOnce(new Error('temporary network failure'))
      .mockResolvedValueOnce({ blob: new Blob(['zip'], { type: 'application/zip' }), filename: 'example.zip' });

    renderPage();
    const button = await screen.findByRole('button', { name: 'Download' });
    fireEvent.click(button);
    await waitFor(() => expect(showToast).toHaveBeenCalledWith('temporary network failure', 'error'));

    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await waitFor(() => expect(downloadOrderDelivery).toHaveBeenCalledTimes(2));
    expect(downloadOrderDelivery.mock.calls[0]![1]).not.toBe(downloadOrderDelivery.mock.calls[1]![1]);
  });

  it('polls with backoff after confirmation and stops when fulfilled', async () => {
    getOrder
      .mockResolvedValueOnce({ order: pendingOrder })
      .mockResolvedValueOnce({ order: confirmedOrder })
      .mockResolvedValueOnce({ order: fulfilledOrder });
    confirmOrder.mockResolvedValue({ order: confirmedOrder });

    renderPage();
    const confirmButton = await screen.findByRole('button', { name: 'Continue' });
    vi.useFakeTimers();
    await act(async () => {
      fireEvent.click(confirmButton);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(confirmOrder).toHaveBeenCalledWith('22');

    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(getOrder).toHaveBeenCalledTimes(2);

    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(getOrder).toHaveBeenCalledTimes(2);

    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(getOrder).toHaveBeenCalledTimes(3);
    expect(screen.getByRole('button', { name: 'Download' })).toBeDefined();

    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(getOrder).toHaveBeenCalledTimes(3);
  });

  it('clears the pending poll timer when the page unmounts', async () => {
    getOrder.mockResolvedValueOnce({ order: pendingOrder });
    confirmOrder.mockResolvedValue({ order: confirmedOrder });

    const view = renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Continue' }));
    vi.useFakeTimers();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(confirmOrder).toHaveBeenCalled();
    view.unmount();

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(getOrder).toHaveBeenCalledTimes(1);
  });
});
