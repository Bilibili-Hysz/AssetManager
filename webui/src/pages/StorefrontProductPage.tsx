import { ArrowLeft, Check, Download, Heart, ImageIcon, ShieldCheck, ShoppingCart, Sparkles } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { ImageViewer } from '../components/viewer/ImageViewer';
import { Modal } from '../components/ui/Modal';
import { useToast } from '../components/ui/Toast';
import { useI18n } from '../hooks/useI18n';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { formatMoney, type StorefrontProduct } from '../components/storefront/types';
import { canonicalizeShopPath, toStorefrontProduct, useCommerceCatalog } from '../hooks/useCommerce';
import { isApiError } from '../api/errors';
import { useAuth } from '../hooks/useAuth';
import { useShopApi } from '../hooks/usePageApis';
import { useShopBuyer } from '../stores/ShopBuyerContext';

export interface StorefrontProductPageProps { product?: StorefrontProduct; }

export default function StorefrontProductPage({ product }: StorefrontProductPageProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const { api } = useAuth();
  const shopApi = useShopApi();
  const { id, '*': wildcardPath } = useParams<{ id?: string; '*': string }>();
  const navigate = useNavigate();
  const catalog = useCommerceCatalog();
  const { addToCart, addToWishlist, removeFromWishlist, isWishlisted, refreshCart } = useShopBuyer();
  const [cartAdding, setCartAdding] = useState(false);
  const [wishlistPending, setWishlistPending] = useState(false);
  const [orderCreating, setOrderCreating] = useState(false);
  const [detailProduct, setDetailProduct] = useState<StorefrontProduct | null>(null);
  const [detailRequestKey, setDetailRequestKey] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<unknown>(null);
  const [detailRetryToken, setDetailRetryToken] = useState(0);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [purchaseOpen, setPurchaseOpen] = useState(false);
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);
  const isPathRoute = wildcardPath !== undefined;
  const detailCandidateRaw = (isPathRoute ? wildcardPath : id)?.trim() ?? '';
  const detailCandidate = isPathRoute ? canonicalizeShopPath(detailCandidateRaw) ?? '' : detailCandidateRaw;
  const catalogProduct = product ?? catalog.products.find(candidate => isPathRoute
    ? canonicalizeShopPath(candidate.slug) === detailCandidate
    : candidate.id === detailCandidate || candidate.slug === detailCandidate);
  const shouldLoadDetail = Boolean(
    !product &&
    !catalog.loading &&
    !catalog.error &&
    !catalogProduct &&
    detailCandidate &&
    (isPathRoute || /^\d+$/.test(detailCandidate)),
  );
  useEffect(() => {
    let cancelled = false;
    if (!shouldLoadDetail) {
      setDetailProduct(null);
      setDetailRequestKey(null);
      setDetailLoading(false);
      setDetailError(null);
      return () => { cancelled = true; };
    }
    setDetailRequestKey(detailCandidate);
    setDetailProduct(null);
    setDetailLoading(true);
    setDetailError(null);
    const request = isPathRoute
      ? shopApi.getItemByPath(detailCandidate)
      : shopApi.getItem(detailCandidate);
    void request
      .then(response => {
        if (cancelled) return;
        setDetailProduct(toStorefrontProduct(response.item, api.buildUrl));
      })
      .catch(reason => {
        if (cancelled) return;
        setDetailProduct(null);
        if (isApiError(reason) && reason.status === 404) {
          setDetailError(null);
        } else {
          setDetailError(reason);
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => { cancelled = true; };
  }, [api, catalog.error, catalog.loading, catalogProduct?.id, detailCandidate, detailRetryToken, isPathRoute, shopApi, shouldLoadDetail]);
  const detailMatchesRoute = detailProduct != null && (
    isPathRoute ? canonicalizeShopPath(detailProduct.slug) === detailCandidate : detailProduct.id === detailCandidate
  );
  const resolvedProduct = catalogProduct ?? (detailMatchesRoute ? detailProduct : null);
  const detailStateMatches = detailRequestKey === detailCandidate;
  const detailPending = shouldLoadDetail && (!detailStateMatches || detailLoading);
  useEffect(() => {
    setSelectedImageIndex(0);
    setViewerOpen(false);
  }, [resolvedProduct?.id]);
  if (!product && catalog.loading) return <StorefrontShell><main className="storefront-main"><div className="storefront-empty" role="status" aria-busy="true"><p>{t('commerce.product_loading')}</p></div></main></StorefrontShell>;
  if (!product && catalog.error) return <StorefrontShell><main className="storefront-main"><div className="storefront-empty" role="alert"><h3>{t('commerce.product_load_failed')}</h3><p>{t('commerce.product_load_failed_description')}</p><button type="button" className="storefront-button storefront-button-ghost" onClick={() => void catalog.refresh()}>{t('gallery.retry')}</button></div></main></StorefrontShell>;
  if (!resolvedProduct && detailPending) return <StorefrontShell><main className="storefront-main"><div className="storefront-empty" role="status" aria-busy="true"><p>{t('commerce.product_loading')}</p></div></main></StorefrontShell>;
  if (!resolvedProduct && detailStateMatches && detailError) return <StorefrontShell><main className="storefront-main"><div className="storefront-empty" role="alert"><h3>{t('commerce.product_load_failed')}</h3><p>{t('commerce.product_load_failed_description')}</p><button type="button" className="storefront-button storefront-button-ghost" onClick={() => setDetailRetryToken(value => value + 1)}>{t('gallery.retry')}</button></div></main></StorefrontShell>;
  if (!resolvedProduct) return <StorefrontShell><main className="storefront-main"><div className="storefront-empty"><h3>{t('commerce.product_not_found')}</h3><p>{t('commerce.product_not_found_description')}</p><Link className="storefront-button storefront-button-ghost" to="/storefront/products"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link></div></main></StorefrontShell>;
  const images = Array.from(new Set([resolvedProduct.imageUrl, ...(resolvedProduct.gallery ?? [])].filter(Boolean)));
  const activeImageIndex = Math.min(selectedImageIndex, Math.max(images.length - 1, 0));
  const activeImage = images[activeImageIndex] ?? resolvedProduct.imageUrl;
  const isFree = resolvedProduct.price === 0;
  const createOrder = async () => {
    if (orderCreating) return;
    setOrderCreating(true);
    try {
      const result = await shopApi.createOrder(resolvedProduct.id);
      setPurchaseOpen(false);
      navigate(`/storefront/checkout/${encodeURIComponent(result.order.id)}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.product_not_found_description'), 'error');
    } finally {
      setOrderCreating(false);
    }
  };
  const action = () => {
    if (isFree) { void createOrder(); return; }
    setPurchaseOpen(true);
  };
  const handleAddToCart = async () => {
    if (cartAdding) return;
    setCartAdding(true);
    try {
      await addToCart(resolvedProduct.id);
      showToast(t('commerce.added_to_cart'), 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.cart_update_failed'), 'error');
      // A rejected add (e.g. a 409 price conflict) can leave the local cart
      // state stale; re-sync from the server like the cart page does.
      await refreshCart().catch(() => undefined);
    } finally {
      setCartAdding(false);
    }
  };
  const handleWishlist = async () => {
    if (wishlistPending) return;
    setWishlistPending(true);
    try {
      if (isWishlisted(resolvedProduct.id)) {
        await removeFromWishlist(resolvedProduct.id);
        showToast(t('commerce.removed_from_wishlist'), 'info');
      } else {
        await addToWishlist(resolvedProduct.id);
        showToast(t('commerce.saved_to_wishlist'), 'success');
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.wishlist_update_failed'), 'error');
    } finally {
      setWishlistPending(false);
    }
  };
  return <StorefrontShell storeName={t('commerce.store')}>
    <main className="storefront-main">
      <Link className="storefront-link" to="/storefront"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link>
       <section className="storefront-detail" style={{ marginTop: 18 }}>
         <div className="storefront-detail-gallery">
           {activeImage ? <button type="button" className="storefront-detail-image" onClick={() => setViewerOpen(true)}><img src={activeImage} alt={resolvedProduct.name} /></button> : <div className="storefront-detail-image storefront-detail-image-placeholder" aria-label={t('commerce.digital_asset')}><ImageIcon size={42} /></div>}
           {images.length > 1 && <div className="storefront-detail-thumbs" role="list" aria-label={t('detail.images')}>
             {images.map((image, index) => <button key={image} type="button" className={`storefront-detail-thumb${index === activeImageIndex ? ' is-active' : ''}`} onClick={() => setSelectedImageIndex(index)} aria-label={`${resolvedProduct.name} ${index + 1}`} aria-pressed={index === activeImageIndex}><img src={image} alt="" /></button>)}
           </div>}
         </div>
         <div className="storefront-detail-copy"><p className="storefront-eyebrow"><Sparkles size={14} /> {resolvedProduct.category ?? t('commerce.digital_asset')}</p><h1>{resolvedProduct.name}</h1><p className="storefront-detail-description">{resolvedProduct.description ?? t('commerce.product_description_fallback')}</p><div className="storefront-detail-price"><strong>{isFree ? t('commerce.free') : formatMoney(resolvedProduct.price, resolvedProduct.currency)}</strong><span>{resolvedProduct.license ?? t('commerce.standard_license')}</span></div><div className="storefront-detail-actions"><button type="button" className="storefront-button storefront-button-primary" onClick={action} disabled={orderCreating}>{isFree ? <Download size={16} /> : <ShoppingCart size={16} />} {orderCreating ? t('browse.loading') : isFree ? t('commerce.get_asset') : t('commerce.buy_now')}</button><button type="button" className="storefront-button storefront-button-ghost" onClick={() => void handleAddToCart()} disabled={cartAdding}><ShoppingCart size={16} /> {cartAdding ? t('browse.loading') : t('commerce.add_to_cart')}</button><button type="button" className={`storefront-heart-button${isWishlisted(resolvedProduct.id) ? ' is-active' : ''}`} onClick={() => void handleWishlist()} aria-label={t('commerce.save')} aria-pressed={isWishlisted(resolvedProduct.id)} disabled={wishlistPending}><Heart size={17} fill={isWishlisted(resolvedProduct.id) ? 'currentColor' : 'none'} /></button></div><div className="storefront-detail-perks"><span><ShieldCheck size={16} /> {t('commerce.secure_checkout')}</span><span><Check size={16} /> {t('commerce.instant_access')}</span></div><div className="storefront-detail-downloads"><Download size={15} /> {t('commerce.downloads_count', resolvedProduct.downloads ?? 0)}</div></div>
      </section>
    </main>
     {viewerOpen && images.length > 0 && <ImageViewer images={images} currentIndex={activeImageIndex} onClose={() => setViewerOpen(false)} />}
    <Modal open={purchaseOpen} onClose={() => setPurchaseOpen(false)} title={t('commerce.confirm_purchase')}><p style={{ color: 'var(--color-text-secondary)', lineHeight: 1.6 }}>{t('commerce.purchase_summary', resolvedProduct.name, formatMoney(resolvedProduct.price, resolvedProduct.currency))}</p><div className="storefront-modal-actions"><button type="button" className="storefront-button storefront-button-ghost" onClick={() => setPurchaseOpen(false)}>{t('action.cancel')}</button><button type="button" className="storefront-button storefront-button-primary" onClick={() => { void createOrder(); }} disabled={orderCreating}>{orderCreating ? t('browse.loading') : t('commerce.continue')}</button></div></Modal>
  </StorefrontShell>;
}



