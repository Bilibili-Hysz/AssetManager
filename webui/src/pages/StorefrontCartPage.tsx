import { AlertTriangle, ArrowLeft, ArrowRight, ImageIcon, Minus, Plus, ShoppingCart, Trash2 } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '../api/errors';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { formatMoney } from '../components/storefront/types';
import { useShopBuyer } from '../stores/ShopBuyerContext';
import { useAuth } from '../hooks/useAuth';
import { assetThumbnailUrl } from '../hooks/useCommerce';
import { useI18n } from '../hooks/useI18n';
import { useToast } from '../components/ui/Toast';

function createIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `cart-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function isPriceConflict(error: unknown): boolean {
  return error instanceof ApiError
    && error.status === 409
    && typeof error.body === 'object'
    && error.body !== null
    && 'code' in error.body
    && (error.body as { code?: unknown }).code === 'price_changed';
}

export default function StorefrontCartPage() {
  const { t } = useI18n();
  const { api } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const {
    cart,
    cartLoading,
    refreshCart,
    updateCartItem,
    removeCartItem,
    clearCart,
    checkout,
  } = useShopBuyer();
  const [buyerName, setBuyerName] = useState('');
  const [buyerEmail, setBuyerEmail] = useState('');
  const [checkingOut, setCheckingOut] = useState(false);
  const [priceConflict, setPriceConflict] = useState(false);
  // The checkout idempotency key must survive a remount of this page for the
  // same cart (e.g. a navigation bounce), so it is persisted per cart id in
  // sessionStorage instead of being regenerated on every mount. A new cart id
  // naturally gets a fresh key; successful checkout does not clear it.
  const idempotencyKey = useMemo(() => {
    const cartId = cart?.id;
    if (cartId == null) return null;
    const storageKey = `shop_cart_checkout_key:${cartId}`;
    try {
      const stored = sessionStorage.getItem(storageKey);
      if (stored) return stored;
      const generated = createIdempotencyKey();
      sessionStorage.setItem(storageKey, generated);
      return generated;
    } catch {
      // sessionStorage is optional; fall back to a non-persisted key so
      // checkout can still proceed.
      return createIdempotencyKey();
    }
  }, [cart?.id]);
  // Per-line in-flight lock: while a quantity update for a line is pending,
  // that row's +/- buttons and input stay disabled so the versioned backend
  // update cannot be raced by rapid clicks. lastRequestedRef remembers the
  // most recent quantity sent per line; a completing request only releases
  // the lock when it is still the latest one for that line.
  const [pendingLineIds, setPendingLineIds] = useState<ReadonlySet<number>>(() => new Set());
  const lastRequestedRef = useRef(new Map<number, number>());

  useEffect(() => {
    if (!cart && !cartLoading) void refreshCart().catch(() => undefined);
  }, [cart, cartLoading, refreshCart]);

  const totals = useMemo(() => {
    const grouped = new Map<string, number>();
    for (const line of cart?.items ?? []) {
      grouped.set(line.currency, (grouped.get(line.currency) ?? 0) + line.unit_price_cents * line.quantity);
    }
    return Array.from(grouped.entries());
  }, [cart?.items]);

  const updateQuantity = async (lineId: number, quantity: number) => {
    if (!cart || !Number.isFinite(quantity) || quantity < 1 || quantity > 999) return;
    if (pendingLineIds.has(lineId)) return;
    setPendingLineIds(current => new Set(current).add(lineId));
    lastRequestedRef.current.set(lineId, quantity);
    try {
      await updateCartItem(lineId, quantity);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.cart_update_failed'), 'error');
      await refreshCart().catch(() => undefined);
    } finally {
      // Ignore out-of-order completion: only the latest request for this line
      // may clear the lock (a newer request keeps it held).
      if (lastRequestedRef.current.get(lineId) === quantity) {
        lastRequestedRef.current.delete(lineId);
        setPendingLineIds(current => {
          const next = new Set(current);
          next.delete(lineId);
          return next;
        });
      }
    }
  };

  const submitCheckout = async (acceptPriceChanges = false) => {
    if (!cart || cart.items.length === 0 || checkingOut) return;
    // The key is generated once the cart identity is known; a submit before
    // the cart loads cannot happen because the checkout button stays hidden
    // until items exist, but keep the guard for safety.
    if (idempotencyKey == null) return;
    setCheckingOut(true);
    try {
      const result = await checkout({
        idempotency_key: idempotencyKey,
        accept_price_changes: acceptPriceChanges,
        buyer_name: buyerName.trim() || undefined,
        buyer_email: buyerEmail.trim() || undefined,
      });
      setPriceConflict(false);
      if (result.checkout_group_id) {
        navigate(`/storefront/checkout/group?group=${encodeURIComponent(result.checkout_group_id)}`);
        return;
      }
      const firstOrder = result.orders[0];
      if (firstOrder) navigate(`/storefront/checkout/${encodeURIComponent(String(firstOrder.id))}`);
      else showToast(t('commerce.checkout_empty'), 'info');
    } catch (error) {
      if (isPriceConflict(error)) {
        setPriceConflict(true);
      } else {
        showToast(error instanceof Error ? error.message : t('commerce.checkout_failed'), 'error');
      }
    } finally {
      setCheckingOut(false);
    }
  };

  const handleClear = async () => {
    if (!cart || cart.items.length === 0) return;
    try {
      await clearCart();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.cart_update_failed'), 'error');
    }
  };

  return (
    <StorefrontShell storeName={t('commerce.store')}>
      <main className="storefront-main storefront-buyer-page">
        <Link className="storefront-link" to="/storefront"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link>
        <div className="storefront-page-intro">
          <div>
            <p className="storefront-eyebrow"><ShoppingCart size={14} /> {t('commerce.cart')}</p>
            <h1>{t('commerce.cart_title')}</h1>
            <p>{t('commerce.cart_description')}</p>
          </div>
          {cart && cart.items.length > 0 && <button type="button" className="storefront-button storefront-button-ghost" onClick={() => void handleClear()}><Trash2 size={15} /> {t('commerce.clear_cart')}</button>}
        </div>

        {cartLoading && !cart ? <section className="storefront-buyer-panel"><p>{t('browse.loading')}</p></section> : cart && cart.items.length > 0 ? (
          <section className="storefront-buyer-panel">
            <div className="storefront-cart-list">
              {cart.items.map(line => {
                const thumbnailUrl = assetThumbnailUrl(line.path, 320, api.buildUrl);
                return (
                  <article className="storefront-cart-line" key={line.id}>
                  <Link className="storefront-cart-line-image" to={`/storefront/product/${encodeURIComponent(String(line.item_id))}`} aria-label={line.title}>
                    {thumbnailUrl ? <img src={thumbnailUrl} alt="" loading="lazy" /> : <span className="storefront-line-image-placeholder" aria-hidden="true"><ImageIcon size={24} /></span>}
                  </Link>
                  <div>
                    <Link className="storefront-cart-line-title" to={`/storefront/product/${encodeURIComponent(String(line.item_id))}`}>{line.title}</Link>
                    <div className="storefront-cart-line-meta"><span>{formatMoney(line.unit_price_cents / 100, line.currency)}</span><span>{line.currency}</span></div>
                  </div>
                  <div className="storefront-cart-line-controls">
                    <button type="button" className="storefront-line-remove" aria-label={t('commerce.decrease_quantity')} onClick={() => void updateQuantity(line.id, line.quantity - 1)} disabled={line.quantity <= 1 || pendingLineIds.has(line.id)}><Minus size={15} /></button>
                    <input className="storefront-cart-quantity" aria-label={t('commerce.quantity')} type="number" min={1} max={999} value={line.quantity} onChange={event => void updateQuantity(line.id, Number(event.target.value))} disabled={pendingLineIds.has(line.id)} />
                    <button type="button" className="storefront-line-remove" aria-label={t('commerce.increase_quantity')} onClick={() => void updateQuantity(line.id, line.quantity + 1)} disabled={line.quantity >= 999 || pendingLineIds.has(line.id)}><Plus size={15} /></button>
                    <button type="button" className="storefront-line-remove" aria-label={t('commerce.remove_from_cart')} onClick={() => void removeCartItem(line.id).catch(error => showToast(error instanceof Error ? error.message : t('commerce.cart_update_failed'), 'error'))}><Trash2 size={15} /></button>
                  </div>
                  </article>
                );
              })}
            </div>
            {priceConflict && <div className="storefront-conflict" role="alert"><span><AlertTriangle size={16} /> {t('commerce.price_changed')}</span><button type="button" className="storefront-button storefront-button-ghost" onClick={() => void submitCheckout(true)} disabled={checkingOut}>{t('commerce.accept_price_changes')}</button></div>}
            <div className="storefront-cart-summary">
              <div className="storefront-cart-total"><span>{t('commerce.cart_total')}</span>{totals.map(([currency, cents]) => <strong key={currency}>{formatMoney(cents / 100, currency)}</strong>)}</div>
              <form className="storefront-checkout-form" onSubmit={event => { event.preventDefault(); void submitCheckout(priceConflict); }}>
                <div className="storefront-checkout-fields">
                  <label className="storefront-checkout-field"><span>{t('commerce.buyer_name')}</span><input value={buyerName} onChange={event => setBuyerName(event.target.value)} autoComplete="name" /></label>
                  <label className="storefront-checkout-field"><span>{t('commerce.buyer_email')}</span><input type="email" value={buyerEmail} onChange={event => setBuyerEmail(event.target.value)} autoComplete="email" /></label>
                </div>
                <button type="submit" className="storefront-button storefront-button-primary" disabled={checkingOut}>{checkingOut ? t('browse.loading') : t('commerce.checkout')} <ArrowRight size={16} /></button>
              </form>
            </div>
          </section>
        ) : (
          <section className="storefront-buyer-panel storefront-empty"><ShoppingCart size={28} /><h3>{t('commerce.cart_empty')}</h3><p>{t('commerce.cart_empty_description')}</p><Link className="storefront-button storefront-button-primary" to="/storefront/products">{t('commerce.browse_assets')} <ArrowRight size={15} /></Link></section>
        )}
      </main>
    </StorefrontShell>
  );
}
