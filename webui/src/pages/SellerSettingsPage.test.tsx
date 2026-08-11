// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SellerSettingsPage from './SellerSettingsPage';

const { getSellerProfile, updateSellerProfile, showToast, sellerApi } = vi.hoisted(() => ({
  getSellerProfile: vi.fn(),
  updateSellerProfile: vi.fn(),
  showToast: vi.fn(),
  sellerApi: {},
}));

vi.mock('../stores/SellerAuthContext', () => ({ useSellerAuth: () => ({ sellerApi }) }));
vi.mock('../api/shop', () => ({ createShopApi: () => ({ getSellerProfile, updateSellerProfile }) }));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('../components/storefront/StorefrontShell', () => ({ StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => ({ t: (key: string) => ({
  'seller.settings': 'Settings',
  'seller.settings_title': 'Store settings',
  'seller.settings_subtitle': 'Manage your storefront.',
  'seller.store_name': 'Store name',
  'seller.contact_email': 'Contact email',
  'seller.store_description': 'Store description',
  'seller.accept_orders': 'Accept new orders',
  'seller.store_status': 'Store status',
  'seller.store_live': 'Live',
  'seller.store_paused': 'Paused',
  'seller.store_status_description': 'The store accepts orders.',
  'seller.store_paused_description': 'The store is paused.',
  'seller.settings_saved': 'Store settings saved.',
  'seller.settings_load_failed': 'Could not load store settings.',
  'seller.settings_save_failed': 'Could not save store settings.',
  'seller.portal': 'Seller Studio',
  'browse.loading': 'Loading...',
  'commerce.save_changes': 'Save changes',
  'gallery.retry': 'Retry',
}[key] ?? key) }) }));

afterEach(() => cleanup());

describe('SellerSettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSellerProfile.mockResolvedValue({ profile: {
      store_name: 'North Studio',
      contact_email: 'hello@example.com',
      description: 'Digital artwork',
      accept_orders: true,
      updated_at: 1,
    } });
    updateSellerProfile.mockResolvedValue({ profile: {
      store_name: 'North Studio',
      contact_email: 'hello@example.com',
      description: 'Digital artwork',
      accept_orders: true,
      updated_at: 2,
    } });
  });

  it('loads, edits, and persists the real seller profile', async () => {
    render(<SellerSettingsPage />);

    expect(await screen.findByDisplayValue('North Studio')).toBeDefined();
    fireEvent.change(screen.getByLabelText('Store name'), { target: { value: 'New North Studio' } });
    fireEvent.click(screen.getByLabelText('Accept new orders'));
    fireEvent.submit(screen.getByRole('button', { name: 'Save changes' }).closest('form')!);

    await waitFor(() => expect(updateSellerProfile).toHaveBeenCalledWith({
      store_name: 'New North Studio',
      contact_email: 'hello@example.com',
      description: 'Digital artwork',
      accept_orders: false,
    }));
    expect(showToast).toHaveBeenCalledWith('Store settings saved.', 'success');
  });

  it('renders a retryable error state when the profile endpoint fails', async () => {
    getSellerProfile.mockRejectedValueOnce(new Error('Profile unavailable'));
    render(<SellerSettingsPage />);

    expect((await screen.findByRole('alert')).textContent).toContain('Profile unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(getSellerProfile).toHaveBeenCalledTimes(2));
  });
});