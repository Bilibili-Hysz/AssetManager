// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BuyerDeliveryDownloadButton } from './BuyerDeliveryDownloadButton';

const mocks = vi.hoisted(() => ({
  showToast: vi.fn(),
  t: vi.fn((key: string) => ({
    'commerce.product_not_found_description': 'This product is unavailable.',
  }[key] ?? key)),
}));

vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({ t: mocks.t }),
}));
vi.mock('../ui/Toast', () => ({
  useToast: () => ({ showToast: mocks.showToast }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function createShop(downloadOrderDelivery = vi.fn()) {
  return { downloadOrderDelivery } as never;
}

function renderButton(
  shop = createShop(),
  props: Partial<React.ComponentProps<typeof BuyerDeliveryDownloadButton>> = {},
) {
  return render(
    <BuyerDeliveryDownloadButton
      orderId="order/42"
      itemTitle="My: Asset?"
      shop={shop}
      label="Download"
      loadingLabel="Downloading..."
      {...props}
    />,
  );
}

describe('BuyerDeliveryDownloadButton', () => {
  beforeEach(() => {
    mocks.showToast.mockReset();
    mocks.t.mockClear();
    vi.useRealTimers();

    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn(() => 'blob:delivery-1'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('downloads the delivery with an idempotency key and cleans up the object URL', async () => {
    const downloadOrderDelivery = vi.fn().mockResolvedValue({
      blob: new Blob(['zip'], { type: 'application/zip' }),
      filename: 'server-name.zip',
    });
    const shop = createShop(downloadOrderDelivery);

    renderButton(shop);
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));

    await waitFor(() => expect(downloadOrderDelivery).toHaveBeenCalledTimes(1));
    const [orderId, requestKey] = downloadOrderDelivery.mock.calls[0]!;
    expect(orderId).toBe('order/42');
    expect(requestKey).toMatch(/^buyer-delivery-order\/42-.+/);
    expect(requestKey.length).toBeLessThanOrEqual(200);

    const anchor = document.querySelector('a');
    expect(anchor).toBeNull();
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
    // revoke is delayed (Firefox blob-URL semantics); wait for it
    await new Promise((resolve) => setTimeout(resolve, 1100));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:delivery-1');

    expect((screen.getByRole('button', { name: 'Download' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('uses the sanitized item title when the delivery has no filename', async () => {
    const downloadOrderDelivery = vi.fn().mockResolvedValue({
      blob: new Blob(['zip']),
      filename: null,
    });
    const shop = createShop(downloadOrderDelivery);
    const appendChild = vi.spyOn(document.body, 'appendChild');

    renderButton(shop);
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));

    await waitFor(() => expect(downloadOrderDelivery).toHaveBeenCalled());
    const calls = appendChild.mock.calls;
    const anchor = calls[calls.length - 1]?.[0] as HTMLAnchorElement;
    expect(anchor.download).toBe('My_ Asset_.zip');
  });

  it('shows loading state and ignores repeated clicks while a download is pending', async () => {
    const pending = deferred<{ blob: Blob; filename: string }>();
    const downloadOrderDelivery = vi.fn().mockReturnValue(pending.promise);
    const shop = createShop(downloadOrderDelivery);

    renderButton(shop);
    const button = screen.getByRole('button', { name: 'Download' }) as HTMLButtonElement;
    fireEvent.click(button);
    fireEvent.click(button);

    expect(downloadOrderDelivery).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect((screen.getByRole('button', { name: 'Downloading...' }) as HTMLButtonElement).disabled).toBe(true);

    await act(async () => {
      pending.resolve({ blob: new Blob(['zip']), filename: 'asset.zip' });
      await pending.promise;
    });
    await waitFor(() => expect((screen.getByRole('button', { name: 'Download' }) as HTMLButtonElement).disabled).toBe(false));
  });

  it('shows an error toast and allows a retry with a fresh request key', async () => {
    const downloadOrderDelivery = vi.fn()
      .mockRejectedValueOnce(new Error('delivery unavailable'))
      .mockResolvedValueOnce({ blob: new Blob(['zip']), filename: 'asset.zip' });
    const shop = createShop(downloadOrderDelivery);

    renderButton(shop);
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await waitFor(() => expect(mocks.showToast).toHaveBeenCalledWith('delivery unavailable', 'error'));
    expect((screen.getByRole('button', { name: 'Download' }) as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await waitFor(() => expect(downloadOrderDelivery).toHaveBeenCalledTimes(2));
    expect(downloadOrderDelivery.mock.calls[0]![1]).not.toBe(downloadOrderDelivery.mock.calls[1]![1]);
  });

  it('does not show a toast or update loading state after unmounting', async () => {
    const pending = deferred<{ blob: Blob; filename: string }>();
    const shop = createShop(vi.fn().mockReturnValue(pending.promise));
    const view = renderButton(shop);
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    view.unmount();

    await act(async () => {
      pending.resolve({ blob: new Blob(['zip']), filename: 'asset.zip' });
      await pending.promise;
    });

    expect(mocks.showToast).not.toHaveBeenCalled();
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });
});



