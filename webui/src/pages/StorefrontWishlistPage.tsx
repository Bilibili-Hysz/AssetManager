import { ArrowLeft, Heart, ImageIcon, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { useShopBuyer } from '../components/storefront/ShopBuyerContext';
import { useAuth } from '../hooks/useAuth';
import { assetThumbnailUrl } from '../hooks/useCommerce';
import { useI18n } from '../hooks/useI18n';
import { useToast } from '../components/ui/Toast';
import { formatMoney } from '../components/storefront/types';

export default function StorefrontWishlistPage() {
  const { t } = useI18n();
  const { api } = useAuth();
  const { showToast } = useToast();
  const { wishlist, wishlistLoading, refreshWishlist, removeFromWishlist, clearWishlist } = useShopBuyer();
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadRetryToken, setLoadRetryToken] = useState(0);

  useEffect(() => {
    if (wishlist.length === 0) {
      setLoadFailed(false);
      void refreshWishlist().catch(() => setLoadFailed(true));
    }
  }, [loadRetryToken, refreshWishlist, wishlist.length]);

  const remove = async (itemId: number) => {
    try {
      await removeFromWishlist(itemId);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.wishlist_update_failed'), 'error');
    }
  };

  const clear = async () => {
    try {
      await clearWishlist();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.wishlist_update_failed'), 'error');
    }
  };

  return (
    <StorefrontShell storeName={t('commerce.store')}>
      <main className="storefront-main storefront-buyer-page">
        <Link className="storefront-link" to="/storefront"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link>
        <div className="storefront-page-intro">
          <div>
            <p className="storefront-eyebrow"><Heart size={14} /> {t('commerce.wishlist')}</p>
            <h1>{t('commerce.wishlist_title')}</h1>
            <p>{t('commerce.wishlist_description')}</p>
          </div>
          {wishlist.length > 0 && <button type="button" className="storefront-button storefront-button-ghost" onClick={() => void clear()}><Trash2 size={15} /> {t('commerce.clear_wishlist')}</button>}
        </div>
        {wishlistLoading && wishlist.length === 0 ? <section className="storefront-buyer-panel"><p>{t('browse.loading')}</p></section> : loadFailed && wishlist.length === 0 ? (
          <section className="storefront-buyer-panel storefront-empty" role="alert"><Heart size={28} /><h3>{t('commerce.wishlist_load_failed')}</h3><button type="button" className="storefront-button storefront-button-primary" onClick={() => setLoadRetryToken(value => value + 1)}>{t('gallery.retry')}</button></section>
        ) : wishlist.length === 0 ? (
          <section className="storefront-buyer-panel storefront-empty"><Heart size={28} /><h3>{t('commerce.wishlist_empty')}</h3><p>{t('commerce.wishlist_empty_description')}</p><Link className="storefront-button storefront-button-primary" to="/storefront/products">{t('commerce.browse_assets')}</Link></section>
        ) : (
          <section className="storefront-wishlist-grid" aria-label={t('commerce.wishlist')}>
            {wishlist.map(item => {
              const available = item.availability === 'available' && item.path !== null;
              const title = item.title ?? t('commerce.product_not_found');
              const thumbnailUrl = available ? assetThumbnailUrl(item.path ?? '', 480, api.buildUrl) : '';
              return (
                <article className={`storefront-wishlist-card${available ? '' : ' is-unavailable'}`} key={item.item_id}>
                  {available ? <Link className="storefront-wishlist-image" to={`/storefront/product/${encodeURIComponent(String(item.item_id))}`}>{thumbnailUrl ? <img src={thumbnailUrl} alt="" loading="lazy" /> : <span className="storefront-line-image-placeholder" aria-hidden="true"><ImageIcon size={28} /></span>}</Link> : <div className="storefront-wishlist-image" aria-hidden="true" />}
                  <h3>{available ? <Link to={`/storefront/product/${encodeURIComponent(String(item.item_id))}`}>{title}</Link> : title}</h3>
                  <p>{available && item.price_cents !== null && item.currency ? formatMoney(item.price_cents / 100, item.currency) : t('commerce.item_unavailable')}</p>
                  <div className="storefront-wishlist-card-actions"><span>{available ? t('commerce.available') : t('commerce.unavailable')}</span><button type="button" className="storefront-line-remove" aria-label={`${t('commerce.remove_from_wishlist')} ${title}`} onClick={() => void remove(item.item_id)}><Trash2 size={15} /></button></div>
                </article>
              );
            })}
          </section>
        )}
      </main>
    </StorefrontShell>
  );
}
