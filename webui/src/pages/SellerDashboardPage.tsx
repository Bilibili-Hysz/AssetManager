import { BarChart3, DollarSign, Eye, Package, Plus, ShoppingBag } from 'lucide-react';
import { Link } from 'react-router-dom';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { EmptyState, ProductCard } from '../components/storefront/ProductCard';
import { formatMoney, type SellerPageProps } from '../components/storefront/types';
import { useI18n } from '../hooks/useI18n';
import { useCommerceCatalog, useCommerceOrders } from '../hooks/useCommerce';

export default function SellerDashboardPage({ seller, products = [], orders = [], stats, onNavigate }: SellerPageProps) {
  const { t } = useI18n();
  const catalog = useCommerceCatalog(true);
  const commerceOrders = useCommerceOrders();
  const resolvedProducts = products.length > 0 ? products : catalog.products;
  const resolvedOrders = orders.length > 0 ? orders : commerceOrders.orders;
  const resolvedStats = stats ?? { ...commerceOrders.stats, products: resolvedProducts.filter(product => product.status === 'active').length };
  const displayProducts = resolvedProducts;
  const displayOrders = resolvedOrders;
  // While the stats hooks are still loading, avoid presenting a misleading
  // zero-valued dashboard; show a placeholder instead (same pattern as the
  // loading text used elsewhere in the seller pages).
  const statsLoading = !stats && (commerceOrders.loading || catalog.loading);
  const statsValue = (value: string) => statsLoading ? t('browse.loading') : value;
  const viewsValue = resolvedStats.views == null ? '—' : resolvedStats.views.toLocaleString();
  const go = (path: string) => onNavigate?.(path);
  return <StorefrontShell sellerMode storeName={seller?.storeName ?? t('seller.portal')}><main className="seller-main"><div className="seller-page-heading"><div><p className="storefront-eyebrow">{t('seller.workspace')}</p><h1>{t('seller.dashboard_title')}</h1><p>{t('seller.dashboard_subtitle')}</p></div><div className="seller-heading-actions"><Link className="storefront-button storefront-button-ghost" to="/storefront"><Eye size={15} /> {t('seller.view_store')}</Link><Link className="storefront-button storefront-button-primary" to="/seller/products/new" onClick={() => go('/seller/products/new')}><Plus size={16} /> {t('seller.add_product')}</Link></div></div><section className="seller-stat-grid" aria-label={t('seller.overview')}><div className="seller-stat-card"><span className="seller-stat-icon"><DollarSign size={19} /></span><span><small>{t('seller.total_revenue')}</small><strong>{statsValue(formatMoney(resolvedStats.revenue))}</strong></span></div><div className="seller-stat-card"><span className="seller-stat-icon"><ShoppingBag size={19} /></span><span><small>{t('seller.orders')}</small><strong>{statsValue(resolvedStats.orders.toLocaleString())}</strong></span></div><div className="seller-stat-card"><span className="seller-stat-icon"><Package size={19} /></span><span><small>{t('seller.active_products')}</small><strong>{statsValue(resolvedStats.products.toLocaleString())}</strong></span></div><div className="seller-stat-card"><span className="seller-stat-icon"><Eye size={19} /></span><span><small>{t('seller.store_views')}</small><strong title={resolvedStats.views == null ? t('seller.analytics_unavailable') : undefined}>{statsValue(viewsValue)}</strong></span></div></section><div className="seller-content-grid"><section className="seller-panel"><div className="seller-panel-header"><h2>{t('seller.recent_products')}</h2><Link to="/seller/products">{t('commerce.view_all')}</Link></div>{displayProducts.length > 0 ? <div className="product-grid">{displayProducts.slice(0, 4).map(product => <ProductCard key={product.id} product={product} sellerMode />)}</div> : <EmptyState title={t('seller.no_products_title')} description={t('seller.no_products_description')} action={<Link className="storefront-button storefront-button-primary" to="/seller/products/new"><Plus size={15} /> {t('seller.add_product')}</Link>} />}</section><aside className="seller-panel"><div className="seller-panel-header"><h2>{t('seller.recent_activity')}</h2><BarChart3 size={18} style={{ color: '#a78bfa' }} /></div><div className="seller-activity-list">{displayOrders.slice(0, 4).map(order => <div className="seller-activity" key={order.id}><span className="seller-activity-dot" /><div><strong>{order.productName}</strong><div>{formatMoney(order.amount, order.currency)} · {t(`seller.status_${order.status}`)}</div><time>{order.createdAt}</time></div></div>)}{displayOrders.length === 0 && <p style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>{t('seller.no_activity')}</p>}</div></aside></div></main></StorefrontShell>;
}
