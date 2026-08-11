import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { createShopApi } from '../../api/shop';
import { useAuth } from '../../hooks/useAuth';
import type {
  ShopBuyerMergeResponse,
  ShopCart,
  ShopCartCheckoutResponse,
  ShopWishlistItem,
} from '../../types/api';

interface ShopBuyerContextValue {
  cart: ShopCart | null;
  wishlist: ShopWishlistItem[];
  cartLoading: boolean;
  wishlistLoading: boolean;
  mergeLoading: boolean;
  refreshCart: () => Promise<ShopCart | null>;
  refreshWishlist: () => Promise<ShopWishlistItem[]>;
  mergeBuyerState: () => Promise<ShopBuyerMergeResponse | null>;
  addToCart: (itemId: string | number, quantity?: number) => Promise<ShopCart>;
  updateCartItem: (lineId: number, quantity: number) => Promise<ShopCart>;
  removeCartItem: (lineId: number) => Promise<ShopCart>;
  clearCart: () => Promise<ShopCart | null>;
  checkout: (payload: {
    idempotency_key: string;
    accept_price_changes?: boolean;
    buyer_name?: string;
    buyer_email?: string;
  }) => Promise<ShopCartCheckoutResponse>;
  addToWishlist: (itemId: string | number) => Promise<ShopWishlistItem[]>;
  removeFromWishlist: (itemId: string | number) => Promise<ShopWishlistItem[]>;
  clearWishlist: () => Promise<ShopWishlistItem[]>;
  isWishlisted: (itemId: string | number) => boolean;
}

const ShopBuyerContext = createContext<ShopBuyerContextValue | null>(null);

class StaleBuyerIdentityError extends Error {
  constructor() {
    super('Buyer identity changed; request ignored');
    this.name = 'StaleBuyerIdentityError';
  }
}

