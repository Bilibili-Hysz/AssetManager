import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { ArrowRight, Moon, RefreshCw, SlidersHorizontal, Sun, X } from 'lucide-react';
import { Link, Navigate } from 'react-router-dom';
import { useMetadataApi } from '../hooks/usePageApis';
import { LayeredPreview } from '../components/files/LayeredPreview';
import { useAuth } from '../hooks/useAuth';
import { useCachedQuery } from '../hooks/useCachedQuery';
import { useTheme } from '../hooks/useTheme';
import { useI18n } from '../hooks/useI18n';
import type { HomeData, PreviewPoolItem } from '../types/api';
import './LandingPage.css';

type FeaturedStatus = 'loading' | 'online' | 'empty' | 'unavailable' | 'decode-error';
type MotionQuery = MediaQueryList & { addListener?: (listener: (event: MediaQueryListEvent) => void) => void; removeListener?: (listener: (event: MediaQueryListEvent) => void) => void };

interface BackgroundSettings {
  blur: number;
  brightness: number;
  saturation: number;
  canvasOpacity: number;
  itemOpacity: number;
}

const darkBackgroundDefaults: BackgroundSettings = {
  blur: 6,
  brightness: 12,
  saturation: 70,
  canvasOpacity: 100,
  itemOpacity: 60,
};

const lightBackgroundDefaults: BackgroundSettings = {
  blur: 4,
  brightness: 100,
  saturation: 85,
  canvasOpacity: 55,
  itemOpacity: 60,
};

const backgroundFields = [
  ['blur', 'blur', 0, 16, 'px'],
  ['brightness', 'brightness', 5, 150, '%'],
  ['saturation', 'saturation', 0, 150, '%'],
  ['canvasOpacity', 'canvas_opacity', 10, 100, '%'],
  ['itemOpacity', 'item_opacity', 10, 100, '%'],
] as const;

const fallbackAccent = '#6366f1';
function isValidAccent(value: string | undefined): value is string {
  return Boolean(value && /^#[\da-f]{6}$/i.test(value));
}

function themeName(isLight: boolean): 'dark' | 'light' {
  return isLight ? 'light' : 'dark';
}

function defaultsForTheme(isLight: boolean): BackgroundSettings {
  return isLight ? lightBackgroundDefaults : darkBackgroundDefaults;
}

function backgroundStorageKey(accent: string | undefined): string {
  return `assets-manager.gate-background.${accent || 'default'}`;
}

function readBackgroundSettings(key: string, isLight: boolean): BackgroundSettings {
  const defaults = defaultsForTheme(isLight);
  try {
    const stored = JSON.parse(window.localStorage.getItem(key) || 'null') as Record<string, unknown> | null;
    const themeSettings = stored?.[themeName(isLight)];
    const source: Partial<BackgroundSettings> = themeSettings && typeof themeSettings === 'object'
      ? themeSettings as Partial<BackgroundSettings>
      : stored as Partial<BackgroundSettings> | null || {};
    return {
      blur: typeof source.blur === 'number' ? source.blur : defaults.blur,
      brightness: typeof source.brightness === 'number' ? source.brightness : defaults.brightness,
      saturation: typeof source.saturation === 'number' ? source.saturation : defaults.saturation,
      canvasOpacity: typeof source.canvasOpacity === 'number' ? source.canvasOpacity : defaults.canvasOpacity,
      itemOpacity: typeof source.itemOpacity === 'number' ? source.itemOpacity : defaults.itemOpacity,
    };
  } catch {
    return defaults;
  }
}

function saveBackgroundSettings(key: string, isLight: boolean, settings: BackgroundSettings): void {
  try {
    const stored = JSON.parse(window.localStorage.getItem(key) || 'null') as { dark?: BackgroundSettings; light?: BackgroundSettings } | null;
    window.localStorage.setItem(key, JSON.stringify({
      ...(stored && typeof stored === 'object' ? stored : {}),
      [themeName(isLight)]: settings,
    }));
  } catch {
    // Visual tuning remains usable when storage is unavailable.
  }
}

function calculateWallCount(): number {
  const width = typeof window === 'undefined' ? 1440 : window.innerWidth;
  const height = typeof window === 'undefined' ? 900 : window.innerHeight;
  return Math.min(72, Math.max(12, Math.ceil(width / 160) * Math.ceil(height / 130)));
}

function shuffle<T>(items: T[]): T[] {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    const current = result[index]!;
    result[index] = result[swapIndex]!;
    result[swapIndex] = current;
  }
  return result;
}

