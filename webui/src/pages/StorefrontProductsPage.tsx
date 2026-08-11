import { ArrowUpRight, ChevronLeft, ChevronRight, Filter, Search } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { useCallback } from 'react';
import { ProductCard, EmptyState } from '../components/storefront/ProductCard';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import type { StorefrontProduct } from '../components/storefront/types';
import { useI18n } from '../hooks/useI18n';
import { useCommerceCatalogPage } from '../hooks/useCommerce';

const DEFAULT_PAGE_SIZE = 24;
const PAGE_SIZE_OPTIONS = [24, 48, 100] as const;

function parsePositiveInteger(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : fallback;
}

function parsePageSize(value: string | null): number {
  const parsed = parsePositiveInteger(value, DEFAULT_PAGE_SIZE);
  return parsed <= 100 ? parsed : DEFAULT_PAGE_SIZE;
}

export interface StorefrontProductsPageProps {
  /** Legacy injection for embedders; the routed page uses the server Catalog contract. */
  products?: StorefrontProduct[];
}

export default function StorefrontProductsPage({ products = [] }: StorefrontProductsPageProps) {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const query = params.get('q')?.trim() ?? '';
  const page = parsePositiveInteger(params.get('page'), 1);
  const pageSize = parsePageSize(params.get('page_size'));
  const hasInjectedProducts = products.length > 0;
  const catalog = useCommerceCatalogPage({
    q: query || undefined,
    page,
    page_size: pageSize,
    sort: 'newest',
  });
  const renderedProducts = hasInjectedProducts ? products : catalog.products;
  const total = hasInjectedProducts ? products.length : catalog.total;
  const effectivePage = hasInjectedProducts ? 1 : page;
  const effectivePageSize = hasInjectedProducts ? Math.max(products.length, 1) : catalog.pageSize;
  const totalPages = Math.max(1, Math.ceil(total / effectivePageSize));
  const isLoading = !hasInjectedProducts && catalog.loading;
  const error = hasInjectedProducts ? null : catalog.error;

  const updateParams = useCallback((update: (next: URLSearchParams) => void) => {
    setParams(previous => {
      const next = new URLSearchParams(previous);
      update(next);
      return next;
    });
  }, [setParams]);

  const submitSearch = useCallback((value: string) => {
    updateParams(next => {
      const normalized = value.trim();
      if (normalized) next.set('q', normalized);
      else next.delete('q');
      next.delete('page');
    });
  }, [updateParams]);

  const goToPage = useCallback((nextPage: number) => {
    const target = Math.min(Math.max(nextPage, 1), totalPages);
    updateParams(next => {
      if (target <= 1) next.delete('page');
      else next.set('page', String(target));
    });
  }, [totalPages, updateParams]);

  const changePageSize = useCallback((value: string) => {
    const nextPageSize = parsePageSize(value);
    updateParams(next => {
      if (nextPageSize === DEFAULT_PAGE_SIZE) next.delete('page_size');
      else next.set('page_size', String(nextPageSize));
      next.delete('page');
    });
  }, [updateParams]);

  return (
    <StorefrontShell searchValue={query} onSearch={submitSearch}>
      <main className="storefront-main">
        <div className="storefront-page-intro">
          <div>
            <p className="storefront-eyebrow"><Filter size={14} /> {t('commerce.marketplace_label')}</p>
            <h1>{t('commerce.browse_assets')}</h1>
            <p>{t('commerce.browse_assets_description')}</p>
          </div>
          <Link className="storefront-button storefront-button-ghost" to="/seller">
            {t('commerce.sell_yours')} <ArrowUpRight size={15} />
          </Link>
        </div>

        <div className="storefront-toolbar">
          <div className="storefront-result-count">{t('commerce.results_count', total)}</div>
          <div className="storefront-catalog-controls">
            <span className="storefront-sort" aria-label={t('commerce.sort_by')}>
              {t('commerce.sort_by')}: <strong>{t('commerce.sort_newest')}</strong>
            </span>
            <label className="storefront-page-size">
              <span>{t('commerce.page_size')}</span>
              <select value={String(pageSize)} onChange={event => changePageSize(event.target.value)}>
                {!PAGE_SIZE_OPTIONS.includes(pageSize as (typeof PAGE_SIZE_OPTIONS)[number]) && <option value={pageSize}>{pageSize}</option>}
                {PAGE_SIZE_OPTIONS.map(option => <option key={option} value={option}>{option}</option>)}
              </select>
            </label>
          </div>
        </div>

        {isLoading ? (
          <div className="storefront-empty" role="status"><p>{t('browse.loading')}</p></div>
        ) : error ? (
          <div className="storefront-empty" role="alert">
            <h3>{t('browse.error')}</h3>
            <p>{t('commerce.product_load_failed_description')}</p>
            <button type="button" className="storefront-button storefront-button-ghost" onClick={() => void catalog.refresh()}>
              {t('landing.retry')}
            </button>
          </div>
        ) : renderedProducts.length > 0 ? (
          <div className="product-grid">
            {renderedProducts.map(product => <ProductCard key={product.id} product={product} />)}
          </div>
        ) : (
          <EmptyState
            title={query ? t('commerce.no_search_results') : t('commerce.no_products_title')}
            description={query ? t('commerce.no_search_results_description') : t('commerce.no_products_description')}
            action={query ? <button className="storefront-button storefront-button-ghost" type="button" onClick={() => submitSearch('')}><Search size={15} /> {t('commerce.clear_search')}</button> : undefined}
          />
        )}

        {!hasInjectedProducts && totalPages > 1 && (
          <nav className="storefront-pagination" aria-label={t('commerce.pagination')}>
            <button
              type="button"
              className="storefront-button storefront-button-ghost"
              aria-label={t('commerce.previous_page')}
              onClick={() => goToPage(effectivePage - 1)}
              disabled={effectivePage <= 1 || isLoading}
            >
              <ChevronLeft size={16} /> {t('commerce.previous_page')}
            </button>
            <span className="storefront-pagination-summary">{t('commerce.page_of', effectivePage, totalPages)}</span>
            <button
              type="button"
              className="storefront-button storefront-button-ghost"
              aria-label={t('commerce.next_page')}
              onClick={() => goToPage(effectivePage + 1)}
              disabled={effectivePage >= totalPages || isLoading}
            >
              {t('commerce.next_page')} <ChevronRight size={16} />
            </button>
          </nav>
        )}
      </main>
    </StorefrontShell>
  );
}