import { ArrowRight, Boxes, ChevronRight, Download, Sparkles, TrendingUp } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { ImageViewer } from '../components/viewer/ImageViewer';
import { useI18n } from '../hooks/useI18n';
import { EmptyState, ProductCard, ProductStat } from '../components/storefront/ProductCard';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import type { StorefrontData, StorefrontProduct } from '../components/storefront/types';
import type { ShopPublicSellerProfile } from '../types/api';
import { useCommerceCatalog } from '../hooks/useCommerce';
import { useAuth } from '../hooks/useAuth';
import { createShopApi } from '../api/shop';

export interface StorefrontPageProps {
  storefront?: StorefrontData;
}

export default function StorefrontPage({ storefront }: StorefrontPageProps) {
  const { t } = useI18n();
  const { api } = useAuth();
  const shopApi = useMemo(() => createShopApi(api), [api]);
  const [preview, setPreview] = useState<StorefrontProduct | null>(null);
  const [publicProfile, setPublicProfile] = useState<ShopPublicSellerProfile | null>(null);
  const catalog = useCommerceCatalog();
  const products = storefront?.products ?? catalog.products;
  // Single-pass aggregation: one traversal builds both the per-category count
  // and the representative cover image, avoiding the previous O(n²) filter
  // per category. The category list is derived from these counts.
  const categoryAggregate = useMemo(() => {
    const counts = new Map<string, number>();
    const covers = new Map<string, string>();
    for (const item of products) {
      if (!item.category) continue;
      counts.set(item.category, (counts.get(item.category) ?? 0) + 1);
      if (item.imageUrl) covers.set(item.category, item.imageUrl);
    }
    return { counts, covers };
  }, [products]);
  const categories = storefront?.categories ?? Array.from(categoryAggregate.counts.entries(), ([name, count]) => ({ id: name, name, count, imageUrl: categoryAggregate.covers.get(name) }));
  const featured = products.filter(product => product.featured).slice(0, 4);
  const latest = products.filter(product => !product.featured).slice(0, 4);
  const heroImages = products.slice(0, 2).map(product => product.imageUrl);

  useEffect(() => {
    void shopApi.recordStorefrontView().catch(() => {
      // Anonymous analytics must never make the storefront unavailable.
    });
  }, [shopApi]);

  useEffect(() => {
    let active = true;
    void shopApi.getPublicProfile()
      .then(response => { if (active) setPublicProfile(response.profile); })
      .catch(() => { /* Store profile is optional for buyer browsing. */ });
    return () => { active = false; };
  }, [shopApi]);

  const storeName = (storefront?.name ?? publicProfile?.store_name) || 'AssetMarket';
  const storeDescription = (storefront?.description ?? publicProfile?.description) || t('commerce.storefront_description');

  return (
    <StorefrontShell storeName={storeName}>
      <main className="storefront-main">
        <section className="storefront-hero" aria-labelledby="storefront-title">
          <div>
            <p className="storefront-eyebrow"><Sparkles size={14} /> {t('commerce.marketplace_label')}</p>
            <h1 id="storefront-title">{storefront?.tagline ?? t('commerce.storefront_title')}</h1>
            <p>{storeDescription}</p>
            <div className="storefront-hero-actions">
              <Link to="/storefront/products" className="storefront-button storefront-button-primary">{t('commerce.explore_assets')} <ArrowRight size={16} /></Link>
              <Link to="/seller" className="storefront-button storefront-button-ghost">{t('commerce.start_selling')}</Link>
            </div>
          </div>
          <div className="storefront-hero-art" aria-hidden="true">
            {heroImages.length > 0 ? heroImages.map((image, index) => <div key={`${image}-${index}`} className="storefront-art-card"><img src={image} alt="" /></div>) : <div className="storefront-art-card"><div style={{ aspectRatio: '4 / 5', background: 'linear-gradient(145deg, #7c3aed, #ec4899 55%, #0f172a)' }} /></div>}
          </div>
        </section>

        {categories.length > 0 && <section className="storefront-section" aria-labelledby="category-title">
          <div className="storefront-section-header"><div><h2 id="category-title">{t('commerce.browse_categories')}</h2><p>{t('commerce.category_subtitle')}</p></div><Link className="storefront-link" to="/storefront/products">{t('commerce.view_all')} <ArrowRight size={15} /></Link></div>
          <div className="storefront-category-grid">{categories.slice(0, 4).map(category => <div className="storefront-category" key={category.id} role="group"><div className="storefront-category-image">{category.imageUrl && <img src={category.imageUrl} alt="" />}</div><strong>{category.name}</strong><span>{t('commerce.asset_count', category.count ?? 0)}</span></div>)}</div>
        </section>}

        <section className="storefront-section" aria-labelledby="featured-title">
          <div className="storefront-section-header"><div><h2 id="featured-title">{t('commerce.featured_assets')}</h2><p>{t('commerce.featured_subtitle')}</p></div><Link className="storefront-link" to="/storefront/products">{t('commerce.view_all')} <ArrowRight size={15} /></Link></div>
          {featured.length > 0 ? <div className="product-grid">{featured.map(product => <ProductCard key={product.id} product={product} onPreview={setPreview} />)}</div> : <EmptyState title={t('commerce.no_products_title')} description={t('commerce.no_products_description')} action={<Link className="storefront-button storefront-button-ghost" to="/seller">{t('commerce.start_selling')}</Link>} />}
        </section>

        {latest.length > 0 && <section className="storefront-section" aria-labelledby="latest-title"><div className="storefront-section-header"><div><h2 id="latest-title">{t('commerce.latest_assets')}</h2><p>{t('commerce.latest_subtitle')}</p></div><TrendingUp size={19} style={{ color: '#a78bfa' }} /></div><div className="product-grid">{latest.map(product => <ProductCard key={product.id} product={product} compact onPreview={setPreview} />)}</div></section>}
        <section className="storefront-section" aria-label={t('commerce.highlights')}><div className="seller-stat-grid"><ProductStat icon={<Boxes size={18} />} label={t('commerce.curated_assets')} value={products.length.toLocaleString()} /><ProductStat icon={<Download size={18} />} label={t('commerce.total_downloads')} value={products.reduce((sum, product) => sum + (product.downloads ?? 0), 0).toLocaleString()} /><ProductStat icon={<Sparkles size={18} />} label={t('commerce.quality_checked')} value="100%" /><ProductStat icon={<ChevronRight size={18} />} label={t('commerce.new_this_week')} value={latest.length.toLocaleString()} /></div></section>
      </main>
      {preview && <ImageViewer images={[preview.imageUrl, ...(preview.gallery ?? [])]} currentIndex={0} onClose={() => setPreview(null)} />}
    </StorefrontShell>
  );
}


