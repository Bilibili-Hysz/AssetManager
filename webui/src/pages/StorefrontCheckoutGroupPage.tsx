import { ArrowLeft, CheckCircle2, Clock3, ExternalLink, PackageCheck, RefreshCw } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { BuyerDeliveryDownloadButton } from '../components/storefront/BuyerDeliveryDownloadButton';
import { formatMoney } from '../components/storefront/types';
import { useShopApi } from '../hooks/usePageApis';
import { useI18n } from '../hooks/useI18n';
import type { ShopCheckoutGroupOrder, ShopCheckoutGroupResponse, ShopOrderStatus } from '../types/api';

const INITIAL_POLL_DELAY_MS = 1_000;
const MAX_POLL_DELAY_MS = 8_000;

function statusLabel(status: ShopOrderStatus, t: (key: string) => string): string {
  const labels: Record<ShopOrderStatus, string> = {
    pending: t('commerce.status_pending'),
    confirmed: t('commerce.status_confirmed'),
    fulfilled: t('commerce.status_fulfilled'),
    revoked: t('commerce.status_revoked'),
  };
  return labels[status];
}

function orderQuantity(order: ShopCheckoutGroupOrder): number {
  return Number.isFinite(order.quantity) && order.quantity > 0 ? order.quantity : 1;
}

function hasActiveOrders(checkout: ShopCheckoutGroupResponse | null): boolean {
  return checkout?.orders.some(order => order.status === 'pending' || order.status === 'confirmed') ?? false;
}