function useReducedMotion(): boolean {
  const [reducedMotion, setReducedMotion] = useState(() => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const query = window.matchMedia('(prefers-reduced-motion: reduce)') as MotionQuery;
    const update = (event: MediaQueryListEvent) => setReducedMotion(event.matches);
    if (typeof query.addEventListener === 'function') {
      query.addEventListener('change', update);
    } else {
      query.addListener?.(update);
    }
    return () => {
      if (typeof query.removeEventListener === 'function') {
        query.removeEventListener('change', update);
      } else {
        query.removeListener?.(update);
      }
    };
  }, []);

  return reducedMotion;
}

export default function LandingPage() {
  const { serverInfo, isLoading, isAuthenticated, role, serviceUnavailable, retryConnect } = useAuth();
  const { t } = useI18n();
  const metadataApi = useMetadataApi();
  const { theme, toggleTheme: toggleSharedTheme } = useTheme();
  const isProtected = Boolean(serverInfo?.auth_enabled && (!isAuthenticated || role === 'guest'));
  const [previewPool, setPreviewPool] = useState<PreviewPoolItem[]>([]);
  const [showcaseUrls, setShowcaseUrls] = useState<string[]>([]);
  const [failedUrls, setFailedUrls] = useState<Set<string>>(() => new Set());
  const [featuredStatus, setFeaturedStatus] = useState<FeaturedStatus>('loading');
  const [homeStats, setHomeStats] = useState<{ total_projects: number; total_size: number; total_size_fmt: string } | null>(null);
  const [tuningOpen, setTuningOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const isLight = theme === 'light';
  const [settings, setSettings] = useState<BackgroundSettings>(() => readBackgroundSettings(backgroundStorageKey(serverInfo?.theme_color), isLight));
  const [isPageVisible, setIsPageVisible] = useState(() => typeof document === 'undefined' || document.visibilityState !== 'hidden');
  const [wallCount, setWallCount] = useState(calculateWallCount);
  const [cursorPosition, setCursorPosition] = useState<{ x: number; y: number } | null>(null);
  const reducedMotion = useReducedMotion();
  const effectNodes = useRef<HTMLElement[]>([]);
  const effectTimers = useRef<ReturnType<typeof window.setTimeout>[]>([]);
  const lastParticleAt = useRef(0);
  const mounted = useRef(true);

  const serverAccent = serverInfo?.theme_color;
  const accent = isValidAccent(serverAccent) ? serverAccent : fallbackAccent;
  const storageKey = useMemo(() => backgroundStorageKey(accent), [accent]);
  const visiblePool = useMemo(() => previewPool.filter(item => item.thumbnail_url && !failedUrls.has(item.thumbnail_url)), [failedUrls, previewPool]);
  const stats = homeStats ?? serverInfo?.library_stats ?? { total_projects: 0, total_size: 0, total_size_fmt: '0 B' };
  const canRotate = featuredStatus === 'online' && isPageVisible && !reducedMotion && visiblePool.length > showcaseUrls.length;
  const wallItems = visiblePool.length
    ? Array.from({ length: wallCount }, (_, index) => visiblePool[index % visiblePool.length])
    : [];

  const handleFeaturedFailure = useCallback((url: string) => {
    setFailedUrls(current => {
      if (current.has(url)) return current;
      const next = new Set(current);
      next.add(url);
      return next;
    });
  }, [visiblePool]);

  // The hero pool lives in the shared cache; fetching is gated until the
  // session resolves (the pre-cache refreshHome skipped the same cases).
  const { data: homeData, error: homeError } = useCachedQuery<HomeData>({
    key: ['home'],
    queryFn: signal => metadataApi.getHome(signal),
    domains: ['home'],
    enabled: !isLoading && !isProtected,
  });

  // Each fresh response rebuilds the deduped + shuffled preview pool and the
  // showcase rotation; the shuffle is deliberately local state, not cache.
  useEffect(() => {
    if (homeData === undefined) return;
    const projects = homeData.preview_pool === undefined ? homeData.recent_projects : homeData.preview_pool;
    const seenUrls = new Set<string>();
    const candidates = projects.reduce<PreviewPoolItem[]>((items, item) => {
      const url = item.thumbnail_url?.trim();
      if (!url || seenUrls.has(url)) return items;
      seenUrls.add(url);
      items.push({ name: item.name, path: item.path, thumbnail_url: url });
      return items;
    }, []);
    const shuffledPool = shuffle(candidates);
    setPreviewPool(shuffledPool);
    setShowcaseUrls(shuffledPool.slice(0, 6).flatMap(item => item.thumbnail_url ? [item.thumbnail_url] : []));
    setFailedUrls(new Set());
    setHomeStats(homeData.stats);
    setFeaturedStatus(shuffledPool.length ? 'online' : 'empty');
  }, [homeData]);

  // Only a failed FIRST load surfaces the unavailable state; a failed
  // refresh keeps the last good pool visible (cache retain-on-error).
  useEffect(() => {
    if (homeError != null && homeData === undefined) {
      setPreviewPool([]);
      setShowcaseUrls([]);
      setFeaturedStatus('unavailable');
    }
  }, [homeError, homeData]);

  useEffect(() => {
    if (previewPool.length === 0) return undefined;
    const preloaders = previewPool.map(item => {
      const url = item.thumbnail_url!;
      const image = new Image();
      const onError = () => {
        setFailedUrls(current => {
          if (current.has(url)) return current;
          const next = new Set(current);
          next.add(url);
          return next;
        });
      };
      image.addEventListener('error', onError);
      image.src = url;
      return [image, onError] as const;
    });

    return () => preloaders.forEach(([image, onError]) => image.removeEventListener('error', onError));
  }, [previewPool]);

  useEffect(() => {
    setSettings(readBackgroundSettings(storageKey, isLight));
  }, [isLight, storageKey]);

  useEffect(() => {
    const updateVisibility = () => setIsPageVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', updateVisibility);
    return () => document.removeEventListener('visibilitychange', updateVisibility);
  }, []);

  useEffect(() => {
    let resizeTimer: ReturnType<typeof window.setTimeout> | undefined;
    const onResize = () => {
      if (resizeTimer) window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => setWallCount(calculateWallCount()), 200);
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      if (resizeTimer) window.clearTimeout(resizeTimer);
    };
  }, []);

  useEffect(() => {
    if (!tuningOpen) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setTuningOpen(false);
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [tuningOpen]);

  // The tuning panel is a non-modal dialog: move focus into it on open and
  // back to its trigger on close (without stealing focus on initial load).
  const tuningToggleRef = useRef<HTMLButtonElement | null>(null);
  const tuningPanelRef = useRef<HTMLElement | null>(null);
  const tuningWasOpenRef = useRef(false);
  useEffect(() => {
    if (tuningOpen) {
      tuningWasOpenRef.current = true;
      tuningPanelRef.current?.focus();
    } else if (tuningWasOpenRef.current) {
      tuningWasOpenRef.current = false;
      tuningToggleRef.current?.focus();
    }
  }, [tuningOpen]);

  useEffect(() => {
    if (!canRotate || showcaseUrls.length === 0) return undefined;
    let rotationIndex = 0;
    let preloader: HTMLImageElement | null = null;
    const interval = window.setInterval(() => {
      const candidates = visiblePool.filter(item => item.thumbnail_url && !showcaseUrls.includes(item.thumbnail_url));
      if (!candidates.length) return;
      const target = candidates[rotationIndex % candidates.length];
      if (!target) return;
      const slot = rotationIndex % showcaseUrls.length;
      rotationIndex += 1;
      preloader = new Image();
      preloader.onload = () => {
        if (!mounted.current) return;
          setShowcaseUrls(current => current.map((url, index) => index === slot && target.thumbnail_url ? target.thumbnail_url : url));
      };
      preloader.onerror = () => target.thumbnail_url && handleFeaturedFailure(target.thumbnail_url);
      preloader.src = target.thumbnail_url || '';
    }, 20_000);
    return () => {
      window.clearInterval(interval);
      if (preloader) {
        preloader.onload = null;
        preloader.onerror = null;
      }
    };
  }, [canRotate, handleFeaturedFailure, showcaseUrls, visiblePool]);

  const removeEffectNode = useCallback((node: HTMLElement) => {
    effectNodes.current = effectNodes.current.filter(current => current !== node);
    node.remove();
  }, []);

  const onPointerMove = useCallback((event: React.PointerEvent<HTMLElement>) => {
    if (reducedMotion || !isPageVisible || !mounted.current || event.pointerType === 'touch') return;
    setCursorPosition({ x: event.clientX, y: event.clientY });
    const now = Date.now();
    if (now - lastParticleAt.current < 66) return;
    lastParticleAt.current = now;
    Array.from({ length: 3 }, (_, index) => {
      const particle = document.createElement('span');
      particle.className = 'gate-particle';
      particle.style.setProperty('--gate-effect-color', accent);
      particle.style.left = `${event.clientX + (Math.random() - 0.5) * (16 + index * 10)}px`;
      particle.style.top = `${event.clientY + (Math.random() - 0.5) * (16 + index * 10)}px`;
      particle.style.animationDelay = `${index * 35}ms`;
      document.body.appendChild(particle);
      effectNodes.current.push(particle);
      let timer: ReturnType<typeof window.setTimeout>;
      timer = window.setTimeout(() => {
        effectTimers.current = effectTimers.current.filter(current => current !== timer);
        removeEffectNode(particle);
      }, 700 + index * 35);
      effectTimers.current.push(timer);
    });
  }, [accent, isPageVisible, reducedMotion, removeEffectNode]);

  const onPointerDown = useCallback((event: React.PointerEvent<HTMLElement>) => {
    if (reducedMotion || !isPageVisible || !mounted.current || event.pointerType === 'touch') return;
    [700, 900].forEach((duration, index) => {
      const ripple = document.createElement('span');
      ripple.className = `gate-ripple gate-ripple-${index + 1}`;
      ripple.style.setProperty('--gate-effect-color', accent);
      ripple.style.borderColor = accent;
      ripple.style.left = `${event.clientX}px`;
      ripple.style.top = `${event.clientY}px`;
      ripple.style.animationDuration = `${duration}ms`;
      document.body.appendChild(ripple);
      effectNodes.current.push(ripple);
      let timer: ReturnType<typeof window.setTimeout>;
      timer = window.setTimeout(() => {
        effectTimers.current = effectTimers.current.filter(current => current !== timer);
        removeEffectNode(ripple);
      }, duration + 80);
      effectTimers.current.push(timer);
    });
  }, [accent, isPageVisible, reducedMotion, removeEffectNode]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      effectTimers.current.forEach(timer => window.clearTimeout(timer));
      effectTimers.current = [];
      effectNodes.current.forEach(node => node.remove());
      effectNodes.current = [];
    };
  }, []);

  const updateSetting = (key: keyof BackgroundSettings, value: number) => {
    const next = { ...settings, [key]: value };
    setSettings(next);
    saveBackgroundSettings(storageKey, isLight, next);
  };

  const resetSettings = () => {
    const next = defaultsForTheme(isLight);
    setSettings(next);
    saveBackgroundSettings(storageKey, isLight, next);
  };

  const toggleTheme = () => {
    toggleSharedTheme();
  };

  const gateStyle = {
    '--gate-accent': accent,
    '--gate-wall-blur': `${settings.blur}px`,
    '--gate-wall-brightness': `${settings.brightness}%`,
    '--gate-wall-saturation': `${settings.saturation}%`,
    '--gate-wall-opacity': `${settings.canvasOpacity / 100}`,
    '--gate-item-opacity': `${settings.itemOpacity / 100}`,
  } as CSSProperties;

  if (isLoading) {
    return <main className="gate gate-loading" aria-label={t('landing.loading')}><div className="gate-loading-bar" /></main>;
  }

  if (serviceUnavailable) {
    return (
      <main className="gate gate-loading" aria-label={t('landing.service_unavailable')}>
        <div className="flex flex-col items-center gap-4 text-center p-8">
          <div className="text-slate-400 text-5xl" aria-hidden="true">⚠</div>
          <h1 className="text-xl font-semibold text-slate-200">{t('landing.service_unavailable')}</h1>
          <p className="text-sm text-slate-400 max-w-md">
            {t('landing.service_unavailable_description')}
          </p>
          <button
            type="button"
            onClick={() => {
              if (retrying) return;
              setRetrying(true);
              void retryConnect().finally(() => setRetrying(false));
            }}
            disabled={retrying}
            className="flex items-center gap-2 px-4 py-2 text-sm text-white bg-brand-600 hover:bg-brand-700 rounded-lg transition-colors"
          >
            <RefreshCw size={16} aria-hidden="true" />
            {t('landing.retry')}
          </button>
        </div>
      </main>
    );
  }

  if (isProtected) return <Navigate to="/login" replace />;

  const name = serverInfo?.share_name || 'My Asset Library';
  const username = serverInfo?.principal?.authenticated ? serverInfo.principal.display_name : 'Designer';
  const avatar = username.slice(0, 1).toUpperCase();
  const imageStatus = featuredStatus === 'online' || featuredStatus === 'empty'
    ? `${homeStats?.total_projects ?? stats.total_projects} ${t('landing.artworks')}`
    : featuredStatus === 'unavailable' ? t('landing.status_unavailable')
      : featuredStatus === 'decode-error' ? t('landing.status_error')
        : t('landing.status_checking');
  const serviceStatus = serverInfo ? t('landing.status_online') : t('landing.status_unavailable');
  const rotationStatus = canRotate ? t('landing.showcase_auto') : t('landing.showcase_static');

  return (
    <main className={`gate ${isLight ? 'gate-light' : ''} ${isPageVisible ? '' : 'gate-paused'}`} style={gateStyle} onPointerMove={onPointerMove} onPointerDown={onPointerDown}>
      {cursorPosition && <span className="gate-cursor-glow" aria-hidden="true" style={{ left: `${cursorPosition.x}px`, top: `${cursorPosition.y}px` }} />}
      <button type="button" className="gate-theme-toggle" aria-label={isLight ? t('gallery.theme_dark') : t('gallery.theme_light')} aria-pressed={isLight} onClick={toggleTheme} title={isLight ? t('gallery.theme_dark') : t('gallery.theme_light')}>
        {isLight ? <Moon size={17} aria-hidden="true" /> : <Sun size={17} aria-hidden="true" />}
      </button>

      <div className={`gate-image-wall ${isPageVisible ? '' : 'gate-wall-paused'}`} aria-hidden="true">
        {wallItems.length ? wallItems.map((item, index) => item && item.thumbnail_url && (
          <div className="gate-wall-item" key={`${item.thumbnail_url}-${index}`} style={{ '--gate-index': index } as CSSProperties}>
            <img src={item.thumbnail_url} alt="" loading="lazy" draggable={false} onError={() => handleFeaturedFailure(item.thumbnail_url!)} />
          </div>
        )) : Array.from({ length: wallCount }, (_, index) => <div className="gate-wall-item gate-wall-placeholder" key={`placeholder-${index}`} style={{ '--gate-index': index } as CSSProperties} />)}
      </div>
      <div className="gate-overlay" aria-hidden="true" />
      <div className="gate-decoration gate-decoration-primary" aria-hidden="true" />
      <div className="gate-decoration gate-decoration-secondary" aria-hidden="true" />
      <div className="gate-sweep" aria-hidden="true" />

      <section className="gate-center">
        <div className="gate-avatar-ring gate-rise" aria-hidden="true"><div className="gate-avatar">{avatar}</div></div>
        <p className="gate-username gate-rise">{username}</p>
        <h1 className="gate-repository gate-rise">{name}</h1>
        <p className="gate-purpose gate-rise">{t('landing.library_purpose')}</p>

        {showcaseUrls.length > 0 && <div className="gate-showcase gate-rise" role="group" aria-label={t('landing.featured_assets')}>
          {showcaseUrls.map(url => {
            const item = previewPool.find(candidate => candidate.thumbnail_url === url);
            if (!item) return null;
            return <div className="gate-showcase-item" key={url}>
              <div data-testid="gate-showcase-image" data-src={url} onErrorCapture={() => handleFeaturedFailure(url)}>
                <LayeredPreview src={url} alt={item.name} isDir size="grid" />
              </div>
            </div>;
          })}
        </div>}

        <div className="gate-status-row gate-rise" aria-label={t('landing.library_status')} role="status" aria-live="polite">
          <span className={`gate-status-pill ${featuredStatus === 'unavailable' || featuredStatus === 'decode-error' ? 'gate-status-error' : ''}`}><span className="gate-status-value">{imageStatus}</span>{featuredStatus === 'unavailable' && <span className="sr-only">Library unavailable</span>}</span>
          <span className={`gate-status-pill ${serviceStatus === t('landing.status_unavailable') ? 'gate-status-error' : ''}`}><span className="gate-status-value">{serviceStatus}</span> {t('landing.local_service')}</span>
          <span className={`gate-status-pill ${rotationStatus === t('landing.showcase_static') ? 'gate-status-paused' : ''}`}><span className="gate-status-value">{rotationStatus}</span> {t('landing.showcase')}</span>
        </div>

        {featuredStatus === 'unavailable' && <p className="gate-message gate-message-error" role="alert">{t('landing.featured_unavailable')}</p>}
        {featuredStatus === 'empty' && <p className="gate-message">{t('landing.no_images')}</p>}
        {featuredStatus === 'decode-error' && <p className="gate-message gate-message-error" role="alert">{t('landing.previews_unavailable')}</p>}

        <div className="gate-entry-options gate-rise">
          <Link className="gate-enter" to="/gallery" aria-label={t('landing.enter_aria')}>
            <ArrowRight size={18} aria-hidden="true" />
            <span>{t('landing.enter')}</span>
          </Link>
          {/* Single secondary entry: the whole option is one link so the hit
              area covers the copy and the accessible name carries both the
              title and the description. The previous structure (unstyled copy
              block + a duplicate bare "Open Workspace" link) glued the strings
              together and rendered a redundant second target. */}
          <Link className="gate-workspace-option" to="/browse">
            <strong>{t('landing.workspace')}</strong>
            <span>{t('landing.workspace_description')}</span>
          </Link>
        </div>
        <p className="gate-stats gate-rise">{t('landing.asset_count', stats.total_projects)} · {stats.total_size_fmt || '0 B'} · {serverInfo?.footer_text || t('landing.footer_ready')}</p>
      </section>

      <button ref={tuningToggleRef} type="button" className="gate-tuning-toggle" aria-label={t('landing.background_tuning')} aria-expanded={tuningOpen} aria-controls="background-tuning" onClick={() => setTuningOpen(open => !open)}>
        <SlidersHorizontal size={16} aria-hidden="true" />
        <span>{t('landing.background')}</span>
      </button>

      {tuningOpen && (
        <section ref={tuningPanelRef} tabIndex={-1} id="background-tuning" role="dialog" aria-modal="false" aria-label={t('landing.background_tuning')} className="gate-tuning-panel max-h-[calc(100dvh-2rem)] overflow-y-auto">
          <div className="gate-tuning-header"><h2>{t('landing.background_tuning')}</h2><button type="button" className="gate-icon-button" aria-label={t('landing.close_background_tuning')} onClick={() => setTuningOpen(false)}><X size={18} aria-hidden="true" /></button></div>
          <div className="gate-tuning-fields">
            {backgroundFields.map(([key, label, min, max, suffix]) => (
              <label className="gate-tuning-field" key={key}>
                <span>{t(`landing.${label}`)}</span>
                <output>{settings[key]}{suffix}</output>
                <input type="range" aria-label={t(`landing.${label}`)} min={min} max={max} value={settings[key]} onChange={event => updateSetting(key, Number(event.target.value))} />
              </label>
            ))}
          </div>
          <button type="button" className="gate-reset-button" onClick={resetSettings}>{t('landing.reset_theme')}</button>
        </section>
      )}
    </main>
  );
}