export function ShopBuyerProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const { api } = auth;
  // Keep the provider tolerant of lightweight route-test/auth adapters that
  // predate the principal identity fields; the real AuthProvider always fills
  // these values.
  const identityGeneration = auth.identityGeneration ?? 0;
  const isAuthenticated = auth.isAuthenticated ?? false;
  const isLoading = auth.isLoading ?? true;
  const principalKind = auth.principal?.kind ?? (isAuthenticated ? 'user' : 'guest');
  const hasStableIdentity = auth.principal != null || auth.identityGeneration != null;
  const shop = useMemo(() => createShopApi(api), [api]);
  const [cart, setCart] = useState<ShopCart | null>(null);
  const [wishlist, setWishlist] = useState<ShopWishlistItem[]>([]);
  const [cartLoading, setCartLoading] = useState(false);
  const [wishlistLoading, setWishlistLoading] = useState(false);
  const [mergeLoading, setMergeLoading] = useState(false);
  const handledIdentityRef = useRef<number | null>(null);
  const identityGenerationRef = useRef(identityGeneration);
  const cartRef = useRef<ShopCart | null>(cart);
  const cartRefreshRequestRef = useRef(0);
  const wishlistRefreshRequestRef = useRef(0);
  const mergeRequestRef = useRef(0);
  const buyerOperationTailRef = useRef<Promise<void>>(Promise.resolve());
  const buyerOperationGenerationRef = useRef(identityGeneration);
  identityGenerationRef.current = identityGeneration;

  const isCurrentIdentity = useCallback(
    (generation: number) => identityGenerationRef.current === generation,
    [],
  );
  const commitCart = useCallback((nextCart: ShopCart | null, generation: number) => {
    if (!isCurrentIdentity(generation)) return false;
    cartRef.current = nextCart;
    setCart(nextCart);
    return true;
  }, [isCurrentIdentity]);
  const commitWishlist = useCallback((nextWishlist: ShopWishlistItem[], generation: number) => {
    if (!isCurrentIdentity(generation)) return false;
    setWishlist(nextWishlist);
    return true;
  }, [isCurrentIdentity]);
  const ensureCurrentIdentity = useCallback((generation: number) => {
    if (!isCurrentIdentity(generation)) throw new StaleBuyerIdentityError();
  }, [isCurrentIdentity]);
  const enqueueBuyerOperation = useCallback(<T,>(
    generation: number,
    operation: () => Promise<T>,
  ) => {
    if (buyerOperationGenerationRef.current !== generation) {
      buyerOperationGenerationRef.current = generation;
      buyerOperationTailRef.current = Promise.resolve();
      cartRef.current = null;
    }
    const next = buyerOperationTailRef.current.catch(() => undefined).then(operation);
    buyerOperationTailRef.current = next.then(() => undefined, () => undefined);
    return next;
  }, []);

  const refreshCart = useCallback(async () => {
    const requestGeneration = identityGeneration;
    const requestId = ++cartRefreshRequestRef.current;
    setCartLoading(true);
    try {
      return await enqueueBuyerOperation(requestGeneration, async () => {
        if (!isCurrentIdentity(requestGeneration)) return null;
        const response = await shop.getCart();
        if (!commitCart(response.cart, requestGeneration)) return null;
        return response.cart;
      });
    } finally {
      if (isCurrentIdentity(requestGeneration) && cartRefreshRequestRef.current === requestId) {
        setCartLoading(false);
      }
    }
  }, [commitCart, enqueueBuyerOperation, identityGeneration, isCurrentIdentity, shop]);

  const refreshWishlist = useCallback(async () => {
    const requestGeneration = identityGeneration;
    const requestId = ++wishlistRefreshRequestRef.current;
    setWishlistLoading(true);
    try {
      return await enqueueBuyerOperation(requestGeneration, async () => {
        if (!isCurrentIdentity(requestGeneration)) return [];
        const response = await shop.getWishlist();
        const nextWishlist = response.items ?? [];
        if (!commitWishlist(nextWishlist, requestGeneration)) return [];
        return nextWishlist;
      });
    } finally {
      if (isCurrentIdentity(requestGeneration) && wishlistRefreshRequestRef.current === requestId) {
        setWishlistLoading(false);
      }
    }
  }, [commitWishlist, enqueueBuyerOperation, identityGeneration, isCurrentIdentity, shop]);

  const mergeBuyerState = useCallback(async (): Promise<ShopBuyerMergeResponse | null> => {
    if (!isAuthenticated || principalKind !== 'user') return null;
    const requestGeneration = identityGeneration;
    const requestId = ++mergeRequestRef.current;
    setMergeLoading(true);
    try {
      return await enqueueBuyerOperation(requestGeneration, async () => {
        if (!isCurrentIdentity(requestGeneration)) return null;
        const response = await shop.mergeBuyerState();
        if (!isCurrentIdentity(requestGeneration)) return null;
        commitCart(response.cart, requestGeneration);
        commitWishlist(response.wishlist ?? response.items ?? [], requestGeneration);
        return response;
      });
    } finally {
      if (isCurrentIdentity(requestGeneration) && mergeRequestRef.current === requestId) {
        setMergeLoading(false);
      }
    }
  }, [commitCart, commitWishlist, enqueueBuyerOperation, identityGeneration, isAuthenticated, isCurrentIdentity, principalKind, shop]);

  useEffect(() => {
    if (!hasStableIdentity || isLoading || handledIdentityRef.current === identityGeneration) return;
    handledIdentityRef.current = identityGeneration;
    let cancelled = false;

    const synchronizeBuyerState = async () => {
      if (isAuthenticated && principalKind === 'user') {
        try {
          await mergeBuyerState();
        } catch {
          // A server that predates the merge endpoint should not leave the
          // storefront blank. Fall back to reading the current user state.
          if (!cancelled) {
            await Promise.allSettled([refreshCart(), refreshWishlist()]);
          }
        }
        return;
      }

      // Never retain a previous user's private cart/wishlist while the
      // ordinary auth session is logged out or changes to a guest session.
      commitCart(null, identityGeneration);
      setWishlist([]);
      await Promise.allSettled([refreshCart(), refreshWishlist()]);
    };

    void synchronizeBuyerState();
    return () => {
      cancelled = true;
    };
  }, [
    identityGeneration,
    isAuthenticated,
    isLoading,
    hasStableIdentity,
    mergeBuyerState,
    principalKind,
    refreshCart,
    refreshWishlist,
  ]);

  const addToCart = useCallback(async (itemId: string | number, quantity = 1) => {
    const requestGeneration = identityGeneration;
    return enqueueBuyerOperation(requestGeneration, async () => {
      ensureCurrentIdentity(requestGeneration);
      const response = await shop.addCartItem(itemId, quantity, cartRef.current?.version);
      ensureCurrentIdentity(requestGeneration);
      commitCart(response.cart, requestGeneration);
      return response.cart;
    });
  }, [commitCart, enqueueBuyerOperation, ensureCurrentIdentity, identityGeneration, shop]);

  const updateCartItem = useCallback(async (lineId: number, quantity: number) => {
    const requestGeneration = identityGeneration;
    return enqueueBuyerOperation(requestGeneration, async () => {
      ensureCurrentIdentity(requestGeneration);
      const response = await shop.updateCartItem(lineId, quantity, cartRef.current?.version);
      ensureCurrentIdentity(requestGeneration);
      commitCart(response.cart, requestGeneration);
      return response.cart;
    });
  }, [commitCart, enqueueBuyerOperation, ensureCurrentIdentity, identityGeneration, shop]);

  const removeCartItem = useCallback(async (lineId: number) => {
    const requestGeneration = identityGeneration;
    return enqueueBuyerOperation(requestGeneration, async () => {
      ensureCurrentIdentity(requestGeneration);
      const response = await shop.removeCartItem(lineId, cartRef.current?.version);
      ensureCurrentIdentity(requestGeneration);
      commitCart(response.cart, requestGeneration);
      return response.cart;
    });
  }, [commitCart, enqueueBuyerOperation, ensureCurrentIdentity, identityGeneration, shop]);

  const clearCart = useCallback(async () => {
    const requestGeneration = identityGeneration;
    return enqueueBuyerOperation(requestGeneration, async () => {
      ensureCurrentIdentity(requestGeneration);
      const response = await shop.clearCart();
      ensureCurrentIdentity(requestGeneration);
      commitCart(response.cart, requestGeneration);
      return response.cart;
    });
  }, [commitCart, enqueueBuyerOperation, ensureCurrentIdentity, identityGeneration, shop]);

  const checkout = useCallback(async (payload: {
    idempotency_key: string;
    accept_price_changes?: boolean;
    buyer_name?: string;
    buyer_email?: string;
  }) => {
    const requestGeneration = identityGeneration;
    return enqueueBuyerOperation(requestGeneration, async () => {
      ensureCurrentIdentity(requestGeneration);
      const response = await shop.checkoutCart(payload);
      ensureCurrentIdentity(requestGeneration);
      commitCart(response.cart, requestGeneration);
      return response;
    });
  }, [commitCart, enqueueBuyerOperation, ensureCurrentIdentity, identityGeneration, shop]);

  const addToWishlist = useCallback(async (itemId: string | number) => {
    const requestGeneration = identityGeneration;
    return enqueueBuyerOperation(requestGeneration, async () => {
      ensureCurrentIdentity(requestGeneration);
      const response = await shop.addWishlistItem(itemId);
      ensureCurrentIdentity(requestGeneration);
      const nextWishlist = response.items ?? [];
      commitWishlist(nextWishlist, requestGeneration);
      return nextWishlist;
    });
  }, [commitWishlist, enqueueBuyerOperation, ensureCurrentIdentity, identityGeneration, shop]);

  const removeFromWishlist = useCallback(async (itemId: string | number) => {
    const requestGeneration = identityGeneration;
    return enqueueBuyerOperation(requestGeneration, async () => {
      ensureCurrentIdentity(requestGeneration);
      const response = await shop.removeWishlistItem(itemId);
      ensureCurrentIdentity(requestGeneration);
      const nextWishlist = response.items ?? [];
      commitWishlist(nextWishlist, requestGeneration);
      return nextWishlist;
    });
  }, [commitWishlist, enqueueBuyerOperation, ensureCurrentIdentity, identityGeneration, shop]);

  const clearWishlist = useCallback(async () => {
    const requestGeneration = identityGeneration;
    return enqueueBuyerOperation(requestGeneration, async () => {
      ensureCurrentIdentity(requestGeneration);
      const response = await shop.clearWishlist();
      ensureCurrentIdentity(requestGeneration);
      const nextWishlist = response.items ?? [];
      commitWishlist(nextWishlist, requestGeneration);
      return nextWishlist;
    });
  }, [commitWishlist, enqueueBuyerOperation, ensureCurrentIdentity, identityGeneration, shop]);

  const isWishlisted = useCallback(
    (itemId: string | number) => wishlist.some(item => String(item.item_id) === String(itemId)),
    [wishlist],
  );

  const value = useMemo<ShopBuyerContextValue>(() => ({
    cart,
    wishlist,
    cartLoading,
    wishlistLoading,
    mergeLoading,
    refreshCart,
    refreshWishlist,
    mergeBuyerState,
    addToCart,
    updateCartItem,
    removeCartItem,
    clearCart,
    checkout,
    addToWishlist,
    removeFromWishlist,
    clearWishlist,
    isWishlisted,
  }), [
    addToCart,
    addToWishlist,
    cart,
    cartLoading,
    checkout,
    clearCart,
    clearWishlist,
    isWishlisted,
    mergeBuyerState,
    mergeLoading,
    refreshCart,
    refreshWishlist,
    removeCartItem,
    removeFromWishlist,
    updateCartItem,
    wishlist,
    wishlistLoading,
  ]);

  return <ShopBuyerContext.Provider value={value}>{children}</ShopBuyerContext.Provider>;
}

export function useShopBuyer(): ShopBuyerContextValue {
  const value = useContext(ShopBuyerContext);
  if (!value) throw new Error('useShopBuyer must be used within ShopBuyerProvider');
  return value;
}
