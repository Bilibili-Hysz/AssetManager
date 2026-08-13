/**
 * Query cache provider: owns one cache per app lifetime and clears it
 * whenever the authenticated identity changes (login, logout, 401 expiry),
 * which is the single isolation point for cached data.
 *
 * Identity-boundary contract (the one rule every identity scope follows):
 *
 *   身份翻转 = 唯一失效边界。每个身份作用域只有一个"翻转信号"，翻转时
 *   无条件清空该作用域持有的派生状态；任何消费者都不得自行推断身份。
 *
 *   1. 主会话:   AuthContext.identityGeneration —— QueryCacheProvider（本组件）
 *               在 layout 阶段清空整个缓存（键不携带身份，隔离=整体清空）。
 *   2. 卖家 cookie: SellerAuthContext.authenticated 翻转 —— 同一缓存再清一次
 *               （卖家 cookie 可独立于主会话翻转）。
 *   3. 买家合并: ShopBuyerContext 直接复用主 identityGeneration 作为 generation
 *               契约（isCurrentIdentity/commit 守卫），并重置自己的 cart/wishlist
 *               与操作队列。
 *
 *   消费者（useCachedQuery）只订阅翻转后果（缓存被清空→自愈重取），
 *   从不比较身份本身。
 */
import {
  createContext, useContext, useLayoutEffect, useMemo, useRef, type ReactNode,
} from 'react';
import { useAuth } from '../hooks/useAuth';
import { createQueryCache, type QueryCache } from './queryCache';

const QueryCacheContext = createContext<QueryCache | null>(null);

export function QueryCacheProvider({
  children,
  cache: injected,
}: {
  children: ReactNode;
  /** Optional injected cache (tests share one instance across render trees). */
  cache?: QueryCache;
}) {
  const owned = useMemo(() => createQueryCache(), []);
  const cache = injected ?? owned;
  const { identityGeneration } = useAuth();
  const previousGeneration = useRef(identityGeneration);

  // Layout effect on purpose: it must run before the children's passive
  // subscribe effects. Otherwise a query whose key already carries the new
  // identity (e.g. favorites scoped by principal) starts one fetch in its
  // subscribe effect, has it aborted by this clear, and then refetches via
  // self-healing — two requests per identity transition.
  useLayoutEffect(() => {
    if (previousGeneration.current !== identityGeneration) {
      previousGeneration.current = identityGeneration;
      cache.clear();
    }
  }, [identityGeneration, cache]);

  return <QueryCacheContext.Provider value={cache}>{children}</QueryCacheContext.Provider>;
}

export function useQueryCache(): QueryCache {
  const cache = useContext(QueryCacheContext);
  if (!cache) throw new Error('useQueryCache must be used within QueryCacheProvider');
  return cache;
}
