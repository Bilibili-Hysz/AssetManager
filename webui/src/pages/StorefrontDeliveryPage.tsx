import { ArrowLeft, Clock3, Download, FileArchive, RefreshCw, ShieldCheck } from 'lucide-react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { BuyerDeliveryDownloadButton } from '../components/storefront/BuyerDeliveryDownloadButton';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { createShopApi } from '../api/shop';
import { useAuth } from '../hooks/useAuth';
import { useI18n } from '../hooks/useI18n';

import type { DeliveryInfo, ShopBuyerOrder } from '../types/api';


export default function StorefrontDeliveryPage() {
  const { api } = useAuth();
  const { t } = useI18n();
  const { token } = useParams<{ token: string }>();
  const [searchParams] = useSearchParams();
  // The route parameter is named `:token` but carries the order id in the new
  // share-claim link format; the mode is chosen by the presence of `?claim=`.
  const claim = searchParams.get('claim');
  const shopApi = useMemo(() => createShopApi(api), [api]);
  const [delivery, setDelivery] = useState<DeliveryInfo | null>(null);
  const [claimOrder, setClaimOrder] = useState<ShopBuyerOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [claimFailed, setClaimFailed] = useState(false);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    if (!token) {
      // A missing token must not leave the page stuck in the loading state.
      setDelivery(null);
      setClaimOrder(null);
      setLoadFailed(false);
      setClaimFailed(false);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadFailed(false);
    setClaimFailed(false);
    if (claim) {
      // New one-time share claim flow: the claim is exchanged for the order
      // receipt cookie, then the order loads through the receipt channel.
      shopApi.claimDelivery(token, claim)
        .then(() => shopApi.getOrder(token))
        .then(value => { if (!cancelled) { setClaimOrder(value.order); setClaimFailed(false); } })
        .catch(() => { if (!cancelled) { setClaimOrder(null); setClaimFailed(true); } })
        .finally(() => { if (!cancelled) setLoading(false); });
    } else {
      // Legacy bearer-token delivery link, kept for older share links.
      shopApi.getDelivery(token)
        .then(value => { if (!cancelled) { setDelivery(value); setLoadFailed(false); } })
        .catch(() => { if (!cancelled) { setDelivery(null); setLoadFailed(true); } })
        .finally(() => { if (!cancelled) setLoading(false); });
    }
    return () => { cancelled = true; };
  }, [claim, retryToken, shopApi, token]);

  const downloadUrl = !claim && token ? shopApi.deliveryDownloadUrl(token) : '#';

  return (
    <StorefrontShell storeName={t('commerce.store')}>
      <main className="storefront-main">
        <Link className="storefront-link" to="/storefront"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link>
        <section className="storefront-delivery-card" aria-labelledby="delivery-title">
          <span className="seller-login-icon"><ShieldCheck size={22} /></span>
          <p className="storefront-eyebrow"><FileArchive size={14} /> {t('commerce.instant_access')}</p>
          <h1 id="delivery-title">
            {loading
              ? t('browse.loading')
              : claim
                ? claimOrder?.item_title ?? t('commerce.product_not_found')
                : delivery?.filename ?? t('commerce.product_not_found')}
          </h1>
          {!loading && claim ? (
            claimFailed ? (
              <div role="alert" style={{ display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'flex-start' }}>
                <p>{t('commerce.delivery_claim_invalid')}</p>
                <button type="button" className="storefront-button storefront-button-ghost" onClick={() => setRetryToken(value => value + 1)}>
                  <RefreshCw size={15} /> {t('gallery.retry')}
                </button>
              </div>
            ) : claimOrder ? (
              <>
                <p>{claimOrder.delivery_available ? t('commerce.digital_asset') : t('commerce.download_started')}</p>
                {claimOrder.status === 'fulfilled' && claimOrder.delivery_available ? (
                  <BuyerDeliveryDownloadButton
                    orderId={claimOrder.id}
                    itemTitle={claimOrder.item_title}
                    shop={shopApi}
                    label={t('action.download')}
                    loadingLabel={t('browse.loading')}
                  />
                ) : (
                  <p className="storefront-checkout-note"><Clock3 size={15} /> {t('commerce.instant_access')}</p>
                )}
              </>
            ) : (
              <p role="alert">{t('commerce.product_not_found_description')}</p>
            )
          ) : !loading && delivery ? (
            <>
              <p>{delivery.is_directory ? t('commerce.digital_asset') : t('commerce.download_started')}</p>
              <a className="storefront-button storefront-button-primary" href={downloadUrl}><Download size={16} /> {t('action.download')}</a>
              <small className="storefront-delivery-meta">{delivery.order.download_count ?? 0} / {delivery.order.max_downloads ?? 0}</small>
            </>
          ) : !loading && loadFailed ? (
            <div role="alert" style={{ display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'flex-start' }}>
              <p>{t('commerce.delivery_load_failed')}</p>
              <button type="button" className="storefront-button storefront-button-ghost" onClick={() => setRetryToken(value => value + 1)}>
                <RefreshCw size={15} /> {t('gallery.retry')}
              </button>
            </div>
          ) : !loading ? <p role="alert">{t('commerce.product_not_found_description')}</p> : null}
        </section>
      </main>
    </StorefrontShell>
  );
}
