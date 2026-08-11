import { AlertCircle, ArrowLeft, ExternalLink, KeyRound, PackageSearch } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { formatMoney } from '../components/storefront/types';
import { createShopApi } from '../api/shop';
import { useAuth } from '../hooks/useAuth';
import { useI18n } from '../hooks/useI18n';
import type { ShopBuyerOrder, ShopOrderStatus } from '../types/api';

const ORDER_LIMIT = 50;
const statuses: Array<ShopOrderStatus | ''> = ['', 'pending', 'confirmed', 'fulfilled', 'revoked'];

function statusLabel(status: ShopOrderStatus, t: (key: string) => string): string {
  return t(`commerce.status_${status}`);
}

function orderQuantity(order: ShopBuyerOrder): number {
  return Number.isFinite(order.quantity) && (order.quantity ?? 0) > 0 ? order.quantity! : 1;
}

function formatOrderDate(timestamp: number): string {
  const milliseconds = timestamp > 1_000_000_000_000 ? timestamp : timestamp * 1000;
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(milliseconds));
}

export default function StorefrontBuyerOrdersPage() {
  const { t } = useI18n();
  const { api } = useAuth();
  const shop = useMemo(() => createShopApi(api), [api]);
  const [status, setStatus] = useState<ShopOrderStatus | ''>('');
  const [orders, setOrders] = useState<ShopBuyerOrder[]>([]);
  const [total, setTotal] = useState<number | undefined>();
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadRetryToken, setLoadRetryToken] = useState(0);
  const [recoveringId, setRecoveringId] = useState<number | null>(null);
  const [recoveredIds, setRecoveredIds] = useState<Set<number>>(() => new Set());
  const [recoveryFailedId, setRecoveryFailedId] = useState<number | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreFailed, setLoadMoreFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadFailed(false);
    // Pagination note: listBuyerOrders caps each request at ORDER_LIMIT (50)
    // orders and accepts no cursor/offset parameter, even though the response
    // can carry a next_cursor. A "load more" flow would require the backend to
    // accept a cursor on shop/buyer/orders; until then the frontend reloads
    // the first page (and a retry is offered when the load fails).
    void shop.listBuyerOrders(status || undefined, ORDER_LIMIT)
      .then(response => {
        if (cancelled) return;
        setOrders(response.orders ?? []);
        setTotal(response.total);
        setNextCursor(response.next_cursor ?? null);
        setLoadMoreFailed(false);
      })
      .catch(() => {
        if (cancelled) return;
        setOrders([]);
        setTotal(undefined);
        setNextCursor(null);
        setLoadFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [loadRetryToken, shop, status]);

  const loadMore = async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setLoadMoreFailed(false);
    try {
      const response = await shop.listBuyerOrders(status || undefined, ORDER_LIMIT, nextCursor);
      setOrders(prev => [...prev, ...(response.orders ?? [])]);
      setNextCursor(response.next_cursor ?? null);
    } catch {
      setLoadMoreFailed(true);
    } finally {
      setLoadingMore(false);
    }
  };

  const recoverReceipt = async (orderId: number) => {
    setRecoveringId(orderId);
    setRecoveryFailedId(null);
    try {
      await shop.recoverOrderReceipt(orderId);
      setRecoveredIds(current => new Set(current).add(orderId));
    } catch {
      setRecoveryFailedId(orderId);
    } finally {
      setRecoveringId(null);
    }
  };

  return (
    <StorefrontShell storeName={t('commerce.store')}>
      <main className="storefront-main storefront-buyer-page">
        <Link className="storefront-link" to="/storefront"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link>
        <div className="storefront-page-intro">
          <div>
            <p className="storefront-eyebrow"><PackageSearch size={14} /> {t('commerce.buyer_orders')}</p>
            <h1>{t('commerce.buyer_orders')}</h1>
            <p>{t('commerce.buyer_orders_description')}</p>
          </div>
          {!loading && !loadFailed && typeof total === 'number' && (
            <span className="storefront-result-count">{t('commerce.buyer_orders_total', total)}</span>
          )}
        </div>

        <section className="storefront-buyer-panel" aria-labelledby="buyer-orders-heading">
          <h2 id="buyer-orders-heading" className="sr-only">{t('commerce.buyer_orders')}</h2>
          <div className="storefront-toolbar">
            <label className="storefront-sort" htmlFor="buyer-orders-status">
              {t('commerce.buyer_orders_filter')}
              <select id="buyer-orders-status" value={status} onChange={event => setStatus(event.target.value as ShopOrderStatus | '')}>
                {statuses.map(value => (
                  <option key={value || 'all'} value={value}>{value ? statusLabel(value, t) : t('commerce.buyer_orders_all')}</option>
                ))}
              </select>
            </label>
          </div>

          {loading ? (
            <div className="storefront-empty" role="status"><p>{t('commerce.buyer_orders_loading')}</p></div>
          ) : loadFailed ? (
            <div className="storefront-empty" role="alert"><AlertCircle size={28} /><h3>{t('commerce.buyer_orders_load_failed')}</h3><button type="button" className="storefront-button storefront-button-primary" onClick={() => setLoadRetryToken(value => value + 1)}>{t('gallery.retry')}</button></div>
          ) : orders.length === 0 ? (
            <div className="storefront-empty" role="status"><PackageSearch size={28} /><h3>{t('commerce.buyer_orders_empty')}</h3><p>{t('commerce.buyer_orders_empty_description')}</p><Link className="storefront-button storefront-button-primary" to="/storefront/products">{t('commerce.continue_shopping')}</Link></div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', minWidth: 680, borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left', color: 'var(--color-text-secondary)' }}>
                    <th style={{ padding: '0 12px 12px 0', fontWeight: 600 }}>{t('commerce.order_title')}</th>
                    <th style={{ padding: '0 12px 12px', fontWeight: 600 }}>{t('commerce.quantity')}</th>
                    <th style={{ padding: '0 12px 12px', fontWeight: 600 }}>{t('commerce.order_amount')}</th>
                    <th style={{ padding: '0 12px 12px', fontWeight: 600 }}>{t('commerce.order_status')}</th>
                    <th style={{ padding: '0 12px 12px', fontWeight: 600 }}>{t('commerce.order_date')}</th>
                    <th style={{ padding: '0 0 12px 12px', fontWeight: 600, textAlign: 'right' }} />
                  </tr>
                </thead>
                <tbody>
                  {orders.map(order => (
                    <tr key={order.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                      <td style={{ padding: '16px 12px 16px 0', color: 'var(--color-text)', fontWeight: 650 }}>{order.item_title}</td>
                      <td style={{ padding: '16px 12px', color: 'var(--color-text-secondary)' }}>{orderQuantity(order)}</td>
                      <td style={{ padding: '16px 12px', color: 'var(--color-text)' }}>{formatMoney(order.amount_cents / 100, order.currency)}</td>
                      <td style={{ padding: '16px 12px' }}><span className={`seller-status seller-status-${order.status}`}>{statusLabel(order.status, t)}</span></td>
                      <td style={{ padding: '16px 12px', color: 'var(--color-text-secondary)', whiteSpace: 'nowrap' }}>{formatOrderDate(order.created_at)}</td>
                      <td style={{ padding: '16px 0 16px 12px', textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                          <Link className="storefront-button storefront-button-ghost" style={{ minHeight: 34, padding: '0 10px', fontSize: 12 }} to={`/storefront/checkout/${encodeURIComponent(String(order.id))}`}><ExternalLink size={14} /> {t('commerce.buyer_orders_view')}</Link>
                          {order.status !== 'revoked' && !recoveredIds.has(order.id) && (
                            <button type="button" className="storefront-button storefront-button-ghost" style={{ minHeight: 34, padding: '0 10px', fontSize: 12 }} disabled={recoveringId === order.id} onClick={() => void recoverReceipt(order.id)}>
                              <KeyRound size={14} /> {recoveringId === order.id ? t('commerce.buyer_orders_loading') : t('commerce.buyer_orders_recover')}
                            </button>
                          )}
                          {recoveredIds.has(order.id) && <span role="status" style={{ color: 'var(--color-success)', fontSize: 12 }}>{t('commerce.buyer_orders_recovered')}</span>}
                          {recoveryFailedId === order.id && <span role="alert" style={{ color: 'var(--color-danger)', fontSize: 12 }}>{t('commerce.buyer_orders_recover_failed')}</span>}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {nextCursor && (
                <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 16 }}>
                  {loadMoreFailed ? (
                    <button type="button" className="storefront-button storefront-button-ghost" onClick={() => void loadMore()}>
                      {t('gallery.retry')}
                    </button>
                  ) : (
                    <button type="button" className="storefront-button storefront-button-ghost" disabled={loadingMore} onClick={() => void loadMore()}>
                      {loadingMore ? t('commerce.buyer_orders_loading') : t('commerce.load_more')}
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      </main>
    </StorefrontShell>
  );
}
