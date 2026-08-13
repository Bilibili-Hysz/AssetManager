import { Clipboard, Download, ExternalLink, Search, XCircle } from 'lucide-react';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { formatMoney, type SellerPageProps } from '../components/storefront/types';
import { useI18n } from '../hooks/useI18n';
import { useCommerceOrders } from '../hooks/useCommerce';
import { useMemo, useState } from 'react';
import { createShopApi } from '../api/shop';
import { useAuth } from '../hooks/useAuth';
import { useToast } from '../components/ui/Toast';
import type { FulfillOrderResponse } from '../types/api';

/**
 * Build the buyer-facing share link for a fulfilled order. New backends return
 * a one-time share claim; the link then points at the storefront delivery page
 * (order id in the route, claim in the query string). Legacy backends without
 * share_claim keep the old bearer delivery URL.
 */
function buildShareDeliveryUrl(result: FulfillOrderResponse, fallbackOrderId: string): string {
  const orderId = String(result.order?.id ?? fallbackOrderId);
  if (result.share_claim) {
    return new URL(
      `/storefront/delivery/${orderId}?claim=${encodeURIComponent(result.share_claim)}`,
      window.location.origin,
    ).toString();
  }
  return new URL(result.delivery_url, window.location.origin).toString();
}

export default function SellerOrdersPage({ seller, orders = [] }: SellerPageProps) {
  const { t } = useI18n();
  const { api } = useAuth();
  const { showToast } = useToast();
  const commerceOrders = useCommerceOrders();
  const visibleOrders = orders.length > 0 ? orders : commerceOrders.orders;
  const shopApi = useMemo(() => createShopApi(api), [api]);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [deliveryLinks, setDeliveryLinks] = useState<Record<string, string>>({});
  const visible = useMemo(() => visibleOrders.filter(order => (status === 'all' || order.status === status) && order.productName.toLowerCase().includes(query.toLowerCase())), [visibleOrders, query, status]);

  const fulfill = async (id: string) => {
    if (pendingId) return;
    setPendingId(id);
    try {
      const result = await shopApi.fulfillOrder(id);
      const deliveryUrl = buildShareDeliveryUrl(result, id);
      setDeliveryLinks(current => ({ ...current, [id]: deliveryUrl }));
      try { await navigator.clipboard?.writeText(deliveryUrl); } catch { /* keep the visible link as a fallback */ }
      await commerceOrders.refresh();
      showToast(t('seller.delivery_link_ready'), 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.product_not_found_description'), 'error');
    } finally {
      setPendingId(null);
    }
  };

  const recoverDelivery = async (id: string) => {
    if (pendingId) return;
    setPendingId(id);
    try {
      const result = await shopApi.rotateDelivery(id);
      const deliveryUrl = buildShareDeliveryUrl(result, id);
      setDeliveryLinks(current => ({ ...current, [id]: deliveryUrl }));
      try { await navigator.clipboard?.writeText(deliveryUrl); } catch { /* keep the visible link as a fallback */ }
      await commerceOrders.refresh();
      showToast(t('seller.delivery_link_recovered'), 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.product_not_found_description'), 'error');
    } finally {
      setPendingId(null);
    }
  };

  const revoke = async (id: string) => {
    if (pendingId) return;
    setPendingId(id);
    try {
      await shopApi.revokeOrder(id);
      await commerceOrders.refresh();
      showToast(t('seller.settings_saved'), 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.product_not_found_description'), 'error');
    } finally {
      setPendingId(null);
    }
  };

  return <StorefrontShell sellerMode storeName={seller?.storeName ?? t('seller.portal')}>
    <main className="seller-main">
      <div className="seller-page-heading"><div><p className="storefront-eyebrow">{t('seller.activity')}</p><h1>{t('seller.orders_title')}</h1><p>{t('seller.orders_subtitle')}</p></div><a className="storefront-button storefront-button-ghost" href={shopApi.exportOrdersUrl()}><Download size={15} /> {t('seller.export_orders')}</a></div>
      <section className="seller-panel"><div className="seller-filter-bar"><div className="seller-filter-buttons">{['all', 'paid', 'pending', 'refunded'].map(value => <button key={value} type="button" className={status === value ? 'is-active' : ''} aria-pressed={status === value} onClick={() => setStatus(value)}>{value === 'all' ? t('seller.filter_all') : t(`seller.status_${value}`)}</button>)}</div><label className="seller-search"><Search size={14} /><span className="sr-only">{t('commerce.search')}</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder={t('seller.search_orders')} /></label></div>
        <div className="seller-table-wrap"><table className="seller-table"><thead><tr><th>{t('seller.order')}</th><th>{t('seller.product')}</th><th>{t('seller.amount')}</th><th>{t('seller.status')}</th><th>{t('seller.date')}</th><th aria-label={t('seller.actions')} /></tr></thead><tbody>{visible.map(order => <tr key={order.id}><td>#{order.id}</td><td>{order.productName}</td><td>{formatMoney(order.amount, order.currency)}</td><td><span className={`seller-status seller-status-${order.status}`}>{t(`seller.status_${order.status}`)}</span></td><td>{order.createdAt}</td><td><div className="seller-row-actions">{order.sourceStatus === 'confirmed' && <button type="button" disabled={pendingId === order.id} className="seller-row-action seller-row-action-success" onClick={() => void fulfill(order.id)}><Clipboard size={13} /> {t('seller.status_paid')}</button>}{order.sourceStatus === 'fulfilled' && <button type="button" disabled={pendingId === order.id} className="seller-row-action seller-row-action-success" onClick={() => void recoverDelivery(order.id)}><Clipboard size={13} /> {t('seller.recover_delivery')}</button>}{(order.sourceStatus === 'pending' || order.sourceStatus === 'confirmed') && <button type="button" disabled={pendingId === order.id} className="seller-row-action seller-row-action-danger" onClick={() => void revoke(order.id)}><XCircle size={13} /> {t('seller.status_refunded')}</button>}{deliveryLinks[order.id] && <a className="seller-row-action" href={deliveryLinks[order.id]} target="_blank" rel="noreferrer"><ExternalLink size={13} /> {t('seller.delivery_link')}</a>}</div></td></tr>)}</tbody></table>{visible.length === 0 && <div style={{ padding: 24 }}><p style={{ color: 'var(--color-text-muted)', fontSize: 13, textAlign: 'center' }}>{t('seller.no_orders')}</p></div>}</div>
      </section>
    </main>
  </StorefrontShell>;
}
