import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, Heart, Menu, ReceiptText, Search, ShoppingBag, ShoppingCart, Store, X } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useAuthContext } from '../../stores/AuthContext';
import { useI18n } from '../../hooks/useI18n';
import './Storefront.css';
import { useShopBuyer } from './ShopBuyerContext';

interface StorefrontShellProps {
  children: ReactNode;
  sellerMode?: boolean;
  storeName?: string;
  onSearch?: (value: string) => void;
  searchValue?: string;
}

export function StorefrontShell({ children, sellerMode = false, storeName = 'AssetMarket', onSearch, searchValue }: StorefrontShellProps) {
  const { t } = useI18n();
  const { isAuthenticated, user, logout } = useAuthContext();
  const location = useLocation();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [search, setSearch] = useState(searchValue ?? '');
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const { cart, wishlist, refreshCart, refreshWishlist } = useShopBuyer();
  const cartCount = cart?.items.reduce((total, line) => total + line.quantity, 0) ?? 0;

  // E11: close the mobile menu on Escape or on a pointer down outside the menu/button.
  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false);
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (menuButtonRef.current?.contains(target)) return; // the button toggles itself
      if (navRef.current?.contains(target)) return; // nav links close it via their own onClick
      setMenuOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (searchValue !== undefined) setSearch(searchValue);
  }, [searchValue]);

  useEffect(() => {
    if (sellerMode) return;
    void refreshCart().catch(() => undefined);
    void refreshWishlist().catch(() => undefined);
  }, [refreshCart, refreshWishlist, sellerMode]);

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    const value = search.trim();
    if (onSearch) {
      onSearch(value);
      return;
    }

    navigate({
      pathname: '/storefront/products',
      search: value ? `?q=${encodeURIComponent(value)}` : '',
    });
  };

  const navItems: Array<[string, string]> = sellerMode
    ? [['/seller', t('seller.dashboard')], ['/seller/products', t('seller.products')], ['/seller/orders', t('seller.orders')], ['/seller/settings', t('seller.settings')]]
    : [['/storefront', t('commerce.store')], ['/storefront/products', t('commerce.browse')]];

  return (
    <div className="storefront-app">
      <header className="storefront-header">
        <div className="storefront-header-inner">
          <Link to={sellerMode ? '/seller' : '/storefront'} className="storefront-brand" aria-label={storeName}>
            <span className="storefront-brand-mark"><Store size={18} /></span>
            <span>{storeName}</span>
          </Link>
          <button type="button" ref={menuButtonRef} className="storefront-menu-button" aria-label={t('commerce.open_menu')} aria-expanded={menuOpen} aria-controls="storefront-nav" onClick={() => setMenuOpen(value => !value)}>
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <nav id="storefront-nav" ref={navRef} className={`storefront-nav ${menuOpen ? 'is-open' : ''}`} aria-label={t('commerce.navigation')}>
            {navItems.map(([href, label]) => (
              <Link key={href} to={href} className={location.pathname === href ? 'is-active' : ''} onClick={() => setMenuOpen(false)}>{label}</Link>
            ))}
          </nav>
          {!sellerMode && (
            <form className="storefront-search" onSubmit={submitSearch} role="search">
              <Search size={16} aria-hidden="true" />
              <label className="sr-only" htmlFor="storefront-search">{t('commerce.search')}</label>
              <input id="storefront-search" value={search} onChange={event => setSearch(event.target.value)} placeholder={t('commerce.search')} />
            </form>
          )}
          <div className="storefront-header-actions">
            {!sellerMode && (
              <>
                <Link className="storefront-icon-button" to="/storefront/products" aria-label={t('commerce.browse_assets')} title={t('commerce.browse_assets')}><ShoppingBag size={18} /></Link>
                <Link className="storefront-icon-button" to="/storefront/orders" aria-label={t('commerce.buyer_orders')} title={t('commerce.buyer_orders')}><ReceiptText size={18} /></Link>
                <Link className="storefront-icon-button storefront-icon-button-with-badge" to="/storefront/wishlist" aria-label={t('commerce.wishlist')} title={t('commerce.wishlist')}><Heart size={18} />{wishlist.length > 0 && <span className="storefront-count-badge">{wishlist.length}</span>}</Link>
                <Link className="storefront-icon-button storefront-icon-button-with-badge" to="/storefront/cart" aria-label={t('commerce.cart')} title={t('commerce.cart')}><ShoppingCart size={18} />{cartCount > 0 && <span className="storefront-count-badge">{cartCount}</span>}</Link>
              </>
            )}
            {sellerMode ? (
              <Link className="storefront-avatar-link" to="/storefront"><ArrowRight size={16} /> {t('seller.view_store')}</Link>
            ) : isAuthenticated ? (
              <Link className="storefront-avatar-link" to="/seller"><span className="storefront-avatar">{(user?.username ?? 'U').slice(0, 1).toUpperCase()}</span><span className="storefront-user-name">{user?.username ?? t('commerce.account')}</span></Link>
            ) : (
              <Link className="storefront-button storefront-button-ghost" to="/login">{t('commerce.sign_in')}</Link>
            )}
            {sellerMode && isAuthenticated && <button type="button" className="storefront-button storefront-button-ghost storefront-logout" onClick={logout}>{t('header.logout')}</button>}
          </div>
        </div>
      </header>
      {children}
      <footer className="storefront-footer"><span>© {new Date().getFullYear()} {storeName}</span><span>{t('commerce.footer_note')}</span></footer>
    </div>
  );
}


