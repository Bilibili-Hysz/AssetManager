import { Archive, ArrowUpRight, Download, Eye, Heart, ImageIcon, Pencil, RotateCcw, ShoppingCart, Star, Trash2 } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useRef, useState, type ReactNode } from 'react';
import { useI18n } from '../../hooks/useI18n';
import { formatMoney, type StorefrontProduct } from './types';

interface ProductCardProps {
  product: StorefrontProduct;
  compact?: boolean;
  sellerMode?: boolean;
  onPreview?: (product: StorefrontProduct) => void;
  /** Moves an active or draft product out of the public catalog. */
  onArchive?: (product: StorefrontProduct) => void;
  /** Restores an archived product to the active catalog. */
  onRestore?: (product: StorefrontProduct) => void;
  /** Permanently removes a product when no order still references it. */
  onRemove?: (product: StorefrontProduct) => void;
  actionPending?: boolean;
}

export function ProductCard({
  product,
  compact = false,
  sellerMode = false,
  onPreview,
  onArchive,
  onRestore,
  onRemove,
  actionPending = false,
}: ProductCardProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const href = sellerMode ? `/seller/products/${product.id}` : `/storefront/product/${encodeURIComponent(product.id)}`;
  const status = product.status ?? 'active';
  const canShowLifecycleActions = sellerMode && (onArchive || onRestore || onRemove);
  // E12: local pending lock so a fast double-click cannot fire the same lifecycle
  // action twice before the parent's actionPending propagates down. The lock is
  // released after a grace period; the parent's actionPending keeps buttons disabled
  // for the full duration of the request.
  const [localPending, setLocalPending] = useState(false);
  const busyRef = useRef(false);
  const runLifecycle = (action: (product: StorefrontProduct) => void) => {
    if (busyRef.current || actionPending) return;
    busyRef.current = true;
    setLocalPending(true);
    try {
      action(product);
    } catch {
      // Parent handlers surface their own errors; the lock must still be released.
    } finally {
      window.setTimeout(() => {
        busyRef.current = false;
        setLocalPending(false);
      }, 400);
    }
  };
  const lifecycleDisabled = actionPending || localPending;

  return (
    <article className={`product-card ${compact ? 'product-card-compact' : ''}`}>
      <button
        type="button"
        className="product-card-media"
        onClick={() => onPreview ? onPreview(product) : navigate(href)}
        aria-label={`${t('commerce.preview')} ${product.name}`}
      >
        {product.imageUrl ? <img src={product.imageUrl} alt="" loading="lazy" /> : <span className="product-card-media-placeholder" aria-hidden="true"><ImageIcon size={34} /></span>}
        <span className="product-card-overlay"><ArrowUpRight size={18} /></span>
        {product.featured && <span className="product-card-badge"><Star size={12} /> {t('commerce.featured')}</span>}
      </button>
      <div className="product-card-body">
        <div className="product-card-heading">
          <div>
            <p className="product-card-category">{product.category ?? t('commerce.digital_asset')}</p>
            <Link to={href} className="product-card-title">{product.name}</Link>
          </div>
        </div>
        {!compact && product.description && <p className="product-card-description">{product.description}</p>}
        <div className="product-card-meta">
          <strong>{product.price === 0 ? t('commerce.free') : formatMoney(product.price, product.currency)}</strong>
          {product.downloads !== undefined && <span><Download size={13} /> {product.downloads.toLocaleString()}</span>}
        </div>
        {!sellerMode && <Link className="product-card-quick-action" to={href}><ShoppingCart size={15} /> {product.price === 0 ? t('commerce.get_asset') : t('commerce.buy_now')}</Link>}
        {sellerMode && (
          <div className="product-card-seller-actions">
            <Link to={href}><Pencil size={14} /> {t('seller.edit')}</Link>
            <span><Eye size={14} /> {t(`seller.status_${status}`)}</span>
          </div>
        )}
        {canShowLifecycleActions && (
          <div className="product-card-lifecycle-actions" role="group" aria-label={t('seller.actions')}>
            {status === 'archived'
              ? onRestore && (
                <button
                  type="button"
                  className="product-card-lifecycle-action"
                  onClick={() => runLifecycle(onRestore)}
                  disabled={lifecycleDisabled}
                >
                  <RotateCcw size={13} /> {t('seller.restore_product')}
                </button>
              )
              : onArchive && (
                <button
                  type="button"
                  className="product-card-lifecycle-action"
                  onClick={() => runLifecycle(onArchive)}
                  disabled={lifecycleDisabled}
                >
                  <Archive size={13} /> {t('seller.archive_product')}
                </button>
              )}
            {onRemove && (
              <button
                type="button"
                className="product-card-lifecycle-action product-card-lifecycle-action-danger"
                onClick={() => runLifecycle(onRemove)}
                disabled={lifecycleDisabled}
              >
                <Trash2 size={13} /> {t('action.delete')}
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

export function ProductStat({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="product-stat"><span className="product-stat-icon">{icon}</span><span><strong>{value}</strong><small>{label}</small></span></div>;
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="storefront-empty"><Heart size={24} /><h3>{title}</h3><p>{description}</p>{action}</div>;
}