export default function StorefrontCheckoutGroupPage() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const group = searchParams.get('group')?.trim() ?? '';
  const shop = useShopApi();
  const [checkout, setCheckout] = useState<ShopCheckoutGroupResponse | null>(null);
  const [loading, setLoading] = useState(Boolean(group));
  const [refreshing, setRefreshing] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollAttemptRef = useRef(0);
  const pollingRef = useRef(false);
  const mountedRef = useRef(true);
  const schedulePollRef = useRef<(delay: number) => void>(() => undefined);

  const stopPolling = useCallback(() => {
    pollingRef.current = false;
    pollAttemptRef.current = 0;
    if (pollTimerRef.current !== null) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const loadCheckout = useCallback(async (showLoading: boolean) => {
    if (!group) return null;
    if (showLoading) setLoading(true);
    else setRefreshing(true);

    try {
      const response = await shop.getCheckoutGroup(group);
      if (mountedRef.current) {
        setCheckout(response);
        setLoadFailed(false);
      }
      return response;
    } catch {
      // Keep the last known checkout visible during transient polling/manual-refresh failures.
      if (mountedRef.current && showLoading) setLoadFailed(true);
      return null;
    } finally {
      if (mountedRef.current) {
        if (showLoading) setLoading(false);
        else setRefreshing(false);
      }
    }
  }, [group, shop]);

  const pollCheckout = useCallback(async () => {
    if (!mountedRef.current || !pollingRef.current) return;
    const nextCheckout = await loadCheckout(false);
    if (!mountedRef.current || !pollingRef.current) return;

    if (nextCheckout && !hasActiveOrders(nextCheckout)) {
      stopPolling();
      return;
    }

    pollAttemptRef.current += 1;
    schedulePollRef.current(Math.min(MAX_POLL_DELAY_MS, INITIAL_POLL_DELAY_MS * 2 ** pollAttemptRef.current));
  }, [loadCheckout, stopPolling]);

  const schedulePoll = useCallback((delay: number) => {
    if (!pollingRef.current || pollTimerRef.current !== null) return;
    pollTimerRef.current = setTimeout(() => {
      pollTimerRef.current = null;
      void pollCheckout();
    }, delay);
  }, [pollCheckout]);
  schedulePollRef.current = schedulePoll;

  const startPolling = useCallback(() => {
    if (!mountedRef.current || pollingRef.current) return;
    pollingRef.current = true;
    pollAttemptRef.current = 0;
    schedulePoll(INITIAL_POLL_DELAY_MS);
  }, [schedulePoll]);

  const refresh = useCallback(async () => {
    if (!group || refreshing) return;
    const nextCheckout = await loadCheckout(false);
    if (!mountedRef.current) return;
    if (nextCheckout && hasActiveOrders(nextCheckout)) startPolling();
    else if (nextCheckout) stopPolling();
  }, [group, loadCheckout, refreshing, startPolling, stopPolling]);

  useEffect(() => {
    mountedRef.current = true;
    stopPolling();
    setCheckout(null);
    setLoadFailed(false);
    if (!group) {
      setLoading(false);
      return () => { mountedRef.current = false; };
    }

    void loadCheckout(true).then(nextCheckout => {
      if (nextCheckout && hasActiveOrders(nextCheckout)) startPolling();
    });

    return () => {
      mountedRef.current = false;
      stopPolling();
    };
  }, [group, loadCheckout, startPolling, stopPolling]);

  const totals = useMemo(() => {
    const grouped = new Map<string, number>();
    for (const order of checkout?.orders ?? []) {
      grouped.set(order.currency, (grouped.get(order.currency) ?? 0) + order.amount_cents);
    }
    return Array.from(grouped.entries());
  }, [checkout?.orders]);

  const hasOrders = (checkout?.orders.length ?? 0) > 0;

  return (
    <StorefrontShell storeName={t('commerce.store')}>
      <main className="storefront-main storefront-buyer-page">
        <Link className="storefront-link" to="/storefront"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link>
        <div className="storefront-page-intro">
          <div>
            <p className="storefront-eyebrow"><PackageCheck size={14} /> {t('commerce.secure_checkout')}</p>
            <h1>{t('commerce.checkout_group_title')}</h1>
            <p>{t('commerce.checkout_group_description')}</p>
          </div>
          <Link className="storefront-button storefront-button-ghost" to="/storefront/products">
            {t('commerce.continue_shopping')}
          </Link>
        </div>

        {loading ? (
          <section className="storefront-buyer-panel"><p>{t('browse.loading')}</p></section>
        ) : !group || loadFailed || !checkout ? (
          <section className="storefront-buyer-panel storefront-empty" role="alert">
            <PackageCheck size={28} />
            <h3>{group ? t('commerce.checkout_group_load_failed') : t('commerce.checkout_group_missing')}</h3>
            <p>{group ? t('commerce.checkout_group_load_failed_description') : t('commerce.checkout_group_missing')}</p>
            {group ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, justifyContent: 'center' }}>
                <button type="button" className="storefront-button storefront-button-primary" onClick={() => void loadCheckout(true)}>
                  <RefreshCw size={15} /> {t('gallery.retry')}
                </button>
                <Link className="storefront-button storefront-button-ghost" to="/storefront/products">
                  {t('commerce.continue_shopping')}
                </Link>
              </div>
            ) : (
              <Link className="storefront-button storefront-button-primary" to="/storefront/products">
                {t('commerce.continue_shopping')}
              </Link>
            )}
          </section>
        ) : !hasOrders ? (
          <section className="storefront-buyer-panel storefront-empty" role="alert">
            <PackageCheck size={28} />
            <h3>{t('commerce.checkout_group_missing')}</h3>
            <Link className="storefront-button storefront-button-primary" to="/storefront/products">
              {t('commerce.continue_shopping')}
            </Link>
          </section>
        ) : (
          <section className="storefront-buyer-panel" aria-labelledby="checkout-group-items-title">
            <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 12, alignItems: 'baseline' }}>
              <div>
                <p className="storefront-eyebrow"><CheckCircle2 size={14} /> {t('commerce.checkout_group')}</p>
                <h2 id="checkout-group-items-title" style={{ margin: 0 }}>{t('commerce.checkout_group_items')}</h2>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
                <button type="button" className="storefront-button storefront-button-ghost" style={{ minHeight: 34, padding: '0 10px', fontSize: 12 }} onClick={() => void refresh()} disabled={refreshing}>
                  <RefreshCw size={14} /> {t('gallery.retry')}
                </button>
                <code style={{ color: 'var(--color-text-secondary)', fontSize: 12 }}>{checkout.checkout_group_id}</code>
              </div>
            </div>

            <div style={{ overflowX: 'auto', marginTop: 20 }}>
              <table style={{ width: '100%', minWidth: 620, borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left', color: 'var(--color-text-secondary)' }}>
                    <th style={{ padding: '0 12px 12px 0', fontWeight: 600 }}>{t('seller.product')}</th>
                    <th style={{ padding: '0 12px 12px', fontWeight: 600 }}>{t('commerce.quantity')}</th>
                    <th style={{ padding: '0 12px 12px', fontWeight: 600 }}>{t('seller.amount')}</th>
                    <th style={{ padding: '0 12px 12px', fontWeight: 600 }}>{t('seller.status')}</th>
                    <th style={{ padding: '0 0 12px 12px', fontWeight: 600, textAlign: 'right' }}>{t('seller.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {checkout.orders.map(order => (
                    <tr key={order.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                      <td style={{ padding: '16px 12px 16px 0', color: 'var(--color-text)', fontWeight: 650 }}>{order.item_title}</td>
                      <td style={{ padding: '16px 12px', color: 'var(--color-text-secondary)' }}>{orderQuantity(order)}</td>
                      <td style={{ padding: '16px 12px', color: 'var(--color-text)' }}>{formatMoney(order.amount_cents / 100, order.currency)}</td>
                      <td style={{ padding: '16px 12px' }}>
                        <span className={`seller-status seller-status-${order.status}`}>{statusLabel(order.status, t)}</span>
                      </td>
                      <td style={{ padding: '16px 0 16px 12px', textAlign: 'right' }}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 8 }}>
                          <Link className="storefront-button storefront-button-ghost" style={{ minHeight: 34, padding: '0 10px', fontSize: 12 }} to={`/storefront/checkout/${encodeURIComponent(String(order.id))}`}>
                            <ExternalLink size={14} /> {t('commerce.order_details')}
                          </Link>
                          {order.status === 'fulfilled' && order.delivery_available ? (
                            <BuyerDeliveryDownloadButton
                              orderId={order.id}
                              itemTitle={order.item_title}
                              shop={shop}
                              label={t('commerce.delivery')}
                              loadingLabel={t('browse.loading')}
                              className="storefront-button storefront-button-primary"
                              style={{ minHeight: 34, padding: '0 10px', fontSize: 12 }}
                              iconSize={14}
                            />
                          ) : (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: 'var(--color-text-secondary)', fontSize: 12 }}>
                              <Clock3 size={14} /> {t('commerce.delivery_pending')}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="storefront-cart-summary">
              <div className="storefront-cart-total">
                <span>{t('commerce.checkout_group_total')}</span>
                {totals.map(([currency, cents]) => <strong key={currency}>{formatMoney(cents / 100, currency)}</strong>)}
              </div>
              <Link className="storefront-button storefront-button-ghost" to="/storefront/products">
                {t('commerce.continue_shopping')}
              </Link>
            </div>
          </section>
        )}
      </main>
    </StorefrontShell>
  );
}
