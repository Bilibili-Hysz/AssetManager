import { Plus, Search } from 'lucide-react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { EmptyState, ProductCard } from '../components/storefront/ProductCard';
import SellerGalleryEditor from '../components/storefront/SellerGalleryEditor';
import type { SellerPageProps, StorefrontProduct } from '../components/storefront/types';
import { useI18n } from '../hooks/useI18n';
import { useCommerceCatalog } from '../hooks/useCommerce';
import { useAuth } from '../hooks/useAuth';
import { useShopApi } from '../hooks/usePageApis';
import { useToast } from '../components/ui/Toast';
import type { ShopItem } from '../types/api';

type ProductStatus = NonNullable<StorefrontProduct['status']>;

export default function SellerProductsPage({ seller, products = [] }: SellerPageProps) {
  const { t } = useI18n();
  const { api } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const { id } = useParams<{ id?: string }>();
  const shopApi = useShopApi();
  const catalog = useCommerceCatalog(true);
  const visibleProducts = products.length > 0 ? products : catalog.products;
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [path, setPath] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [coverPath, setCoverPath] = useState('');
  const [galleryPaths, setGalleryPaths] = useState<string[]>([]);
  const [price, setPrice] = useState('0');
  const [managedItems, setManagedItems] = useState<ShopItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [pendingProductId, setPendingProductId] = useState<string | null>(null);
  const isCreating = location.pathname.endsWith('/new');
  const isEditing = Boolean(id);
  const product = isEditing
    ? visibleProducts.find(candidate => candidate.id === id || candidate.slug === id)
    : undefined;
  const rawProduct = useMemo(
    () => managedItems.find(candidate => String(candidate.id) === product?.id || candidate.path === product?.slug),
    [managedItems, product],
  );
  const visible = useMemo(
    () => visibleProducts.filter(candidate => (filter === 'all' || (candidate.status ?? 'active') === filter) && candidate.name.toLowerCase().includes(query.toLowerCase())),
    [filter, visibleProducts, query],
  );

  useEffect(() => {
    if (!product) return;
    setPath(product.slug ?? product.id);
    setTitle(product.name);
    setDescription(rawProduct?.description ?? '');
    setCoverPath(rawProduct?.cover_path ?? '');
    setGalleryPaths(rawProduct?.gallery_paths ?? []);
    setPrice(String(product.price));
  }, [product, rawProduct]);

  const loadManagedItems = async () => {
    const response = await shopApi.list(undefined, true);
    setManagedItems(response.items);
  };

  useEffect(() => {
    void loadManagedItems().catch(() => {
      // The catalog hook still owns the visible list; this request only fills
      // seller-only fields such as description and includes disabled states.
    });
  }, [shopApi]);

  const refreshCatalog = async () => {
    await catalog.refresh();
    await loadManagedItems();
  };

  const saveProduct = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving || (isEditing && !product)) return;
    const normalizedPath = path.trim();
    const normalizedTitle = title.trim();
    const amount = Number(price);
    if (!normalizedPath || !normalizedTitle || !Number.isFinite(amount) || amount < 0) return;
    const normalizedCoverPath = coverPath.trim();
    const normalizedGalleryPaths = galleryPaths.map(value => value.trim()).filter(Boolean);
    const allGalleryPaths = [normalizedCoverPath, ...normalizedGalleryPaths].filter(Boolean);
    const comparablePaths = allGalleryPaths.map(value => value.toLowerCase());
    const hasDuplicateGalleryPath = new Set(comparablePaths).size !== comparablePaths.length;
    const hasInvalidGalleryPath = allGalleryPaths.some(value => value.startsWith('/') || /^https?:\/\//i.test(value) || value.split('/').some(segment => segment === '..'));
    if (hasDuplicateGalleryPath || hasInvalidGalleryPath || normalizedGalleryPaths.length > 20) return;
    if (!window.confirm(t('seller.confirm_save_product'))) return;
    setSaving(true);
    try {
      const initialGalleryPaths = rawProduct?.gallery_paths ?? [];
      const galleryChanged = normalizedGalleryPaths.length > 0 || (isEditing && normalizedGalleryPaths.join('\n') !== initialGalleryPaths.join('\n'));
      const payload = {
        path: normalizedPath,
        title: normalizedTitle,
        description: description.trim(),
        ...(galleryChanged ? { gallery_paths: normalizedGalleryPaths } : {}),
        ...((isEditing && normalizedCoverPath !== (rawProduct?.cover_path ?? '')) || (!isEditing && normalizedCoverPath) ? { cover_path: normalizedCoverPath } : {}),
        price_cents: Math.round(amount * 100),
        ...(isEditing ? { status: product?.status ?? 'active' } : { status: 'active' as const }),
      };
      if (isEditing && product) {
        await shopApi.update(product.id, payload);
      } else {
        await shopApi.create(payload);
      }
      await refreshCatalog();
      showToast(t('seller.product_updated'), 'success');
      navigate('/seller/products');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.product_not_found_description'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const updateProductStatus = async (candidate: StorefrontProduct, status: ProductStatus) => {
    if (pendingProductId) return;
    setPendingProductId(candidate.id);
    try {
      await shopApi.update(candidate.id, { status });
      await refreshCatalog();
      showToast(t('seller.product_updated'), 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.product_not_found_description'), 'error');
    } finally {
      setPendingProductId(null);
    }
  };

  const removeProduct = async (candidate: StorefrontProduct) => {
    if (pendingProductId || !window.confirm(t('seller.delete_product_confirmation', candidate.name))) return;
    setPendingProductId(candidate.id);
    try {
      await shopApi.remove(candidate.id);
      await refreshCatalog();
      showToast(t('seller.product_removed'), 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('commerce.product_not_found_description'), 'error');
    } finally {
      setPendingProductId(null);
    }
  };

  if (isEditing && catalog.loading) {
    return <StorefrontShell sellerMode storeName={seller?.storeName ?? t('seller.portal')}><main className="seller-main"><section className="seller-panel" aria-busy="true"><p>{t('browse.loading')}</p></section></main></StorefrontShell>;
  }

  if (isEditing && !product) {
    return <StorefrontShell sellerMode storeName={seller?.storeName ?? t('seller.portal')}><main className="seller-main"><div className="storefront-empty"><h3>{t('commerce.product_not_found')}</h3><p>{t('commerce.product_not_found_description')}</p><Link className="storefront-button storefront-button-ghost" to="/seller/products">{t('action.cancel')}</Link></div></main></StorefrontShell>;
  }

  if (isCreating || isEditing) {
    const heading = isEditing ? t('seller.edit') : t('seller.add_product');
    return <StorefrontShell sellerMode storeName={seller?.storeName ?? t('seller.portal')}><main className="seller-main"><div className="seller-page-heading"><div><p className="storefront-eyebrow">{t('seller.catalog')}</p><h1>{heading}</h1><p>{t('seller.products_subtitle')}</p></div></div><section className="seller-panel"><form className="seller-form" onSubmit={saveProduct}><div className="seller-form-grid"><label className="seller-field"><span>{t('info.path')}</span><input value={path} onChange={event => setPath(event.target.value)} placeholder="projects/example" required /></label><label className="seller-field"><span>{t('seller.product')}</span><input value={title} onChange={event => setTitle(event.target.value)} placeholder={t('seller.products_title')} required /></label><label className="seller-field"><span>{t('seller.amount')}</span><input type="number" min="0" step="0.01" value={price} onChange={event => setPrice(event.target.value)} required /></label><label className="seller-field"><span>{t('seller.description')}</span><textarea value={description} onChange={event => setDescription(event.target.value)} rows={4} /></label><div className="seller-field sm:col-span-2"><SellerGalleryEditor coverPath={coverPath} galleryPaths={galleryPaths} buildUrl={api.buildUrl} onChange={({ coverPath: nextCoverPath, galleryPaths: nextGalleryPaths }) => { setCoverPath(nextCoverPath); setGalleryPaths(nextGalleryPaths); }} /></div></div><div><button type="submit" className="storefront-button storefront-button-primary" disabled={saving}>{saving ? t('browse.loading') : heading}</button><button type="button" className="storefront-button storefront-button-ghost" style={{ marginLeft: 8 }} onClick={() => navigate('/seller/products')}>{t('action.cancel')}</button></div></form></section></main></StorefrontShell>;
  }

  return <StorefrontShell sellerMode storeName={seller?.storeName ?? t('seller.portal')}><main className="seller-main"><div className="seller-page-heading"><div><p className="storefront-eyebrow">{t('seller.catalog')}</p><h1>{t('seller.products_title')}</h1><p>{t('seller.products_subtitle')}</p></div><Link className="storefront-button storefront-button-primary" to="/seller/products/new"><Plus size={16} /> {t('seller.add_product')}</Link></div><div className="seller-filter-bar"><div className="seller-filter-buttons">{['all', 'active', 'draft', 'archived'].map(value => <button key={value} type="button" className={filter === value ? 'is-active' : ''} aria-pressed={filter === value} onClick={() => setFilter(value)}>{t(`seller.filter_${value}`)}</button>)}</div><label className="seller-search"><Search size={14} /><span className="sr-only">{t('commerce.search')}</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder={t('seller.search_products')} /></label></div>{visible.length > 0 ? <div className="product-grid">{visible.map(candidate => <ProductCard key={candidate.id} product={candidate} sellerMode onArchive={productToArchive => void updateProductStatus(productToArchive, 'archived')} onRestore={productToRestore => void updateProductStatus(productToRestore, 'active')} onRemove={productToRemove => void removeProduct(productToRemove)} actionPending={pendingProductId === candidate.id} />)}</div> : <EmptyState title={t('seller.no_products_title')} description={t('seller.no_products_description')} action={<Link className="storefront-button storefront-button-primary" to="/seller/products/new"><Plus size={15} /> {t('seller.add_product')}</Link>} />}</main></StorefrontShell>;
}
