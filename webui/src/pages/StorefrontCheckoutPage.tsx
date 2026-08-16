import { ArrowLeft, CheckCircle2, Clock3, PackageCheck, RefreshCw } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { useCallback, useEffect, useRef, useState } from 'react';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { BuyerDeliveryDownloadButton } from '../components/storefront/BuyerDeliveryDownloadButton';
import { formatMoney } from '../components/storefront/types';
import { useShopApi } from '../hooks/usePageApis';
import { useI18n } from '../hooks/useI18n';
import { useToast } from '../components/ui/Toast';
import type { ShopBuyerOrder } from '../types/api';

const INITIAL_POLL_DELAY_MS = 1_000;
const MAX_POLL_DELAY_MS = 8_000;

export default function StorefrontCheckoutPage() {
  const { t } = useI18n();
  const { showToast } = useToast();
  const { orderId } = useParams<{ orderId: string }>();
  const shopApi = useShopApi();
  const [order, setOrder] = useState<ShopBuyerOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [confirming, setConfirming] = useState(false);
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

  const loadOrder = useCallback(async (showLoading: boolean) => {
    if (!orderId) return null;
    if (showLoading) setLoading(true);
    try {
      const result = await shopApi.getOrder(orderId);
      if (mountedRef.current) {
        setOrder(result.order);
        setLoadFailed(false);
      }
      return result.order;
    } catch {
      if (mountedRef.current && showLoading) {
        setOrder(null);
        setLoadFailed(true);
      }
      return null;
    } finally {
      if (mountedRef.current && showLoading) setLoading(false);
    }
  }, [orderId, shopApi]);

  const pollOrder = useCallback(async () => {
    if (!mountedRef.current || !pollingRef.current) return;
    const nextOrder = await loadOrder(false);
    if (!mountedRef.current || !pollingRef.current) return;
    if (nextOrder?.status === 'fulfilled' || nextOrder?.status === 'revoked') {
      stopPolling();
      return;
    }

    pollAttemptRef.current += 1;
    schedulePollRef.current(Math.min(MAX_POLL_DELAY_MS, INITIAL_POLL_DELAY_MS * 2 ** pollAttemptRef.current));
  }, [loadOrder, stopPolling]);

  const schedulePoll = useCallback((delay: number) => {
    if (!pollingRef.current || pollTimerRef.current !== null) return;
    pollTimerRef.current = setTimeout(() => {
      pollTimerRef.current = null;
      void pollOrder();
    }, delay);
  }, [pollOrder]);
  schedulePollRef.current = schedulePoll;

  const startPolling = useCallback(() => {
    if (!mountedRef.current || pollingRef.current) return;
    pollingRef.current = true;
    pollAttemptRef.current = 0;
    schedulePoll(INITIAL_POLL_DELAY_MS);
  }, [schedulePoll]);

  useEffect(() => {
    mountedRef.current = true;
    stopPolling();
    if (!orderId) {
      // No order id on the route: never leave the page stuck in loading.
      setLoading(false);
      return () => { mountedRef.current = false; };
    }
    void loadOrder(true).then(nextOrder => {
      if (nextOrder?.status === 'confirmed') startPolling();
    });
    return () => {
      mountedRef.current = false;
      stopPolling();
    };
  }, [loadOrder, orderId, startPolling, stopPolling]);

  const confirm = async () => {
    if (!orderId || confirming) return;
    setConfirming(true);
    try {
      const result = await shopApi.confirmOrder(orderId);
      if (!mountedRef.current) return;
      setOrder(result.order);
      showToast(t('commerce.purchase_ready'), 'success');
      if (result.order.status === 'fulfilled' || result.order.status === 'revoked') {
        stopPolling();
      } else {
        startPolling();
      }
    } catch (error) {
      if (mountedRef.current) {
        showToast(error instanceof Error ? error.message : t('commerce.product_not_found_description'), 'error');
      }
    } finally {
      if (mountedRef.current) setConfirming(false);
    }
  };

  return (
    <StorefrontShell storeName={t('commerce.store')}>
      <main className="storefront-main">
        <Link className="storefront-link" to="/storefront"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link>
        <section className="storefront-checkout-card" aria-labelledby="checkout-title">
          <p className="storefront-eyebrow"><PackageCheck size={14} /> {t('commerce.secure_checkout')}</p>
          <h1 id="checkout-title">{t('commerce.confirm_purchase')}</h1>
          {loading ? <p>{t('browse.loading')}</p> : !order ? (
            loadFailed ? (
              <div role="alert" style={{ display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'flex-start' }}>
                <p>{t('commerce.checkout_load_failed')}</p>
                <button type="button" className="storefront-button storefront-button-ghost" onClick={() => void loadOrder(true)}>
                  <RefreshCw size={15} /> {t('gallery.retry')}
                </button>
              </div>
            ) : (
              <p role="alert">{t('commerce.product_not_found_description')}</p>
            )
          ) : (
            <>
              <div className="storefront-checkout-summary">
                <div><span>{t('seller.order')}</span><strong>#{order.id}</strong></div>
                <div><span>{t('seller.product')}</span><strong>{order.item_title}</strong></div>
                <div><span>{t('seller.amount')}</span><strong>{formatMoney(order.amount_cents / 100, order.currency)}</strong></div>
                <div><span>{t('seller.status')}</span><strong className={`seller-status seller-status-${order.status}`}>{order.status}</strong></div>
              </div>
              {order.status === 'pending' ? (
                <button type="button" className="storefront-button storefront-button-primary" disabled={confirming} onClick={() => void confirm()}>
                  <CheckCircle2 size={16} /> {confirming ? t('browse.loading') : t('commerce.continue')}
                </button>
              ) : order.status === 'fulfilled' && order.delivery_available ? (
                <BuyerDeliveryDownloadButton
                  orderId={order.id}
                  itemTitle={order.item_title}
                  shop={shopApi}
                  label={t('action.download')}
                  loadingLabel={t('browse.loading')}
                />
              ) : (
                <p className="storefront-checkout-note"><Clock3 size={15} /> {t('commerce.instant_access')}</p>
              )}
            </>
          )}
        </section>
      </main>
    </StorefrontShell>
  );
}
