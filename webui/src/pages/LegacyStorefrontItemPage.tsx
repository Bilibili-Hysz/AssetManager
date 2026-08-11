import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ExternalLink, FileText, Image as ImageIcon, ShoppingCart } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { createMetadataApi } from '../api/metadata';
import { createShopApi } from '../api/shop';
import { useAuth } from '../hooks/useAuth';
import { useI18n } from '../hooks/useI18n';
import type { ProjectDetail, ShopItem } from '../types/api';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { ImageViewer } from '../components/viewer/ImageViewer';
import { formatMoney } from '../components/storefront/types';

function decodeRouteValue(value: string): string {
  try { return decodeURIComponent(value); } catch { return value; }
}

function safeExternalUrl(value: string): boolean {
  try {
    const protocol = new URL(value).protocol;
    return protocol === 'http:' || protocol === 'https:';
  } catch { return false; }
}

export default function LegacyStorefrontItemPage() {
  const { api } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const params = useParams();
  const path = decodeRouteValue(params['*'] ?? '');
  const metadataApi = useMemo(() => createMetadataApi(api), [api]);
  const shopApi = useMemo(() => createShopApi(api), [api]);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [shopItem, setShopItem] = useState<ShopItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [orderLoading, setOrderLoading] = useState(false);
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setDetail(null);
    setShopItem(null);
    Promise.all([
      path ? metadataApi.getProjectDetail(path, controller.signal) : Promise.reject(new Error('Missing asset path')),
      shopApi.list('active').catch(() => ({ items: [] as ShopItem[] })),
    ]).then(([nextDetail, shopResponse]) => {
      if (controller.signal.aborted) return;
      setDetail(nextDetail);
      const matching = shopResponse.items.find(item => item.path === path && item.enabled && item.status === 'active');
      setShopItem(matching ?? null);
    }).catch(() => {
      if (!controller.signal.aborted) setDetail(null);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [metadataApi, path, shopApi]);

  const images = useMemo(() => detail?.images.map(image => image.url).filter(Boolean) ?? [], [detail]);
  const externalUrls = detail?.urls.filter(safeExternalUrl) ?? [];
  const createOrder = useCallback(async () => {
    if (!shopItem || orderLoading) return;
    setOrderLoading(true);
    try {
      const response = await shopApi.createOrder(shopItem.id);
      navigate(`/storefront/checkout/${encodeURIComponent(response.order.id)}`);
    } catch {
      setOrderLoading(false);
    }
  }, [navigate, orderLoading, shopApi, shopItem]);

  return (
    <StorefrontShell>
      <main className="storefront-main">
        <Link className="storefront-link" to="/storefront"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link>
        {loading ? <p style={{ marginTop: 24, color: 'var(--color-text-secondary)' }}>{t('gallery.loading')}</p> : detail ? <>
          <section className="storefront-detail" style={{ marginTop: 18 }}>
            <div className="storefront-detail-gallery">
              {images.length > 0 ? <button type="button" className="storefront-detail-image" onClick={() => setViewerIndex(0)}><img src={images[0]} alt={detail.name} /></button> : <div className="storefront-detail-image" style={{ display: 'grid', placeItems: 'center', minHeight: 260, color: 'var(--color-text-muted)' }}><ImageIcon size={42} /></div>}
              {images.length > 1 && <div className="storefront-detail-thumbs">{images.map((image, index) => <button key={image} type="button" onClick={() => setViewerIndex(index)} style={{ padding: 0, border: 0, background: 'transparent', cursor: 'pointer' }}><img src={image} alt={`${detail.name} ${index + 1}`} /></button>)}</div>}
            </div>
            <div className="storefront-detail-copy">
              <p className="storefront-eyebrow"><FileText size={14} /> {t('commerce.digital_asset')}</p>
              <h1>{detail.name}</h1>
              <p className="storefront-detail-description">{detail.notes || detail.path}</p>
              <div className="storefront-detail-actions">
                {shopItem ? <button type="button" className="storefront-button storefront-button-primary" onClick={() => { void createOrder(); }} disabled={orderLoading}><ShoppingCart size={16} /> {orderLoading ? t('browse.loading') : `${t('commerce.buy_now')} · ${formatMoney(shopItem.price_cents / 100, shopItem.currency)}`}</button> : detail.download_url ? <a className="storefront-button storefront-button-primary" href={detail.download_url}><FileText size={16} /> {t('action.download')}</a> : <Link className="storefront-button storefront-button-primary" to={`/detail?path=${encodeURIComponent(detail.path)}&from=gallery`}><FileText size={16} /> {t('action.detail')}</Link>}
                <Link className="storefront-button storefront-button-ghost" to={`/detail?path=${encodeURIComponent(detail.path)}&from=gallery`}>{t('action.detail')}</Link>
              </div>
              {externalUrls.length > 0 && <div style={{ display: 'grid', gap: 8, marginTop: 24 }}><strong>{t('info.urls')}</strong>{externalUrls.map(url => <a key={url} className="storefront-link" href={url} target="_blank" rel="noreferrer"><ExternalLink size={14} /> {url}</a>)}</div>}
              {detail.tags.length > 0 && <p style={{ marginTop: 24, color: 'var(--color-text-secondary)', fontSize: 13 }}>{t('info.tags')}: {detail.tags.join(', ')}</p>}
            </div>
          </section>
          {viewerIndex !== null && <ImageViewer images={images} currentIndex={viewerIndex} onClose={() => setViewerIndex(null)} />}
        </> : <div className="storefront-empty" style={{ marginTop: 24 }}><h3>{t('commerce.product_not_found')}</h3><p>{t('commerce.product_not_found_description')}</p><Link className="storefront-button storefront-button-ghost" to="/storefront">{t('commerce.browse')}</Link></div>}
      </main>
    </StorefrontShell>
  );
}
