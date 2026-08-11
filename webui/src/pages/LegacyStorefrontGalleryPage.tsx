import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Search } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { createMetadataApi } from '../api/metadata';
import { useAuth } from '../hooks/useAuth';
import { useI18n } from '../hooks/useI18n';
import type { SearchResult } from '../types/api';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import LegacyAssetCard from '../components/storefront/LegacyAssetCard';

export default function LegacyStorefrontGalleryPage() {
  const { api } = useAuth();
  const { t } = useI18n();
  const { tag: rawTag = '' } = useParams<{ tag: string }>();
  const tag = useMemo(() => {
    try { return decodeURIComponent(rawTag); } catch { return rawTag; }
  }, [rawTag]);
  const metadataApi = useMemo(() => createMetadataApi(api), [api]);
  const [assets, setAssets] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setFailed(false);
    metadataApi.search('', tag, undefined, controller.signal)
      .then(response => { if (!controller.signal.aborted) setAssets(response.results ?? []); })
      .catch(() => { if (!controller.signal.aborted) { setAssets([]); setFailed(true); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [metadataApi, tag]);

  return (
    <StorefrontShell>
      <main className="storefront-main">
        <Link className="storefront-link" to="/storefront"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link>
        <div className="storefront-page-intro" style={{ marginTop: 22 }}>
          <div>
            <p className="storefront-eyebrow"><Search size={14} /> {t('gallery.visual_library')}</p>
            <h1>{t('gallery.nav_collections')}: {tag}</h1>
            <p>{t('gallery.visual_library_description')}</p>
          </div>
        </div>
        {loading ? <p style={{ color: 'var(--color-text-secondary)' }}>{t('gallery.loading')}</p> : failed ? <div className="storefront-empty"><h3>{t('gallery.unavailable')}</h3><p>{t('gallery.load_failed')}</p></div> : assets.length > 0 ? <div className="product-grid">{assets.map(asset => <LegacyAssetCard key={`${asset.type}:${asset.path}`} asset={asset} />)}</div> : <div className="storefront-empty"><h3>{t('gallery.no_visual_assets')}</h3><p>{t('gallery.inspect_workspace')}</p></div>}
      </main>
    </StorefrontShell>
  );
}
