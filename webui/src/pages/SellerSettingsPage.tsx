import { Check, Save, ShieldCheck, XCircle } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import type { SellerPageProps } from '../components/storefront/types';
import { createShopApi } from '../api/shop';
import { useI18n } from '../hooks/useI18n';
import { useSellerAuth } from '../stores/SellerAuthContext';
import { useToast } from '../components/ui/Toast';
import type { ShopSellerProfile } from '../types/api';

const EMPTY_PROFILE: ShopSellerProfile = {
  store_name: '',
  contact_email: '',
  description: '',
  accept_orders: true,
  updated_at: 0,
};

export default function SellerSettingsPage({ seller }: SellerPageProps) {
  const { t } = useI18n();
  const { sellerApi } = useSellerAuth();
  const { showToast } = useToast();
  const shopApi = useMemo(() => createShopApi(sellerApi), [sellerApi]);
  const [profile, setProfile] = useState<ShopSellerProfile>(EMPTY_PROFILE);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await shopApi.getSellerProfile();
      setProfile(response.profile);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '');
    } finally {
      setLoading(false);
    }
  }, [shopApi]);

  useEffect(() => { void loadProfile(); }, [loadProfile]);

  const updateProfile = <Key extends keyof ShopSellerProfile>(key: Key, value: ShopSellerProfile[Key]) => {
    setProfile(current => ({ ...current, [key]: value }));
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving || loading) return;
    setSaving(true);
    try {
      const response = await shopApi.updateSellerProfile({
        store_name: profile.store_name,
        contact_email: profile.contact_email,
        description: profile.description,
        accept_orders: profile.accept_orders,
      });
      setProfile(response.profile);
      showToast(t('seller.settings_saved'), 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('seller.settings_save_failed'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const shellStoreName = profile.store_name || seller?.storeName || t('seller.portal');
  return (
    <StorefrontShell sellerMode storeName={shellStoreName}>
      <main className="seller-main">
        <div className="seller-page-heading">
          <div>
            <p className="storefront-eyebrow">{t('seller.settings')}</p>
            <h1>{t('seller.settings_title')}</h1>
            <p>{t('seller.settings_subtitle')}</p>
          </div>
        </div>
        {loading ? (
          <section className="seller-panel" aria-busy="true"><p>{t('browse.loading')}</p></section>
        ) : loadError ? (
          <section className="seller-panel">
            <div className="storefront-empty" role="alert">
              <XCircle size={24} aria-hidden="true" />
              <h3>{t('seller.settings_load_failed')}</h3>
              <p>{loadError || t('seller.settings_load_failed')}</p>
              <button type="button" className="storefront-button storefront-button-ghost" onClick={() => void loadProfile()}>{t('gallery.retry')}</button>
            </div>
          </section>
        ) : (
          <section className="seller-panel">
            <form className="seller-form" onSubmit={save}>
              <div className="seller-form-grid">
                <div className="seller-field">
                  <label htmlFor="seller-store-name">{t('seller.store_name')}</label>
                  <input id="seller-store-name" value={profile.store_name} onChange={event => updateProfile('store_name', event.target.value)} disabled={saving} />
                </div>
                <div className="seller-field">
                  <label htmlFor="seller-store-email">{t('seller.contact_email')}</label>
                  <input id="seller-store-email" type="email" value={profile.contact_email} onChange={event => updateProfile('contact_email', event.target.value)} disabled={saving} />
                </div>
                <div className="seller-field seller-field-full">
                  <label htmlFor="seller-store-description">{t('seller.store_description')}</label>
                  <textarea id="seller-store-description" value={profile.description} onChange={event => updateProfile('description', event.target.value)} disabled={saving} />
                </div>
              </div>
              <label className="seller-check-row">
                <input type="checkbox" checked={profile.accept_orders} onChange={event => updateProfile('accept_orders', event.target.checked)} disabled={saving} />
                {t('seller.accept_orders')} <ShieldCheck size={15} />
              </label>
              <div>
                <button type="submit" className="storefront-button storefront-button-primary" disabled={saving}>
                  <Save size={15} /> {saving ? t('browse.loading') : t('commerce.save_changes')}
                </button>
              </div>
              <div className="seller-quota">
                <div className="seller-quota-header">
                  <span>{t('seller.store_status')}</span>
                  <strong style={{ color: profile.accept_orders ? 'var(--color-success)' : 'var(--color-warning)' }}>
                    {profile.accept_orders ? <Check size={14} /> : <XCircle size={14} />} {profile.accept_orders ? t('seller.store_live') : t('seller.store_paused')}
                  </strong>
                </div>
                <p style={{ margin: 0, color: 'var(--color-text-secondary)', fontSize: 12, lineHeight: 1.6 }}>
                  {profile.accept_orders ? t('seller.store_status_description') : t('seller.store_paused_description')}
                </p>
              </div>
            </form>
          </section>
        )}
      </main>
    </StorefrontShell>
  );
}