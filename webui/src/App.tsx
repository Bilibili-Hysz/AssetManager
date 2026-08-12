import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet, useParams, useSearchParams } from 'react-router-dom';
import { AuthProvider } from './stores/AuthContext';
import { RealtimeProvider } from './stores/RealtimeContext';
import { SellerAuthProvider } from './stores/SellerAuthContext';
import { ToastProvider } from './components/ui/Toast';
import { DownloadProgressProvider } from './components/ui/DownloadProgress';
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import NotFoundPage from './pages/NotFoundPage';
const BrowsePage = lazy(() => import('./pages/BrowsePage'));
const DetailPage = lazy(() => import('./pages/DetailPage'));
const GalleryHomePage = lazy(() => import('./pages/GalleryHomePage'));
const GalleryCollectionPage = lazy(() => import('./pages/GalleryCollectionPage'));
const GalleryFavoritesPage = lazy(() => import('./pages/GalleryFavoritesPage'));
const ShareReceivePage = lazy(() => import('./pages/ShareReceivePage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));
import ProtectedRoute from './components/auth/ProtectedRoute';
import { CommandPalette } from './components/ui/CommandPalette';
import { useAuthContext } from './stores/AuthContext';
const StorefrontPage = lazy(() => import('./pages/StorefrontPage'));
const StorefrontProductsPage = lazy(() => import('./pages/StorefrontProductsPage'));
const StorefrontProductPage = lazy(() => import('./pages/StorefrontProductPage'));
const StorefrontCheckoutPage = lazy(() => import('./pages/StorefrontCheckoutPage'));
const StorefrontCheckoutGroupPage = lazy(() => import('./pages/StorefrontCheckoutGroupPage'));
const StorefrontDeliveryPage = lazy(() => import('./pages/StorefrontDeliveryPage'));
const StorefrontCartPage = lazy(() => import('./pages/StorefrontCartPage'));
const StorefrontWishlistPage = lazy(() => import('./pages/StorefrontWishlistPage'));
const StorefrontBuyerOrdersPage = lazy(() => import('./pages/StorefrontBuyerOrdersPage'));
const LegacyStorefrontGalleryPage = lazy(() => import('./pages/LegacyStorefrontGalleryPage'));
const LegacyStorefrontItemPage = lazy(() => import('./pages/LegacyStorefrontItemPage'));
const SellerDashboardPage = lazy(() => import('./pages/SellerDashboardPage'));
const SellerOrdersPage = lazy(() => import('./pages/SellerOrdersPage'));
const SellerProductsPage = lazy(() => import('./pages/SellerProductsPage'));
const SellerSettingsPage = lazy(() => import('./pages/SellerSettingsPage'));
import { SellerAccessGate } from './components/storefront/SellerAccessGate';
import { ShopBuyerProvider } from './stores/ShopBuyerContext';

type CommerceFeature = 'commerce' | 'seller' | 'quota';

function FeatureFlagRoute({ feature }: { feature: CommerceFeature }) {
  const { isLoading, serverInfo } = useAuthContext();
  if (isLoading) return null;
  const flags = serverInfo?.feature_flags;
  const enabled = Boolean(flags?.commerce) && Boolean(flags?.[feature]);
  if (!enabled) {
    // Previously redirected to /gallery, which bounces unauthenticated users
    // to /login — a confusing redirect chain when the feature is simply
    // disabled. Render an explicit page instead.
    return <NotFoundPage />;
  }
  return <Outlet />;
}

function CommerceBuyerRoute() {
  return (
    <ShopBuyerProvider>
      <Outlet />
    </ShopBuyerProvider>
  );
}

function SellerProviderRoute() {
  return (
    <SellerAuthProvider>
      <Outlet />
    </SellerAuthProvider>
  );
}

function LegacyStorefrontCheckoutRoute() {
  const [params] = useSearchParams();
  const orderId = params.get('order');
  return orderId
    ? <Navigate to={`/storefront/checkout/${encodeURIComponent(orderId)}`} replace />
    : <Navigate to="/storefront" replace />;
}

function LegacyStorefrontDeliveryRoute() {
  const { token = '' } = useParams<{ token: string }>();
  const [searchParams] = useSearchParams();
  // Preserve the query string: share-claim links arrive as
  // /store/delivery/:token?claim=... and the delivery page needs it.
  const query = searchParams.toString();
  const to = `/storefront/delivery/${encodeURIComponent(decodeRouteValue(token))}${query ? `?${query}` : ''}`;
  return <Navigate to={to} replace />;
}

function decodeRouteValue(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function App() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const openPalette = useCallback(() => setPaletteOpen(true), []);
  const handlePaletteShortcut = useCallback((event: KeyboardEvent) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      setPaletteOpen(previous => !previous);
    }
  }, []);

  useEffect(() => {
    document.addEventListener('keydown', handlePaletteShortcut);
    return () => document.removeEventListener('keydown', handlePaletteShortcut);
  }, [handlePaletteShortcut]);

  return (
    <BrowserRouter>
      <AuthProvider>
        <RealtimeProvider>
          <ToastProvider>
            <DownloadProgressProvider>
              <Suspense fallback={<div className="app-route-loading" aria-busy="true" />}>
              <Routes>
                <Route path="/" element={<LandingPage />} />
                <Route path="/login" element={<LoginPage />} />
                <Route element={<ProtectedRoute capability="browse" />}>
                  <Route path="/browse" element={<BrowsePage onOpenPalette={openPalette} />} />
                  <Route path="/detail" element={<DetailPage onOpenPalette={openPalette} />} />
                  <Route path="/gallery" element={<GalleryHomePage onOpenPalette={openPalette} />} />
                  <Route path="/gallery/collection" element={<GalleryCollectionPage onOpenPalette={openPalette} />} />
                  <Route path="/gallery/favorites" element={<GalleryFavoritesPage onOpenPalette={openPalette} />} />
                </Route>
                <Route element={<ProtectedRoute capability="manage_users" />}>
                  <Route path="/admin" element={<AdminPage />} />
                </Route>
                <Route element={<FeatureFlagRoute feature="commerce" />}>
                  <Route element={<CommerceBuyerRoute />}>
                  <Route path="/storefront" element={<StorefrontPage />} />
                  <Route path="/storefront/products" element={<StorefrontProductsPage />} />
                  <Route path="/storefront/cart" element={<StorefrontCartPage />} />
                  <Route path="/storefront/wishlist" element={<StorefrontWishlistPage />} />
                  <Route path="/storefront/orders" element={<StorefrontBuyerOrdersPage />} />
                  <Route path="/storefront/product/:id" element={<StorefrontProductPage />} />
                  <Route path='/storefront/product/path/*' element={<StorefrontProductPage />} />
                  <Route path="/storefront/checkout/group" element={<StorefrontCheckoutGroupPage />} />
                  <Route path="/storefront/checkout/:orderId" element={<StorefrontCheckoutPage />} />
                  <Route path="/storefront/delivery/:token" element={<StorefrontDeliveryPage />} />
                  {/* Compatibility aliases from AssetsManager_New_WebUI. */}
                  <Route path="/store" element={<Navigate to="/storefront" replace />} />
                  <Route path="/store/gallery/:tag" element={<LegacyStorefrontGalleryPage />} />
                  <Route path="/store/checkout" element={<LegacyStorefrontCheckoutRoute />} />
                  <Route path="/store/delivery/:token" element={<LegacyStorefrontDeliveryRoute />} />
                  <Route path="/store/*" element={<LegacyStorefrontItemPage />} />
                  <Route element={<FeatureFlagRoute feature="seller" />}>
                    <Route element={<SellerProviderRoute />}>
                      <Route element={<SellerAccessGate />}>
                        <Route path="/seller" element={<SellerDashboardPage />} />
                        <Route path="/seller/products" element={<SellerProductsPage />} />
                        <Route path="/seller/products/new" element={<SellerProductsPage />} />
                        <Route path="/seller/products/:id" element={<SellerProductsPage />} />
                        <Route path="/seller/orders" element={<SellerOrdersPage />} />
                        <Route path="/seller/settings" element={<SellerSettingsPage />} />
                        {/* Compatibility aliases from the reference seller workbench. */}
                        <Route path="/app" element={<Navigate to="/seller" replace />} />
                        <Route path="/app/items" element={<Navigate to="/seller/products" replace />} />
                        <Route path="/app/orders" element={<Navigate to="/seller/orders" replace />} />
                      </Route>
                    </Route>
                  </Route>
                  </Route>
                </Route>
                <Route path="/s/:shareId" element={<ShareReceivePage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
              </Suspense>
              {paletteOpen && <CommandPalette open={true} onClose={() => setPaletteOpen(false)} />}
            </DownloadProgressProvider>
          </ToastProvider>
        </RealtimeProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
